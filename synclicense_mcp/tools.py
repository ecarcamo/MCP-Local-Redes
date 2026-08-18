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

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import pricing
from .catalog import ESTADOS_DERECHOS
from .errors import ErrorDeNegocio
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


# ---------------------------------------------------------------------------
# Tool 1: buscar_pista
# ---------------------------------------------------------------------------

MOODS = [
    "alegre",
    "epico",
    "melancolico",
    "relajado",
    "tenso",
    "energetico",
    "inspirador",
    "oscuro",
]

GENEROS = [
    "pop",
    "rock",
    "electronica",
    "hip_hop",
    "jazz",
    "clasica",
    "folk",
    "ambient",
    "cinematica",
    "latina",
]


def _buscar_pista(args: dict, sesion: Any) -> ResultadoTool:
    encontradas = sesion.catalogo.buscar(
        mood=args["mood"],
        genero=args["genero"],
        instrumental=args["instrumental"],
        duracion_seg_min=args["duracion_seg_min"],
        duracion_seg_max=args["duracion_seg_max"],
        presupuesto_max=args["presupuesto_max"],
    )
    limite = args["limite"]
    seleccion = encontradas[:limite]

    pistas = [
        {
            "pista_id": p["pista_id"],
            "titulo": p["titulo"],
            "artista": p["artista"],
            "duracion_seg": p["duracion_seg"],
            "genero": p["genero"],
            "mood": p["mood"],
            "instrumental": p["instrumental"],
            "popularidad": p["popularidad"],
            "tarifa_base_usd": p["tarifa_base_usd"],
            "estado_derechos": p["estado_derechos"],
        }
        for p in seleccion
    ]

    if not pistas:
        texto = (
            "No tracks matched those criteria. Try widening the budget, the "
            "duration range, or dropping the mood/genre filter."
        )
    else:
        lineas = [
            f"{len(encontradas)} track(s) matched; showing the top {len(pistas)}:"
        ]
        for p in pistas:
            lineas.append(
                f"  {p['pista_id']} · \"{p['titulo']}\" by {p['artista']} · "
                f"{p['duracion_seg']}s · {p['genero']}/{p['mood']} · "
                f"base USD {p['tarifa_base_usd']:.2f} · rights: {p['estado_derechos']}"
            )
        texto = "\n".join(lineas)

    return ResultadoTool(
        texto=texto,
        datos={"total_encontradas": len(encontradas), "pistas": pistas},
    )


registrar(
    Tool(
        name="buscar_pista",
        title="Search tracks",
        description=(
            "Search the licensing catalog by creative brief and budget. "
            "Every filter is optional; combine them to narrow the shortlist. "
            "Tracks blocked by an authorship dispute are excluded because they "
            "cannot be licensed. Returns the most popular matches first."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": MOODS,
                    "description": "Emotional character of the track.",
                },
                "genero": {
                    "type": "string",
                    "enum": GENEROS,
                    "description": "Musical genre.",
                },
                "instrumental": {
                    "type": "boolean",
                    "description": "true to return only tracks without vocals.",
                },
                "duracion_seg_min": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Minimum duration in seconds.",
                },
                "duracion_seg_max": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Maximum duration in seconds.",
                },
                "presupuesto_max": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Maximum base fee in USD before multipliers.",
                },
                "limite": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "How many candidates to return.",
                },
            },
            "required": [],
        },
        handler=_buscar_pista,
    )
)


# ---------------------------------------------------------------------------
# Tool 2: verificar_clearance
# ---------------------------------------------------------------------------


def _verificar_clearance(args: dict, sesion: Any) -> ResultadoTool:
    pista_id = args["pista_id"]
    pista = sesion.catalogo.obtener(pista_id)
    if pista is None:
        raise ErrorDeNegocio(
            "pista_inexistente",
            f"There is no track with id '{pista_id}' in the catalog.",
            {"pista_id": pista_id},
        )

    estado = pista["estado_derechos"]
    propiedades = ESTADOS_DERECHOS[estado]

    datos = {
        "pista_id": pista_id,
        "titulo": pista["titulo"],
        "artista": pista["artista"],
        "estado": estado,
        "licenciable": propiedades["licenciable"],
        "detalle": pista["detalle_derechos"],
        "restricciones": pista["restricciones"],
        "recargo_escrow_pct": propiedades["recargo_escrow_pct"],
        "licencia_origen": pista["licencia"],
    }

    veredicto = "CLEARED" if propiedades["licenciable"] else "NOT LICENSABLE"
    lineas = [
        f"{pista_id} \"{pista['titulo']}\" — {veredicto} (status: {estado})",
        pista["detalle_derechos"],
    ]
    if propiedades["recargo_escrow_pct"]:
        lineas.append(
            f"An escrow surcharge of {propiedades['recargo_escrow_pct']:.0f}% "
            "will be added to any quote for this track."
        )
    for restriccion in pista["restricciones"]:
        lineas.append(f"  - {restriccion}")

    return ResultadoTool(texto="\n".join(lineas), datos=datos)


registrar(
    Tool(
        name="verificar_clearance",
        title="Check rights clearance",
        description=(
            "Check the legal status of one track before quoting or licensing "
            "it. Returns 'libre' (cleared), 'samples_pendientes' (licensable "
            "but with a 15% escrow surcharge and a hold-back clause) or "
            "'bloqueada' (frozen by an authorship dispute, not licensable). "
            "Always run this before generating a contract."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "pista_id": {
                    "type": "string",
                    "description": "Track id as returned by buscar_pista, e.g. TRK-00001.",
                }
            },
            "required": ["pista_id"],
        },
        handler=_verificar_clearance,
    )
)


# ---------------------------------------------------------------------------
# Tool 3: calcular_costo_licencia
# ---------------------------------------------------------------------------


def _buscar_pista_o_fallar(sesion: Any, pista_id: str) -> dict:
    """Fetch a track or raise the business error every tool shares."""
    pista = sesion.catalogo.obtener(pista_id)
    if pista is None:
        raise ErrorDeNegocio(
            "pista_inexistente",
            f"There is no track with id '{pista_id}' in the catalog.",
            {"pista_id": pista_id},
        )
    return pista


def _calcular_costo_licencia(args: dict, sesion: Any) -> ResultadoTool:
    pista = _buscar_pista_o_fallar(sesion, args["pista_id"])

    alcance = {
        "tipo_uso": args["tipo_uso"],
        "territorio": args["territorio"],
        "exclusividad": args["exclusividad"],
        "duracion_meses": args["duracion_meses"],
    }
    # Raises ErrorDeNegocio when the track is blocked.
    desglose = pricing.calcular(
        pista,
        alcance["tipo_uso"],
        alcance["territorio"],
        alcance["exclusividad"],
        alcance["duracion_meses"],
    )

    emitida = datetime.now(timezone.utc)
    valida_hasta = emitida + timedelta(days=pricing.VALIDEZ_COTIZACION_DIAS)
    cotizacion_id = f"COT-{uuid.uuid4().hex[:10].upper()}"

    cotizacion = {
        "cotizacion_id": cotizacion_id,
        "pista_id": pista["pista_id"],
        "titulo": pista["titulo"],
        "artista": pista["artista"],
        "alcance": alcance,
        "desglose": desglose,
        "estado_derechos": pista["estado_derechos"],
        "emitida_en": emitida.isoformat(timespec="seconds"),
        "valida_hasta": valida_hasta.isoformat(timespec="seconds"),
    }
    # Held in the session so generar_contrato can validate it later. This is
    # what makes the tools a chain instead of five independent lookups.
    sesion.cotizaciones[cotizacion_id] = cotizacion

    texto = (
        pricing.explicar(desglose, pista, alcance)
        + f"\n  quote id: {cotizacion_id} (valid until {cotizacion['valida_hasta']})"
    )
    if desglose["recargo_escrow_usd"]:
        texto += (
            "\n  Note: this track has samples pending clearance; part of the fee "
            "is held in escrow."
        )

    return ResultadoTool(texto=texto, datos=cotizacion)


registrar(
    Tool(
        name="calcular_costo_licencia",
        title="Quote a licence",
        description=(
            "Price a track for a specific licensing scenario. The fee is not "
            "fixed: it is the base fee multiplied by the type of use, the "
            "territory, the exclusivity and the term, plus an escrow surcharge "
            "when the track has samples pending clearance. Returns a full "
            "breakdown and a cotizacion_id that generar_contrato requires."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "pista_id": {
                    "type": "string",
                    "description": "Track id, e.g. TRK-00001.",
                },
                "tipo_uso": {
                    "type": "string",
                    "enum": sorted(pricing.MULT_TIPO_USO),
                    "description": "Where the track will be placed.",
                },
                "territorio": {
                    "type": "string",
                    "enum": sorted(pricing.MULT_TERRITORIO),
                    "description": "Territory the licence must cover.",
                },
                "exclusividad": {
                    "type": "string",
                    "enum": sorted(pricing.MULT_EXCLUSIVIDAD),
                    "description": (
                        "'no' = non-exclusive, 'sectorial' = exclusive within the "
                        "client's industry, 'total' = fully exclusive."
                    ),
                },
                "duracion_meses": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 120,
                    "description": "Licence term in months. Use 0 for a perpetual licence.",
                },
            },
            "required": [
                "pista_id",
                "tipo_uso",
                "territorio",
                "exclusividad",
                "duracion_meses",
            ],
        },
        handler=_calcular_costo_licencia,
    )
)
