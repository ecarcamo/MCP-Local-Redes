"""Contract issuing and usage registration.

This is the last leg of the licensing flow. A contract can only be built on top
of a quote that is still valid and belongs to the same track, and a usage record
can only be filed against an active contract. Those checks are what turn five
tools into an actual workflow.

Quotes and contracts live in the session (see :class:`synclicense_mcp.server.Sesion`).
Usage records are appended to ``data/usage_log.jsonl`` because royalty reporting
has to survive the process that produced it.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .catalog import REPO_ROOT
from .errors import ErrorDeNegocio

REGISTRO_USOS = REPO_ROOT / "data" / "usage_log.jsonl"

# A calendar month is approximated as 30 days, which is how licence terms are
# normally counted on a rate card.
DIAS_POR_MES = 30

RESTRICCIONES_BASE = [
    "The licence covers only the project declared by the licensee; any other "
    "placement requires a new licence.",
    "The licensee may not sublicense, resell or register the track with a "
    "content-identification system.",
    "The original author must be credited as required by the underlying "
    "Creative Commons licence.",
]


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def validar_cotizacion(cotizaciones: dict, cotizacion_id: str, pista_id: str) -> dict:
    """Check that a quote exists, is still valid and matches the track.

    Raises:
        ErrorDeNegocio: with motive ``cotizacion_inexistente``,
            ``cotizacion_expirada`` or ``cotizacion_no_corresponde``.
    """
    cotizacion = cotizaciones.get(cotizacion_id)
    if cotizacion is None:
        raise ErrorDeNegocio(
            "cotizacion_inexistente",
            f"Quote '{cotizacion_id}' does not exist in this session. Run "
            "calcular_costo_licencia first and use the cotizacion_id it returns.",
            {"cotizacion_id": cotizacion_id},
        )

    if cotizacion["pista_id"] != pista_id:
        raise ErrorDeNegocio(
            "cotizacion_no_corresponde",
            f"Quote '{cotizacion_id}' was issued for track "
            f"{cotizacion['pista_id']}, not {pista_id}.",
            {
                "cotizacion_id": cotizacion_id,
                "pista_id_cotizacion": cotizacion["pista_id"],
                "pista_id_solicitada": pista_id,
            },
        )

    valida_hasta = datetime.fromisoformat(cotizacion["valida_hasta"])
    if _ahora() > valida_hasta:
        raise ErrorDeNegocio(
            "cotizacion_expirada",
            f"Quote '{cotizacion_id}' expired on {cotizacion['valida_hasta']}. "
            "Request a new quote before issuing the contract.",
            {"cotizacion_id": cotizacion_id, "valida_hasta": cotizacion["valida_hasta"]},
        )

    return cotizacion


def restricciones_para(pista: dict, alcance: dict) -> list[str]:
    """Assemble the restriction clauses that apply to this specific licence."""
    clausulas = list(pista.get("restricciones", []))
    clausulas.extend(RESTRICCIONES_BASE)

    if alcance["exclusividad"] == "no":
        clausulas.append(
            "Non-exclusive licence: the same track may be licensed to other clients."
        )
    elif alcance["exclusividad"] == "sectorial":
        clausulas.append(
            "Sector exclusivity: the track will not be licensed to another client "
            "in the licensee's industry for the duration of the term."
        )
    else:
        clausulas.append(
            "Full exclusivity: the track is withdrawn from the catalog for the "
            "duration of the term."
        )

    if alcance["territorio"] != "mundial":
        clausulas.append(
            f"Distribution is limited to the '{alcance['territorio']}' territory."
        )

    return clausulas


def crear_contrato(cotizacion: dict, pista: dict, cliente: str) -> dict:
    """Turn a validated quote into a licence agreement."""
    alcance = cotizacion["alcance"]
    inicio = _ahora()
    meses = alcance["duracion_meses"]
    if meses == 0:
        fin = None
        vigencia_texto = "perpetual"
    else:
        fin = inicio + timedelta(days=meses * DIAS_POR_MES)
        vigencia_texto = f"{meses} month(s)"

    return {
        "contrato_id": f"CTR-{uuid.uuid4().hex[:10].upper()}",
        "cotizacion_id": cotizacion["cotizacion_id"],
        "cliente": cliente,
        "pista": {
            "pista_id": pista["pista_id"],
            "titulo": pista["titulo"],
            "artista": pista["artista"],
            "licencia_origen": pista["licencia"],
        },
        "alcance": alcance,
        "vigencia": {
            "inicio": inicio.isoformat(timespec="seconds"),
            "fin": fin.isoformat(timespec="seconds") if fin else None,
            "descripcion": vigencia_texto,
        },
        "monto_usd": cotizacion["desglose"]["total_usd"],
        "moneda": "USD",
        "restricciones": restricciones_para(pista, alcance),
        "estado": "activo",
        "emitido_en": inicio.isoformat(timespec="seconds"),
    }


def validar_contrato(contratos: dict, contrato_id: str) -> dict:
    """Check that a contract exists in this session and is still active."""
    contrato = contratos.get(contrato_id)
    if contrato is None:
        raise ErrorDeNegocio(
            "contrato_inexistente",
            f"Contract '{contrato_id}' does not exist in this session. Issue it "
            "with generar_contrato first.",
            {"contrato_id": contrato_id},
        )
    if contrato["estado"] != "activo":
        raise ErrorDeNegocio(
            "contrato_inactivo",
            f"Contract '{contrato_id}' is not active (status: {contrato['estado']}).",
            {"contrato_id": contrato_id, "estado": contrato["estado"]},
        )
    return contrato


def registrar_uso(contrato: dict, plataforma: str, url_proyecto: str) -> dict:
    """File a usage record against a contract and append it to the audit log."""
    registro = {
        "registro_id": f"USO-{uuid.uuid4().hex[:10].upper()}",
        "contrato_id": contrato["contrato_id"],
        "pista_id": contrato["pista"]["pista_id"],
        "titulo": contrato["pista"]["titulo"],
        "cliente": contrato["cliente"],
        "plataforma": plataforma,
        "url_proyecto": url_proyecto,
        "monto_usd": contrato["monto_usd"],
        "registrado_en": _ahora().isoformat(timespec="seconds"),
        "estado": "registrado",
    }
    _anexar_registro(registro)
    return registro


def _anexar_registro(registro: dict, ruta: Path | None = None) -> None:
    """Append one record as a JSON line, so the log can grow across sessions."""
    ruta = ruta or REGISTRO_USOS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as archivo:
        archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
