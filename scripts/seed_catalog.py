#!/usr/bin/env python3
"""Build the track catalog used by the Sync Licensing MCP server.

The catalog has two layers:

* **Track metadata** (title, artist, duration, genre, mood, licence). In
  `--jamendo` mode this is pulled from the public Jamendo API, which exposes a
  Creative Commons catalog. In `--offline` mode it is generated locally so the
  project can be demoed without network access or credentials.

* **Business layer** (`tarifa_base_usd`, `estado_derechos`). No licensing
  platform publishes its rate card or the internal legal status of each track,
  so this layer is simulated. It is derived from a fixed seed, which makes the
  catalog reproducible: the same seed always yields the same prices and the same
  rights statuses.

Usage:
    python scripts/seed_catalog.py --offline --count 800
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "catalog.json"

# Seed defaults to the author's student ID so the catalog is reproducible.
DEFAULT_SEED = 23016

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

# Creative Commons licences actually used across the Jamendo catalog.
LICENCIAS = [
    "CC BY 3.0",
    "CC BY-SA 3.0",
    "CC BY-ND 3.0",
    "CC BY-NC 3.0",
]

# Rights status distribution. Most of a real catalog is cleared; a minority
# carries unresolved samples, and a few tracks are frozen by an authorship
# dispute and cannot be licensed at all.
DISTRIBUCION_DERECHOS = [
    ("libre", 0.82),
    ("samples_pendientes", 0.13),
    ("bloqueada", 0.05),
]

DETALLE_DERECHOS = {
    "libre": "Cleared for synchronisation. No third-party claims on record.",
    "samples_pendientes": (
        "Contains one or more samples whose clearance is still in progress. "
        "Licensable with a 15% escrow surcharge and a hold-back clause."
    ),
    "bloqueada": (
        "Frozen by an authorship dispute between credited writers. "
        "Cannot be licensed until the dispute is resolved."
    ),
}

RESTRICCIONES_POR_ESTADO = {
    "libre": [],
    "samples_pendientes": [
        "15% of the fee is held in escrow until sample clearance is confirmed.",
        "The licensee must notify the platform before any broadcast use.",
    ],
    "bloqueada": [
        "Track is not available for licensing.",
    ],
}

# Vocabulary for the offline title/artist generator.
TITULO_A = [
    "Sunburst", "Neon", "Glass", "Paper", "Iron", "Velvet", "Wild", "Slow",
    "Golden", "Silent", "Crimson", "Hollow", "Bright", "Distant", "Electric",
    "Frozen", "Midnight", "Coastal", "Restless", "Amber",
]
TITULO_B = [
    "Horizon", "Machine", "Cathedral", "Avenue", "Signal", "Harbor", "Static",
    "Motion", "Ashes", "Parade", "Mirage", "Circuit", "Garden", "Voltage",
    "Current", "Skyline", "Echoes", "Fever", "Lantern", "Drift",
]
ARTISTA_A = [
    "Nova", "Cassette", "Lunar", "Paper", "Halcyon", "Bitter", "Northern",
    "Solar", "Quiet", "Modern", "Velour", "Atlas", "Sable", "Vermillion",
]
ARTISTA_B = [
    "Bloom", "Kids", "Field", "Theory", "Society", "Union", "Collective",
    "Motel", "Signal", "Method", "Radio", "Assembly", "Division", "Club",
]

# Tracks pinned at the top of the catalog so the documented demo flow and the
# test suite always have a known-good, a pending-samples and a blocked track.
PISTAS_FIJAS = [
    {
        "titulo": "Sunburst",
        "artista": "Nova Bloom",
        "duracion_seg": 32,
        "genero": "electronica",
        "mood": "energetico",
        "instrumental": True,
        "popularidad": 71,
        "licencia": "CC BY-SA 3.0",
        "tarifa_base_usd": 45.0,
        "estado_derechos": "libre",
    },
    {
        "titulo": "Paper Cathedral",
        "artista": "Halcyon Theory",
        "duracion_seg": 154,
        "genero": "cinematica",
        "mood": "inspirador",
        "instrumental": True,
        "popularidad": 58,
        "licencia": "CC BY 3.0",
        "tarifa_base_usd": 62.5,
        "estado_derechos": "samples_pendientes",
    },
    {
        "titulo": "Crimson Parade",
        "artista": "Bitter Union",
        "duracion_seg": 208,
        "genero": "rock",
        "mood": "epico",
        "instrumental": False,
        "popularidad": 84,
        "licencia": "CC BY-NC 3.0",
        "tarifa_base_usd": 98.0,
        "estado_derechos": "bloqueada",
    },
]


def tarifa_base(duracion_seg: int, popularidad: int) -> float:
    """Derive the base fee from duration and popularity.

    Longer tracks offer more usable material and popular tracks carry more
    audience value, so both push the fee up. The result lands in roughly the
    18-130 USD band, comparable to published royalty-free rate cards.
    """
    por_duracion = min(duracion_seg, 300) / 300 * 40
    por_popularidad = popularidad / 100 * 70
    bruto = 18 + por_duracion + por_popularidad
    # Round to the nearest half dollar, the way a published rate card would.
    return round(bruto * 2) / 2


def elegir_estado(rng: random.Random) -> str:
    """Pick a rights status following DISTRIBUCION_DERECHOS."""
    ticket = rng.random()
    acumulado = 0.0
    for estado, peso in DISTRIBUCION_DERECHOS:
        acumulado += peso
        if ticket < acumulado:
            return estado
    return DISTRIBUCION_DERECHOS[-1][0]


def completar_pista(base: dict, indice: int) -> dict:
    """Fill in the derived fields shared by both seed modes."""
    estado = base["estado_derechos"]
    return {
        "pista_id": f"TRK-{indice:05d}",
        "titulo": base["titulo"],
        "artista": base["artista"],
        "duracion_seg": base["duracion_seg"],
        "genero": base["genero"],
        "mood": base["mood"],
        "instrumental": base["instrumental"],
        "popularidad": base["popularidad"],
        "licencia": base["licencia"],
        "tarifa_base_usd": base["tarifa_base_usd"],
        "estado_derechos": estado,
        "detalle_derechos": DETALLE_DERECHOS[estado],
        "restricciones": RESTRICCIONES_POR_ESTADO[estado],
    }


def generar_offline(count: int, seed: int) -> list[dict]:
    """Generate a synthetic catalog with no network access.

    Deterministic: the same seed always produces the same catalog, so the
    committed data file can be regenerated and reviewed.
    """
    rng = random.Random(seed)
    pistas = []

    for base in PISTAS_FIJAS:
        pistas.append(completar_pista(dict(base), len(pistas) + 1))

    vistos = {(p["titulo"], p["artista"]) for p in pistas}

    while len(pistas) < count:
        titulo = f"{rng.choice(TITULO_A)} {rng.choice(TITULO_B)}"
        artista = f"{rng.choice(ARTISTA_A)} {rng.choice(ARTISTA_B)}"
        if (titulo, artista) in vistos:
            continue
        vistos.add((titulo, artista))

        duracion = rng.randint(30, 300)
        popularidad = rng.randint(5, 99)
        pistas.append(
            completar_pista(
                {
                    "titulo": titulo,
                    "artista": artista,
                    "duracion_seg": duracion,
                    "genero": rng.choice(GENEROS),
                    "mood": rng.choice(MOODS),
                    "instrumental": rng.random() < 0.45,
                    "popularidad": popularidad,
                    "licencia": rng.choice(LICENCIAS),
                    "tarifa_base_usd": tarifa_base(duracion, popularidad),
                    "estado_derechos": elegir_estado(rng),
                },
                len(pistas) + 1,
            )
        )

    return pistas


def escribir_catalogo(pistas: list[dict], fuente: str, seed: int, salida: Path) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    documento = {
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": fuente,
        "seed": seed,
        "total": len(pistas),
        "pistas": pistas,
    }
    salida.write_text(
        json.dumps(documento, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resumen(pistas: list[dict]) -> str:
    conteo: dict[str, int] = {}
    for pista in pistas:
        conteo[pista["estado_derechos"]] = conteo.get(pista["estado_derechos"], 0) + 1
    partes = [f"{estado}={cantidad}" for estado, cantidad in sorted(conteo.items())]
    return ", ".join(partes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="generate the catalog locally, without network access (default)",
    )
    parser.add_argument(
        "--count", type=int, default=800, help="number of tracks to generate"
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="seed for the business layer"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="output JSON file"
    )
    args = parser.parse_args()

    pistas = generar_offline(args.count, args.seed)
    escribir_catalogo(pistas, "offline", args.seed, args.output)

    print(f"Wrote {len(pistas)} tracks to {args.output}")
    print(f"Rights status distribution: {resumen(pistas)}")


if __name__ == "__main__":
    main()
