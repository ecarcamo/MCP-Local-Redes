"""Business-rule failures.

These are distinct from JSON-RPC errors. A blocked track, an expired quote or
an unknown contract are *valid* protocol calls whose answer happens to be "no".
The MCP specification asks for those to come back as a successful response with
``isError: true``, so the model can read the explanation and correct course,
instead of a transport-level error that would look like the server broke.
"""

from __future__ import annotations

from typing import Any


class ErrorDeNegocio(Exception):
    """A tool ran correctly but the licensing rules refuse the operation."""

    def __init__(self, motivo: str, mensaje: str, datos: Any = None) -> None:
        super().__init__(mensaje)
        self.motivo = motivo
        self.mensaje = mensaje
        self.datos = datos or {}
