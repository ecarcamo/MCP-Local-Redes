"""JSON-RPC 2.0 framing over a stdio transport.

Implemented by hand against the JSON-RPC 2.0 specification
(https://www.jsonrpc.org/specification), which is the wire format MCP uses.

Framing rules for the MCP stdio transport:

* one JSON message per line, terminated by ``\\n``;
* UTF-8 encoded, and a message must never contain an embedded newline;
* ``stdout`` carries protocol traffic only, so every diagnostic goes to
  ``stderr``.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

# Standard JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# MCP-specific code, used when a request arrives before the handshake finished.
SERVER_NOT_INITIALIZED = -32002


class JsonRpcError(Exception):
    """An error that must be reported back as a JSON-RPC ``error`` object.

    This is for *protocol-level* failures (bad envelope, unknown method,
    invalid arguments). A tool that runs correctly but is refused by the
    business rules returns a successful response carrying ``isError: true``
    instead, which is what lets a model read and recover from the failure.
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_object(self) -> dict:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


def log(message: str) -> None:
    """Write a diagnostic line to stderr, never to stdout."""
    print(f"[synclicense-mcp] {message}", file=sys.stderr, flush=True)


def read_message(stream: TextIO) -> dict | None:
    """Read one newline-delimited JSON-RPC message.

    Returns ``None`` at end of input. Blank lines are skipped, because a host
    may pad the stream while it is starting up.

    Raises:
        JsonRpcError: with ``PARSE_ERROR`` when the line is not valid JSON.
    """
    while True:
        linea = stream.readline()
        if linea == "":  # EOF
            return None
        linea = linea.strip()
        if not linea:
            continue
        try:
            mensaje = json.loads(linea)
        except json.JSONDecodeError as exc:
            raise JsonRpcError(PARSE_ERROR, "Parse error", str(exc)) from exc
        if not isinstance(mensaje, dict):
            # Batches are valid JSON-RPC but MCP does not use them, and this
            # server does not accept them.
            raise JsonRpcError(INVALID_REQUEST, "Expected a single JSON object")
        return mensaje


def write_message(stream: TextIO, mensaje: dict) -> None:
    """Serialise one message onto a single line and flush it immediately."""
    # separators without spaces and no indentation guarantee a single line.
    linea = json.dumps(mensaje, ensure_ascii=False, separators=(",", ":"))
    stream.write(linea + "\n")
    stream.flush()


def parse_request(mensaje: dict) -> tuple[str, dict, Any, bool]:
    """Validate the JSON-RPC envelope and pull out its parts.

    Returns:
        ``(method, params, request_id, is_notification)``. A notification is a
        message with no ``id``: per the specification it must not be answered.

    Raises:
        JsonRpcError: with ``INVALID_REQUEST`` when the envelope is malformed.
    """
    if mensaje.get("jsonrpc") != "2.0":
        raise JsonRpcError(INVALID_REQUEST, "Missing or invalid 'jsonrpc' version field")

    metodo = mensaje.get("method")
    if not isinstance(metodo, str) or not metodo:
        raise JsonRpcError(INVALID_REQUEST, "Missing or invalid 'method' field")

    params = mensaje.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        # Positional params are legal JSON-RPC but MCP always uses named ones.
        raise JsonRpcError(INVALID_PARAMS, "'params' must be an object")

    request_id = mensaje.get("id")
    es_notificacion = "id" not in mensaje

    return metodo, params, request_id, es_notificacion


def make_response(request_id: Any, result: Any) -> dict:
    """Build a successful JSON-RPC response."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, error: JsonRpcError) -> dict:
    """Build a JSON-RPC error response.

    ``id`` is ``null`` when the request could not be parsed far enough to know
    which call it belonged to, as the specification requires.
    """
    return {"jsonrpc": "2.0", "id": request_id, "error": error.to_object()}
