"""Rate card for synchronisation licences.

The price of a sync licence is not a fixed number attached to a track: the same
track costs one thing for an Instagram post and another for a national TV
campaign. This module encodes those conditional rules.

    subtotal = tarifa_base
             x multiplicador de tipo de uso
             x multiplicador de territorio
             x multiplicador de exclusividad
             x multiplicador de vigencia

    total    = subtotal + escrow

The multipliers are modelled on the public royalty-free rate cards of platforms
such as Jamendo Licensing (https://licensing.jamendo.com). They are part of the
simulated business layer: no platform publishes its actual internal pricing.
"""

from __future__ import annotations

from .catalog import ESTADOS_DERECHOS
from .errors import ErrorDeNegocio

# How wide the audience of the placement is, and how commercial it is.
MULT_TIPO_USO = {
    "redes_sociales": 1.0,
    "evento_interno": 1.1,
    "podcast": 1.3,
    "web_corporativo": 1.6,
    "publicidad_online": 2.5,
    "videojuego": 4.0,
    "tv_nacional": 6.0,
    "cine": 8.0,
}

# How much of the world the licence covers.
MULT_TERRITORIO = {
    "local": 1.0,
    "latam": 1.8,
    "europa": 2.2,
    "norteamerica": 2.4,
    "mundial": 3.2,
}

# Exclusivity takes the track off the market for everyone else, so it is the
# single most expensive dimension.
MULT_EXCLUSIVIDAD = {
    "no": 1.0,
    "sectorial": 2.0,
    "total": 4.5,
}

# Term multipliers, as (upper bound in months, multiplier). Six months is the
# reference term, which is why it sits at 1.0.
ESCALA_VIGENCIA = [
    (3, 0.8),
    (6, 1.0),
    (12, 1.5),
    (24, 2.2),
    (36, 2.8),
]
MULT_VIGENCIA_LARGA = 3.2  # over 36 months
MULT_VIGENCIA_PERPETUA = 3.5  # duracion_meses = 0

# A quote holds its price for 30 days.
VALIDEZ_COTIZACION_DIAS = 30


def multiplicador_vigencia(duracion_meses: int) -> float:
    """Return the term multiplier. ``0`` means a perpetual licence."""
    if duracion_meses == 0:
        return MULT_VIGENCIA_PERPETUA
    for tope, multiplicador in ESCALA_VIGENCIA:
        if duracion_meses <= tope:
            return multiplicador
    return MULT_VIGENCIA_LARGA


def calcular(
    pista: dict,
    tipo_uso: str,
    territorio: str,
    exclusividad: str,
    duracion_meses: int,
) -> dict:
    """Price one track for a specific licensing scenario.

    Returns the full breakdown, so the quote can be explained line by line
    instead of handing the client an opaque number.

    Raises:
        ErrorDeNegocio: if the track cannot be licensed at all.
    """
    estado = pista["estado_derechos"]
    propiedades = ESTADOS_DERECHOS[estado]
    if not propiedades["licenciable"]:
        raise ErrorDeNegocio(
            "pista_bloqueada",
            f"Track {pista['pista_id']} \"{pista['titulo']}\" cannot be quoted: "
            f"{pista['detalle_derechos']}",
            {"pista_id": pista["pista_id"], "estado": estado},
        )

    base = float(pista["tarifa_base_usd"])
    mult_uso = MULT_TIPO_USO[tipo_uso]
    mult_territorio = MULT_TERRITORIO[territorio]
    mult_exclusividad = MULT_EXCLUSIVIDAD[exclusividad]
    mult_vigencia = multiplicador_vigencia(duracion_meses)

    subtotal = base * mult_uso * mult_territorio * mult_exclusividad * mult_vigencia
    recargo_pct = propiedades["recargo_escrow_pct"]
    escrow = subtotal * recargo_pct / 100
    total = subtotal + escrow

    return {
        "tarifa_base_usd": round(base, 2),
        "multiplicadores": {
            "tipo_uso": mult_uso,
            "territorio": mult_territorio,
            "exclusividad": mult_exclusividad,
            "vigencia": mult_vigencia,
        },
        "subtotal_usd": round(subtotal, 2),
        "recargo_escrow_pct": recargo_pct,
        "recargo_escrow_usd": round(escrow, 2),
        "total_usd": round(total, 2),
        "moneda": "USD",
    }


def explicar(desglose: dict, pista: dict, alcance: dict) -> str:
    """Render the breakdown as the line-by-line explanation a client expects."""
    m = desglose["multiplicadores"]
    vigencia = (
        "perpetual"
        if alcance["duracion_meses"] == 0
        else f"{alcance['duracion_meses']} month(s)"
    )
    lineas = [
        f"Quote for {pista['pista_id']} \"{pista['titulo']}\" by {pista['artista']}",
        f"  base fee                 USD {desglose['tarifa_base_usd']:>10.2f}",
        f"  x use ({alcance['tipo_uso']})".ljust(27) + f"{m['tipo_uso']:>14.2f}",
        f"  x territory ({alcance['territorio']})".ljust(27) + f"{m['territorio']:>14.2f}",
        f"  x exclusivity ({alcance['exclusividad']})".ljust(27)
        + f"{m['exclusividad']:>14.2f}",
        f"  x term ({vigencia})".ljust(27) + f"{m['vigencia']:>14.2f}",
        f"  subtotal                 USD {desglose['subtotal_usd']:>10.2f}",
    ]
    if desglose["recargo_escrow_usd"]:
        lineas.append(
            f"  + escrow ({desglose['recargo_escrow_pct']:.0f}%)".ljust(27)
            + f"USD {desglose['recargo_escrow_usd']:>10.2f}"
        )
    lineas.append(f"  TOTAL                    USD {desglose['total_usd']:>10.2f}")
    return "\n".join(lineas)
