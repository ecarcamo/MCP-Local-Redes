#!/usr/bin/env python3
"""Command-line MCP client for the Sync Licensing server.

A minimal host: it spawns the server as a subprocess, talks to it over the
stdio transport and prints every JSON-RPC message that crosses the wire, so the
protocol itself is visible rather than hidden behind a library. Like the server,
it is written directly against JSON-RPC 2.0 with no MCP SDK.

Two modes:

    python client/mcp_cli.py --demo          scripted end-to-end licensing flow
    python client/mcp_cli.py --interactive   REPL to call any tool by hand
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

CLIENT_INFO = {"name": "synclicense-mcp-cli", "version": "0.1.0"}
PROTOCOL_VERSION = "2025-11-25"


class Colores:
    """ANSI codes, blanked out when the output is not a terminal."""

    def __init__(self, activo: bool) -> None:
        self.enviado = "\033[36m" if activo else ""   # cyan
        self.recibido = "\033[32m" if activo else ""  # green
        self.error = "\033[31m" if activo else ""     # red
        self.titulo = "\033[1;35m" if activo else ""  # bold magenta
        self.tenue = "\033[90m" if activo else ""     # grey
        self.reset = "\033[0m" if activo else ""


class ClienteMCP:
    """Owns the server subprocess and the request/response bookkeeping."""

    def __init__(self, colores: Colores, catalogo: Path | None = None, verbose: bool = True) -> None:
        self.colores = colores
        self.verbose = verbose
        self._siguiente_id = 1

        comando = [sys.executable, "-m", "synclicense_mcp"]
        if catalogo is not None:
            comando += ["--catalog", str(catalogo)]

        # stderr is inherited on purpose: the server logs there, so its
        # diagnostics interleave with the protocol trace in the terminal.
        self.proceso = subprocess.Popen(
            comando,
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    # ------------------------------------------------------------- transport

    def _traza(self, direccion: str, mensaje: dict) -> None:
        if not self.verbose:
            return
        c = self.colores
        if direccion == "out":
            flecha, color = "-->", c.enviado
        else:
            flecha, color = "<--", c.recibido
        linea = json.dumps(mensaje, ensure_ascii=False, separators=(",", ":"))
        print(f"{color}{flecha} {linea}{c.reset}")

    def enviar_request(self, metodo: str, params: dict | None = None) -> dict:
        """Send a request and block until its response comes back."""
        mensaje: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._siguiente_id,
            "method": metodo,
        }
        self._siguiente_id += 1
        if params is not None:
            mensaje["params"] = params

        self._traza("out", mensaje)
        self.proceso.stdin.write(json.dumps(mensaje, ensure_ascii=False) + "\n")
        self.proceso.stdin.flush()

        linea = self.proceso.stdout.readline()
        if not linea:
            raise RuntimeError("The server closed the connection unexpectedly.")
        respuesta = json.loads(linea)
        self._traza("in", respuesta)
        return respuesta

    def enviar_notificacion(self, metodo: str, params: dict | None = None) -> None:
        """Send a notification. By definition it gets no response."""
        mensaje: dict[str, Any] = {"jsonrpc": "2.0", "method": metodo}
        if params is not None:
            mensaje["params"] = params
        self._traza("out", mensaje)
        self.proceso.stdin.write(json.dumps(mensaje, ensure_ascii=False) + "\n")
        self.proceso.stdin.flush()

    def cerrar(self) -> None:
        if self.proceso.poll() is None:
            self.proceso.stdin.close()
            self.proceso.wait(timeout=5)

    # -------------------------------------------------------------- protocol

    def handshake(self) -> dict:
        """Run initialize + notifications/initialized."""
        respuesta = self.enviar_request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        if "error" in respuesta:
            raise RuntimeError(f"initialize failed: {respuesta['error']}")
        self.enviar_notificacion("notifications/initialized")
        return respuesta["result"]

    def listar_tools(self) -> list[dict]:
        respuesta = self.enviar_request("tools/list")
        return respuesta["result"]["tools"]

    def llamar_tool(self, nombre: str, argumentos: dict) -> dict:
        """Call a tool. Returns the raw response so the caller can see errors."""
        return self.enviar_request(
            "tools/call", {"name": nombre, "arguments": argumentos}
        )


# --------------------------------------------------------------------- output


def imprimir_resultado(respuesta: dict, colores: Colores) -> dict | None:
    """Print the human-readable part of a tools/call response.

    Returns the ``structuredContent`` so the caller can chain the ids it holds
    into the next call, which is the whole point of this workflow.
    """
    c = colores
    if "error" in respuesta:
        error = respuesta["error"]
        print(f"{c.error}JSON-RPC error {error['code']}: {error['message']}{c.reset}")
        if "data" in error:
            print(f"{c.error}  data: {json.dumps(error['data'], ensure_ascii=False)}{c.reset}")
        return None

    resultado = respuesta["result"]
    for bloque in resultado.get("content", []):
        if bloque.get("type") == "text":
            prefijo = c.error if resultado.get("isError") else ""
            reset = c.reset if resultado.get("isError") else ""
            for linea in bloque["text"].splitlines():
                print(f"{prefijo}   {linea}{reset}")
    return resultado.get("structuredContent")


def titulo(texto: str, colores: Colores) -> None:
    print()
    print(f"{colores.titulo}{'=' * 78}{colores.reset}")
    print(f"{colores.titulo}{texto}{colores.reset}")
    print(f"{colores.titulo}{'=' * 78}{colores.reset}")


# ----------------------------------------------------------------- demo mode


def ejecutar_demo(cliente: ClienteMCP, colores: Colores) -> int:
    """Replay the licensing conversation from the approved project proposal.

    Every step feeds on the ids returned by the previous one: nothing is
    hard-coded except the client's stated intent.
    """
    c = colores

    titulo("STEP 0 - Handshake (initialize + notifications/initialized)", c)
    info = cliente.handshake()
    print(f"   server: {info['serverInfo']['name']} v{info['serverInfo']['version']}")
    print(f"   negotiated protocol: {info['protocolVersion']}")

    titulo("STEP 1 - tools/list: what the server exposes", c)
    for tool in cliente.listar_tools():
        print(f"   {tool['name']:<26} {tool['title']}")

    titulo(
        'STEP 2 - "I need an instrumental, upbeat 30-second track for an\n'
        '          Instagram ad, budget $100." -> buscar_pista',
        c,
    )
    datos = imprimir_resultado(
        cliente.llamar_tool(
            "buscar_pista",
            {
                "instrumental": True,
                "mood": "energetico",
                "duracion_seg_max": 40,
                "presupuesto_max": 100,
                "limite": 3,
            },
        ),
        c,
    )
    if not datos or not datos.get("pistas"):
        print(f"{c.error}The demo needs at least one candidate track.{c.reset}")
        return 1

    # The client picks "Sunburst" out of the shortlist, as in the proposal.
    elegida = next(
        (p for p in datos["pistas"] if p["titulo"] == "Sunburst"), datos["pistas"][0]
    )
    pista_id = elegida["pista_id"]
    print(f"\n{c.tenue}   The client picks \"{elegida['titulo']}\" ({pista_id}).{c.reset}")

    titulo('STEP 3 - "Does it have any rights problem?" -> verificar_clearance', c)
    clearance = imprimir_resultado(
        cliente.llamar_tool("verificar_clearance", {"pista_id": pista_id}), c
    )
    if not clearance or not clearance.get("licenciable"):
        print(f"{c.error}Track is not licensable; the flow stops here.{c.reset}")
        return 1

    titulo(
        'STEP 4 - "How much for social media, non-exclusive, six months?"\n'
        "          -> calcular_costo_licencia",
        c,
    )
    cotizacion = imprimir_resultado(
        cliente.llamar_tool(
            "calcular_costo_licencia",
            {
                "pista_id": pista_id,
                "tipo_uso": "redes_sociales",
                "territorio": "local",
                "exclusividad": "no",
                "duracion_meses": 6,
            },
        ),
        c,
    )
    if not cotizacion:
        return 1
    cotizacion_id = cotizacion["cotizacion_id"]

    titulo('STEP 5 - "Perfect, I want to license it." -> generar_contrato', c)
    contrato = imprimir_resultado(
        cliente.llamar_tool(
            "generar_contrato",
            {
                "pista_id": pista_id,
                "cliente": "Agencia Lumen S.A.",
                "cotizacion_id": cotizacion_id,
            },
        ),
        c,
    )
    if not contrato:
        return 1
    contrato_id = contrato["contrato_id"]

    titulo("STEP 6 - Closing the operation -> registrar_uso", c)
    imprimir_resultado(
        cliente.llamar_tool(
            "registrar_uso",
            {
                "contrato_id": contrato_id,
                "plataforma": "Instagram",
                "url_proyecto": "https://instagram.com/p/lumen-verano-2026",
            },
        ),
        c,
    )

    titulo("STEP 7 - Business rules refusing invalid operations", c)
    print(f"{c.tenue}   7a. Quoting a track frozen by an authorship dispute:{c.reset}")
    imprimir_resultado(
        cliente.llamar_tool(
            "calcular_costo_licencia",
            {
                "pista_id": "TRK-00003",
                "tipo_uso": "cine",
                "territorio": "mundial",
                "exclusividad": "total",
                "duracion_meses": 0,
            },
        ),
        c,
    )
    print(f"\n{c.tenue}   7b. Issuing a contract from a quote for a different track:{c.reset}")
    imprimir_resultado(
        cliente.llamar_tool(
            "generar_contrato",
            {
                "pista_id": "TRK-00002",
                "cliente": "Agencia Lumen S.A.",
                "cotizacion_id": cotizacion_id,
            },
        ),
        c,
    )
    print(f"\n{c.tenue}   7c. Calling a tool with an invalid enum value "
          f"(protocol-level error, not a business one):{c.reset}")
    imprimir_resultado(
        cliente.llamar_tool(
            "calcular_costo_licencia",
            {
                "pista_id": pista_id,
                "tipo_uso": "holograma",
                "territorio": "local",
                "exclusividad": "no",
                "duracion_meses": 6,
            },
        ),
        c,
    )

    titulo("Demo finished", c)
    print(f"   quote:    {cotizacion_id}")
    print(f"   contract: {contrato_id}")
    print("   Each step consumed an id produced by the previous one.")
    return 0


# ---------------------------------------------------------- interactive mode

AYUDA = """
Commands:
  list                      show the tools published by the server
  schema <tool>             show the JSON Schema of one tool
  call <tool> <json-args>   call a tool, e.g.
                            call verificar_clearance {"pista_id": "TRK-00001"}
  ping                      send a JSON-RPC ping
  raw <method> [json]       send any JSON-RPC method by hand
  help                      show this help
  quit                      close the session
"""


def ejecutar_interactivo(cliente: ClienteMCP, colores: Colores) -> int:
    c = colores
    info = cliente.handshake()
    print(
        f"\nConnected to {info['serverInfo']['name']} v{info['serverInfo']['version']} "
        f"(protocol {info['protocolVersion']})"
    )
    print(AYUDA)

    tools = {t["name"]: t for t in cliente.listar_tools()}

    while True:
        try:
            entrada = input(f"{c.titulo}mcp>{c.reset} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not entrada:
            continue

        partes = entrada.split(None, 1)
        comando = partes[0].lower()
        resto = partes[1] if len(partes) > 1 else ""

        if comando in ("quit", "exit"):
            return 0
        if comando == "help":
            print(AYUDA)
            continue
        if comando == "list":
            for nombre, tool in tools.items():
                print(f"  {nombre:<26} {tool['title']}")
                print(f"    {c.tenue}{tool['description']}{c.reset}")
            continue
        if comando == "schema":
            tool = tools.get(resto.strip())
            if tool is None:
                print(f"{c.error}Unknown tool. Try 'list'.{c.reset}")
                continue
            print(json.dumps(tool["inputSchema"], indent=2, ensure_ascii=False))
            continue
        if comando == "ping":
            cliente.enviar_request("ping")
            continue
        if comando == "call":
            trozos = resto.split(None, 1)
            if not trozos:
                print(f"{c.error}Usage: call <tool> <json-args>{c.reset}")
                continue
            nombre = trozos[0]
            crudo = trozos[1].strip() if len(trozos) > 1 else "{}"
            try:
                argumentos = json.loads(crudo) if crudo else {}
            except json.JSONDecodeError as exc:
                print(f"{c.error}Arguments must be valid JSON: {exc}{c.reset}")
                continue
            imprimir_resultado(cliente.llamar_tool(nombre, argumentos), c)
            continue
        if comando == "raw":
            trozos = shlex.split(resto)
            if not trozos:
                print(f"{c.error}Usage: raw <method> [json-params]{c.reset}")
                continue
            metodo = trozos[0]
            params = json.loads(trozos[1]) if len(trozos) > 1 else None
            cliente.enviar_request(metodo, params)
            continue

        print(f"{c.error}Unknown command '{comando}'. Type 'help'.{c.reset}")


# ---------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument(
        "--demo", action="store_true", help="run the scripted licensing flow (default)"
    )
    modo.add_argument(
        "--interactive", action="store_true", help="open a REPL against the server"
    )
    parser.add_argument(
        "--catalog", type=Path, default=None, help="alternative catalog JSON file"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="hide the raw JSON-RPC trace and show only the answers",
    )
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = parser.parse_args()

    colores = Colores(activo=sys.stdout.isatty() and not args.no_color)
    cliente = ClienteMCP(colores, catalogo=args.catalog, verbose=not args.quiet)

    try:
        if args.interactive:
            return ejecutar_interactivo(cliente, colores)
        return ejecutar_demo(cliente, colores)
    except RuntimeError as exc:
        print(f"{colores.error}{exc}{colores.reset}", file=sys.stderr)
        return 1
    finally:
        cliente.cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
