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
    python scripts/seed_catalog.py --jamendo --count 800   # needs JAMENDO_CLIENT_ID
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "catalog.json"

# Seed defaults to the author's student ID so the catalog is reproducible.
DEFAULT_SEED = 23016

# Public Jamendo API. Docs: https://developer.jamendo.com/v3.0
JAMENDO_API = "https://api.jamendo.com/v3.0/tracks/"
JAMENDO_PAGE_SIZE = 200  # maximum the endpoint accepts per request

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


def cargar_client_id() -> str:
    """Read JAMENDO_CLIENT_ID from the environment or from a local .env file.

    A full dotenv library would be overkill here: the file only ever holds
    KEY=VALUE lines.
    """
    client_id = os.environ.get("JAMENDO_CLIENT_ID", "").strip()
    if client_id:
        return client_id

    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for linea in env_file.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            if clave.strip() != "JAMENDO_CLIENT_ID":
                continue
            valor = valor.strip().strip('"').strip("'")
            # An empty value means the file was copied from .env.example but
            # never filled in, so fall through to the instructions below rather
            # than sending an unauthenticated request to the API.
            if valor:
                return valor

    raise SystemExit(
        "JAMENDO_CLIENT_ID is not set. Copy .env.example to .env and add your "
        "client_id from https://devportal.jamendo.com, or run with --offline."
    )


def mapear_tags(musicinfo: dict, rng: random.Random) -> tuple[str, str, bool]:
    """Map Jamendo's tag structure onto our genre / mood / instrumental fields.

    Jamendo returns free-form tags, so anything we do not recognise falls back
    to a seeded random choice to keep every track fully described.
    """
    tags = musicinfo.get("tags", {}) or {}
    generos_tag = [t.lower() for t in tags.get("genres", []) or []]
    vartags = [t.lower() for t in tags.get("vartags", []) or []]

    genero = next((g for g in generos_tag if g in GENEROS), None)
    if genero is None:
        # Common Jamendo genre names that do not match our vocabulary directly.
        alias = {
            "electronic": "electronica",
            "hiphop": "hip_hop",
            "classical": "clasica",
            "lounge": "ambient",
            "soundtrack": "cinematica",
            "latin": "latina",
        }
        genero = next(
            (alias[g] for g in generos_tag if g in alias), rng.choice(GENEROS)
        )

    mood_alias = {
        "happy": "alegre",
        "epic": "epico",
        "sad": "melancolico",
        "melancholic": "melancolico",
        "relaxed": "relajado",
        "calm": "relajado",
        "dark": "oscuro",
        "energetic": "energetico",
        "inspiring": "inspirador",
        "tense": "tenso",
    }
    mood = next(
        (mood_alias[v] for v in vartags if v in mood_alias), rng.choice(MOODS)
    )

    instrumental = "instrumental" in vartags or musicinfo.get("vocalinstrumental") == "instrumental"

    return genero, mood, instrumental


def descargar_jamendo(count: int, client_id: str, seed: int) -> list[dict]:
    """Page through the Jamendo API and build catalog entries from the results.

    Only the *metadata* comes from Jamendo. The base fee and the rights status
    are still generated locally from the seed, because that information is not
    public for any platform.
    """
    try:
        import requests  # imported here so --offline never needs the dependency
    except ImportError:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "The --jamendo mode needs the 'requests' package: pip install -r requirements.txt"
        )

    rng = random.Random(seed)
    pistas: list[dict] = []
    offset = 0

    while len(pistas) < count:
        faltantes = count - len(pistas)
        parametros = {
            "client_id": client_id,
            "format": "json",
            "limit": min(JAMENDO_PAGE_SIZE, faltantes),
            "offset": offset,
            "include": "musicinfo+licenses",
            "audioformat": "mp32",
            "order": "popularity_total",
        }
        print(f"  fetching offset={offset} ...", file=sys.stderr)
        respuesta = requests.get(JAMENDO_API, params=parametros, timeout=30)
        respuesta.raise_for_status()
        cuerpo = respuesta.json()

        cabecera = cuerpo.get("headers", {})
        if cabecera.get("status") != "success":
            raise SystemExit(f"Jamendo API error: {cabecera.get('error_message')}")

        resultados = cuerpo.get("results", [])
        if not resultados:
            print(
                f"  Jamendo returned no more results; stopping at {len(pistas)} tracks.",
                file=sys.stderr,
            )
            break

        for item in resultados:
            duracion = int(item.get("duration") or 0)
            if duracion <= 0:
                continue
            genero, mood, instrumental = mapear_tags(item.get("musicinfo", {}) or {}, rng)
            popularidad = rng.randint(5, 99)
            pistas.append(
                completar_pista(
                    {
                        "titulo": item.get("name") or "Untitled",
                        "artista": item.get("artist_name") or "Unknown artist",
                        "duracion_seg": duracion,
                        "genero": genero,
                        "mood": mood,
                        "instrumental": instrumental,
                        "popularidad": popularidad,
                        "licencia": item.get("license_ccurl") or "Creative Commons",
                        "tarifa_base_usd": tarifa_base(duracion, popularidad),
                        "estado_derechos": elegir_estado(rng),
                    },
                    len(pistas) + 1,
                )
            )

        offset += len(resultados)

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
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument(
        "--offline",
        action="store_true",
        help="generate the catalog locally, without network access (default)",
    )
    modo.add_argument(
        "--jamendo",
        action="store_true",
        help="pull real track metadata from the Jamendo API (needs JAMENDO_CLIENT_ID)",
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

    if args.jamendo:
        fuente = "jamendo"
        pistas = descargar_jamendo(args.count, cargar_client_id(), args.seed)
    else:
        fuente = "offline"
        pistas = generar_offline(args.count, args.seed)

    escribir_catalogo(pistas, fuente, args.seed, args.output)

    print(f"Wrote {len(pistas)} tracks to {args.output}")
    print(f"Rights status distribution: {resumen(pistas)}")


if __name__ == "__main__":
    main()
