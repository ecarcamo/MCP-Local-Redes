"""Tool registry, argument validation and dispatch.

Every tool is declared with a JSON Schema, exactly as ``tools/list`` must
publish it. The schema is not decorative: :func:`validar_argumentos` is the
only entry point into a handler, so the same declaration that documents a tool
is the one that enforces its contract.

The validator covers the subset of JSON Schema these tools use (``type``,
``enum``, ``required``, ``minimum``, ``maximum``, ``default``). It is written by
hand for the same reason the protocol is: no external schema library.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .jsonrpc import INVALID_PARAMS, JsonRpcError

@dataclass(frozen=True)
class ResultadoTool:
    """What a handler returns.

    ``texto`` is the human-readable summary that goes into ``content`` for the
    model to read; ``datos`` is the machine-readable payload that goes into
    ``structuredContent`` for the client to chain into the next call.
    """

    texto: str
    datos: dict


# A handler receives the validated arguments and the live session.
Handler = Callable[[dict, Any], ResultadoTool]


@dataclass(frozen=True)
class Tool:
    """One MCP tool: its published descriptor plus the function behind it."""

    name: str
    title: str
    description: str
    input_schema: dict
    handler: Handler

    def descriptor(self) -> dict:
        """The object published by ``tools/list``."""
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


REGISTRO: dict[str, Tool] = {}


def registrar(tool: Tool) -> Tool:
    """Add a tool to the registry, keeping declaration order for tools/list."""
    REGISTRO[tool.name] = tool
    return tool


def listar_descriptores() -> list[dict]:
    return [tool.descriptor() for tool in REGISTRO.values()]


_TIPOS_PYTHON = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def validar_argumentos(schema: dict, argumentos: dict) -> dict:
    """Validate ``argumentos`` against ``schema`` and apply defaults.

    Raises:
        JsonRpcError: with ``INVALID_PARAMS`` describing the first problem
            found, so a model reading the error can correct the call.
    """
    if not isinstance(argumentos, dict):
        raise JsonRpcError(INVALID_PARAMS, "'arguments' must be an object")

    propiedades = schema.get("properties", {})
    requeridos = schema.get("required", [])

    desconocidos = set(argumentos) - set(propiedades)
    if desconocidos:
        raise JsonRpcError(
            INVALID_PARAMS,
            f"Unknown argument(s): {', '.join(sorted(desconocidos))}",
            {"esperados": sorted(propiedades)},
        )

    for nombre in requeridos:
        if argumentos.get(nombre) is None:
            raise JsonRpcError(INVALID_PARAMS, f"Missing required argument '{nombre}'")

    validados: dict[str, Any] = {}
    for nombre, definicion in propiedades.items():
        if nombre not in argumentos or argumentos[nombre] is None:
            if "default" in definicion:
                validados[nombre] = definicion["default"]
            else:
                validados[nombre] = None
            continue

        valor = argumentos[nombre]
        tipo = definicion.get("type")
        esperado = _TIPOS_PYTHON.get(tipo)

        # bool is a subclass of int in Python, so it must be rejected explicitly
        # for numeric fields to avoid accepting true as 1.
        if tipo in ("integer", "number") and isinstance(valor, bool):
            raise JsonRpcError(
                INVALID_PARAMS, f"Argument '{nombre}' must be of type {tipo}"
            )
        if esperado is not None and not isinstance(valor, esperado):
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Argument '{nombre}' must be of type {tipo}, got {type(valor).__name__}",
            )

        if "enum" in definicion and valor not in definicion["enum"]:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Argument '{nombre}' must be one of: {', '.join(map(str, definicion['enum']))}",
                {"recibido": valor},
            )

        if "minimum" in definicion and valor < definicion["minimum"]:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Argument '{nombre}' must be >= {definicion['minimum']}",
            )
        if "maximum" in definicion and valor > definicion["maximum"]:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Argument '{nombre}' must be <= {definicion['maximum']}",
            )

        validados[nombre] = valor

    return validados


def ejecutar(nombre: str, argumentos: dict, sesion: Any) -> ResultadoTool:
    """Run one tool by name after validating its arguments.

    Raises:
        JsonRpcError: with ``INVALID_PARAMS`` when the tool does not exist or
            the arguments do not satisfy its schema.
    """
    tool = REGISTRO.get(nombre)
    if tool is None:
        raise JsonRpcError(
            INVALID_PARAMS,
            f"Unknown tool '{nombre}'",
            {"disponibles": sorted(REGISTRO)},
        )
    validados = validar_argumentos(tool.input_schema, argumentos)
    return tool.handler(validados, sesion)
