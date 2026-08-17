"""MCP protocol dispatch for the Sync Licensing server.

Implements the handshake and the tool methods of the Model Context Protocol
directly on top of :mod:`synclicense_mcp.jsonrpc`. Every message is built and
validated by hand; no MCP SDK is involved.

Methods handled:

===============================  ====================================
``initialize``                   negotiate version, advertise tools
``notifications/initialized``    consumed, marks the session ready
``ping``                         liveness check
``tools/list``                   publish the tool descriptors
``tools/call``                   validate arguments and run a tool
===============================  ====================================
"""

from __future__ import annotations

import sys
import traceback
from typing import Any, TextIO

from . import (
    PREFERRED_PROTOCOL_VERSION,
    SERVER_NAME,
    SUPPORTED_PROTOCOL_VERSIONS,
    __version__,
)
from . import jsonrpc
from . import tools as tools_mod
from .catalog import Catalogo
from .errors import ErrorDeNegocio
from .jsonrpc import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    SERVER_NOT_INITIALIZED,
    JsonRpcError,
)

INSTRUCCIONES = (
    "Sync licensing assistant for a Creative Commons music catalog. "
    "Use buscar_pista to shortlist tracks by creative brief and budget, "
    "verificar_clearance to confirm a track is legally usable, "
    "calcular_costo_licencia to quote it for a specific use, territory, "
    "exclusivity and term, generar_contrato to turn an accepted quote into a "
    "licence, and registrar_uso to register the deployment. The tools are "
    "chained: a contract requires a valid quote id, and a usage record "
    "requires an active contract id."
)

# Requests allowed before the initialize handshake has completed.
METODOS_SIN_HANDSHAKE = {"initialize", "ping"}


class Sesion:
    """State that lives for as long as the client stays connected.

    Quotes and contracts are held here rather than on disk because they belong
    to one negotiation: this is what forces the assistant to carry context from
    one tool call to the next.
    """

    def __init__(self, catalogo: Catalogo) -> None:
        self.catalogo = catalogo
        self.cotizaciones: dict[str, dict] = {}
        self.contratos: dict[str, dict] = {}
        self.inicializada = False
        self.protocol_version = PREFERRED_PROTOCOL_VERSION
        self.cliente: dict[str, Any] = {}


class Servidor:
    """Reads JSON-RPC messages from a stream and answers them."""

    def __init__(
        self,
        catalogo: Catalogo,
        entrada: TextIO | None = None,
        salida: TextIO | None = None,
    ) -> None:
        self.sesion = Sesion(catalogo)
        self.entrada = entrada if entrada is not None else sys.stdin
        self.salida = salida if salida is not None else sys.stdout

    # ---------------------------------------------------------------- loop

    def ejecutar(self) -> None:
        """Serve requests until stdin reaches EOF."""
        jsonrpc.log(
            f"listening on stdio · catalog: {len(self.sesion.catalogo)} tracks "
            f"(source: {self.sesion.catalogo.fuente})"
        )
        while True:
            try:
                mensaje = jsonrpc.read_message(self.entrada)
            except JsonRpcError as exc:
                # A line we could not parse has no id, so it must be null.
                jsonrpc.write_message(self.salida, jsonrpc.make_error(None, exc))
                continue

            if mensaje is None:
                jsonrpc.log("stdin closed, shutting down")
                return

            respuesta = self.manejar_mensaje(mensaje)
            if respuesta is not None:
                jsonrpc.write_message(self.salida, respuesta)

    def manejar_mensaje(self, mensaje: dict) -> dict | None:
        """Route one message. Returns None for notifications."""
        request_id = mensaje.get("id")
        try:
            metodo, params, request_id, es_notificacion = jsonrpc.parse_request(mensaje)
        except JsonRpcError as exc:
            return jsonrpc.make_error(request_id, exc)

        try:
            resultado = self._despachar(metodo, params, es_notificacion)
        except JsonRpcError as exc:
            if es_notificacion:
                jsonrpc.log(f"error in notification '{metodo}': {exc.message}")
                return None
            return jsonrpc.make_error(request_id, exc)
        except Exception as exc:  # unexpected: never let the server die
            traceback.print_exc(file=sys.stderr)
            if es_notificacion:
                return None
            return jsonrpc.make_error(
                request_id, JsonRpcError(INTERNAL_ERROR, "Internal error", str(exc))
            )

        if es_notificacion:
            return None
        return jsonrpc.make_response(request_id, resultado)

    # ------------------------------------------------------------ dispatch

    def _despachar(self, metodo: str, params: dict, es_notificacion: bool) -> Any:
        if metodo == "initialize":
            return self._initialize(params)

        if metodo == "notifications/initialized":
            self.sesion.inicializada = True
            jsonrpc.log("handshake complete, session ready")
            return None

        if metodo.startswith("notifications/"):
            # Unknown notifications are ignored, as the specification requires.
            jsonrpc.log(f"ignoring unknown notification '{metodo}'")
            return None

        if not self.sesion.inicializada and metodo not in METODOS_SIN_HANDSHAKE:
            raise JsonRpcError(
                SERVER_NOT_INITIALIZED,
                "Server not initialized: send 'initialize' before any other request",
            )

        if metodo == "ping":
            return {}
        if metodo == "tools/list":
            return {"tools": tools_mod.listar_descriptores()}
        if metodo == "tools/call":
            return self._tools_call(params)

        raise JsonRpcError(METHOD_NOT_FOUND, f"Method not found: {metodo}")

    def _initialize(self, params: dict) -> dict:
        """Negotiate the protocol version and advertise capabilities.

        If the client asks for a revision we do not implement, we answer with
        our preferred one and let the client decide whether to continue, which
        is the behaviour the specification prescribes.
        """
        pedida = params.get("protocolVersion")
        if pedida in SUPPORTED_PROTOCOL_VERSIONS:
            acordada = pedida
        else:
            acordada = PREFERRED_PROTOCOL_VERSION
            jsonrpc.log(
                f"client asked for protocol '{pedida}', offering '{acordada}' instead"
            )

        self.sesion.protocol_version = acordada
        self.sesion.cliente = params.get("clientInfo", {}) or {}
        jsonrpc.log(
            f"initialize from {self.sesion.cliente.get('name', 'unknown client')} "
            f"· protocol {acordada}"
        )

        return {
            "protocolVersion": acordada,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": SERVER_NAME,
                "title": "Sync Licensing Assistant",
                "version": __version__,
            },
            "instructions": INSTRUCCIONES,
        }

    def _tools_call(self, params: dict) -> dict:
        """Run a tool and shape the result the way ``tools/call`` requires."""
        nombre = params.get("name")
        if not isinstance(nombre, str) or not nombre:
            raise JsonRpcError(jsonrpc.INVALID_PARAMS, "Missing tool 'name'")
        argumentos = params.get("arguments", {}) or {}

        try:
            resultado = tools_mod.ejecutar(nombre, argumentos, self.sesion)
        except ErrorDeNegocio as exc:
            # A refusal by the licensing rules is a successful call with a
            # negative answer, not a protocol failure.
            jsonrpc.log(f"tool '{nombre}' refused: {exc.motivo}")
            return {
                "content": [{"type": "text", "text": exc.mensaje}],
                "structuredContent": {
                    "ok": False,
                    "motivo": exc.motivo,
                    **exc.datos,
                },
                "isError": True,
            }

        return {
            "content": [{"type": "text", "text": resultado.texto}],
            "structuredContent": {"ok": True, **resultado.datos},
            "isError": False,
        }
