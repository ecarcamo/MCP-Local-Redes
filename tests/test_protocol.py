"""Tests for the JSON-RPC framing and the MCP method dispatch.

Most tests drive the :class:`Servidor` in-process, which keeps them fast. The
last one launches the real ``python -m synclicense_mcp`` subprocess so the stdio
transport itself is covered end to end.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from synclicense_mcp import jsonrpc
from synclicense_mcp.catalog import REPO_ROOT
from synclicense_mcp.server import Servidor

TOOLS_ESPERADAS = {
    "buscar_pista",
    "verificar_clearance",
    "calcular_costo_licencia",
    "generar_contrato",
    "registrar_uso",
}


def request(servidor: Servidor, id_: int, metodo: str, params: dict | None = None) -> dict:
    mensaje = {"jsonrpc": "2.0", "id": id_, "method": metodo}
    if params is not None:
        mensaje["params"] = params
    return servidor.manejar_mensaje(mensaje)


def llamar(servidor: Servidor, nombre: str, argumentos: dict, id_: int = 99) -> dict:
    return request(servidor, id_, "tools/call", {"name": nombre, "arguments": argumentos})


# --------------------------------------------------------------- handshake


def test_initialize_negocia_la_version_del_protocolo(catalogo):
    srv = Servidor(catalogo)
    respuesta = request(
        srv,
        1,
        "initialize",
        {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t"}},
    )
    resultado = respuesta["result"]
    assert resultado["protocolVersion"] == "2025-11-25"
    assert resultado["capabilities"]["tools"] == {"listChanged": False}
    assert resultado["serverInfo"]["name"] == "synclicense-mcp"


def test_una_version_desconocida_recibe_la_preferida(catalogo):
    """The server offers its own revision instead of failing the handshake."""
    srv = Servidor(catalogo)
    respuesta = request(
        srv, 1, "initialize", {"protocolVersion": "1999-01-01", "capabilities": {}}
    )
    assert respuesta["result"]["protocolVersion"] == "2025-11-25"


def test_las_notificaciones_no_reciben_respuesta(servidor):
    """A message without 'id' must never be answered, per JSON-RPC 2.0."""
    assert servidor.manejar_mensaje(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    ) is None


def test_se_rechazan_peticiones_antes_del_handshake(catalogo):
    srv = Servidor(catalogo)
    respuesta = request(srv, 1, "tools/list")
    assert respuesta["error"]["code"] == jsonrpc.SERVER_NOT_INITIALIZED


def test_ping_responde_antes_del_handshake(catalogo):
    srv = Servidor(catalogo)
    assert request(srv, 1, "ping")["result"] == {}


# ------------------------------------------------------------ envelope rules


def test_falta_la_version_de_jsonrpc(servidor):
    respuesta = servidor.manejar_mensaje({"id": 1, "method": "ping"})
    assert respuesta["error"]["code"] == jsonrpc.INVALID_REQUEST


def test_metodo_desconocido(servidor):
    assert request(servidor, 1, "no/existe")["error"]["code"] == jsonrpc.METHOD_NOT_FOUND


def test_una_linea_invalida_es_un_error_de_parseo():
    import io

    with pytest.raises(jsonrpc.JsonRpcError) as exc:
        jsonrpc.read_message(io.StringIO("{no es json}\n"))
    assert exc.value.code == jsonrpc.PARSE_ERROR


def test_los_mensajes_se_serializan_en_una_sola_linea():
    """The stdio transport breaks if a message spans more than one line."""
    import io

    salida = io.StringIO()
    jsonrpc.write_message(salida, {"jsonrpc": "2.0", "id": 1, "result": {"t": "a\nb"}})
    escrito = salida.getvalue()
    assert escrito.count("\n") == 1 and escrito.endswith("\n")


# -------------------------------------------------------------- tools/list


def test_tools_list_publica_las_cinco_herramientas(servidor):
    tools = request(servidor, 1, "tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == TOOLS_ESPERADAS
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["description"]


# -------------------------------------------------------------- tools/call


def test_buscar_pista_filtra_por_presupuesto(servidor):
    resultado = llamar(servidor, "buscar_pista", {"presupuesto_max": 30, "limite": 5})["result"]
    assert resultado["isError"] is False
    for pista in resultado["structuredContent"]["pistas"]:
        assert pista["tarifa_base_usd"] <= 30


def test_buscar_pista_excluye_las_bloqueadas(servidor):
    resultado = llamar(servidor, "buscar_pista", {"limite": 20})["result"]
    estados = {p["estado_derechos"] for p in resultado["structuredContent"]["pistas"]}
    assert "bloqueada" not in estados


def test_una_tool_desconocida_es_invalid_params(servidor):
    assert llamar(servidor, "no_existe", {})["error"]["code"] == jsonrpc.INVALID_PARAMS


def test_falta_un_argumento_obligatorio(servidor):
    respuesta = llamar(servidor, "verificar_clearance", {})
    assert respuesta["error"]["code"] == jsonrpc.INVALID_PARAMS
    assert "pista_id" in respuesta["error"]["message"]


def test_un_valor_fuera_del_enum_es_invalid_params(servidor):
    respuesta = llamar(
        servidor,
        "calcular_costo_licencia",
        {
            "pista_id": "TRK-00001",
            "tipo_uso": "holograma",
            "territorio": "local",
            "exclusividad": "no",
            "duracion_meses": 6,
        },
    )
    assert respuesta["error"]["code"] == jsonrpc.INVALID_PARAMS


def test_un_tipo_equivocado_es_invalid_params(servidor):
    respuesta = llamar(servidor, "buscar_pista", {"limite": "tres"})
    assert respuesta["error"]["code"] == jsonrpc.INVALID_PARAMS


def test_un_argumento_desconocido_se_rechaza(servidor):
    respuesta = llamar(servidor, "buscar_pista", {"tempo": 120})
    assert respuesta["error"]["code"] == jsonrpc.INVALID_PARAMS


# ------------------------------------------------------- business rules


def test_una_pista_inexistente_es_error_de_negocio_no_de_protocolo(servidor):
    """A valid call with a bad id answers 'no', it does not fail the transport."""
    respuesta = llamar(servidor, "verificar_clearance", {"pista_id": "TRK-99999"})
    assert "error" not in respuesta
    assert respuesta["result"]["isError"] is True
    assert respuesta["result"]["structuredContent"]["motivo"] == "pista_inexistente"


def test_no_se_cotiza_una_pista_bloqueada(servidor):
    respuesta = llamar(
        servidor,
        "calcular_costo_licencia",
        {
            "pista_id": "TRK-00003",
            "tipo_uso": "cine",
            "territorio": "mundial",
            "exclusividad": "total",
            "duracion_meses": 0,
        },
    )
    assert respuesta["result"]["isError"] is True
    assert respuesta["result"]["structuredContent"]["motivo"] == "pista_bloqueada"


# ----------------------------------------------------------- tool chaining


def _cotizar(servidor, pista_id="TRK-00001"):
    return llamar(
        servidor,
        "calcular_costo_licencia",
        {
            "pista_id": pista_id,
            "tipo_uso": "redes_sociales",
            "territorio": "local",
            "exclusividad": "no",
            "duracion_meses": 6,
        },
    )["result"]["structuredContent"]


def test_flujo_completo_encadenado(servidor):
    """Quote -> contract -> usage, each step consuming the previous id."""
    cotizacion = _cotizar(servidor)
    assert cotizacion["desglose"]["total_usd"] > 0

    contrato = llamar(
        servidor,
        "generar_contrato",
        {
            "pista_id": "TRK-00001",
            "cliente": "Agencia Lumen S.A.",
            "cotizacion_id": cotizacion["cotizacion_id"],
        },
    )["result"]["structuredContent"]
    assert contrato["estado"] == "activo"
    assert contrato["monto_usd"] == cotizacion["desglose"]["total_usd"]

    registro = llamar(
        servidor,
        "registrar_uso",
        {
            "contrato_id": contrato["contrato_id"],
            "plataforma": "Instagram",
            "url_proyecto": "https://example.com/spot",
        },
    )["result"]["structuredContent"]
    assert registro["estado"] == "registrado"
    assert registro["contrato_id"] == contrato["contrato_id"]


def test_no_hay_contrato_sin_cotizacion_valida(servidor):
    respuesta = llamar(
        servidor,
        "generar_contrato",
        {"pista_id": "TRK-00001", "cliente": "X", "cotizacion_id": "COT-INVENTADA"},
    )
    assert respuesta["result"]["isError"] is True
    assert respuesta["result"]["structuredContent"]["motivo"] == "cotizacion_inexistente"


def test_la_cotizacion_debe_corresponder_a_la_pista(servidor):
    cotizacion = _cotizar(servidor, "TRK-00001")
    respuesta = llamar(
        servidor,
        "generar_contrato",
        {
            "pista_id": "TRK-00002",
            "cliente": "X",
            "cotizacion_id": cotizacion["cotizacion_id"],
        },
    )
    assert respuesta["result"]["structuredContent"]["motivo"] == "cotizacion_no_corresponde"


def test_una_cotizacion_expirada_no_genera_contrato(servidor):
    """Quotes hold their price for 30 days; after that they must be redone."""
    cotizacion = _cotizar(servidor)
    servidor.sesion.cotizaciones[cotizacion["cotizacion_id"]]["valida_hasta"] = (
        "2020-01-01T00:00:00+00:00"
    )
    respuesta = llamar(
        servidor,
        "generar_contrato",
        {
            "pista_id": "TRK-00001",
            "cliente": "X",
            "cotizacion_id": cotizacion["cotizacion_id"],
        },
    )
    assert respuesta["result"]["structuredContent"]["motivo"] == "cotizacion_expirada"


def test_no_se_registra_uso_sin_contrato(servidor):
    respuesta = llamar(
        servidor,
        "registrar_uso",
        {"contrato_id": "CTR-INVENTADO", "plataforma": "TikTok", "url_proyecto": "http://x"},
    )
    assert respuesta["result"]["structuredContent"]["motivo"] == "contrato_inexistente"


def test_las_cotizaciones_no_se_comparten_entre_sesiones(catalogo, servidor):
    """A second connection must not see the first one's quotes."""
    cotizacion = _cotizar(servidor)
    otro = Servidor(catalogo)
    request(otro, 1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}})
    otro.manejar_mensaje({"jsonrpc": "2.0", "method": "notifications/initialized"})
    respuesta = llamar(
        otro,
        "generar_contrato",
        {
            "pista_id": "TRK-00001",
            "cliente": "X",
            "cotizacion_id": cotizacion["cotizacion_id"],
        },
    )
    assert respuesta["result"]["structuredContent"]["motivo"] == "cotizacion_inexistente"


# ------------------------------------------------------------- stdio transport


def test_el_servidor_responde_por_stdio_real():
    """Launch the actual process and speak newline-delimited JSON-RPC to it."""
    entrada = "\n".join(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "0"},
                    },
                }
            ),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]
    ) + "\n"

    proceso = subprocess.run(
        [sys.executable, "-m", "synclicense_mcp"],
        input=entrada,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert proceso.returncode == 0

    lineas = [json.loads(l) for l in proceso.stdout.splitlines() if l.strip()]
    # Two requests, one notification: exactly two responses.
    assert len(lineas) == 2
    assert lineas[0]["id"] == 1
    assert {t["name"] for t in lineas[1]["result"]["tools"]} == TOOLS_ESPERADAS
    # Diagnostics must stay off stdout.
    assert "synclicense-mcp" in proceso.stderr
