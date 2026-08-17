"""Loading and querying the track catalog.

The catalog is the JSON document produced by ``scripts/seed_catalog.py``. It is
loaded once when the server starts and kept in memory: it is a few hundred
records, so an index by id is enough and there is no need for a database.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = REPO_ROOT / "data" / "catalog.json"


class CatalogoNoEncontrado(RuntimeError):
    """Raised when the catalog file is missing, so the server can explain how to build it."""


class Catalogo:
    """In-memory view of the track catalog."""

    def __init__(self, documento: dict) -> None:
        self.generado_en = documento.get("generado_en", "")
        self.fuente = documento.get("fuente", "desconocida")
        self.pistas: list[dict] = documento.get("pistas", [])
        self._por_id = {pista["pista_id"]: pista for pista in self.pistas}

    def __len__(self) -> int:
        return len(self.pistas)

    def obtener(self, pista_id: str) -> dict | None:
        """Return one track by id, or None if it does not exist."""
        return self._por_id.get(pista_id)

    def buscar(
        self,
        mood: str | None = None,
        genero: str | None = None,
        instrumental: bool | None = None,
        duracion_seg_min: int | None = None,
        duracion_seg_max: int | None = None,
        presupuesto_max: float | None = None,
        incluir_bloqueadas: bool = False,
    ) -> list[dict]:
        """Filter the catalog by creative and budget criteria.

        Blocked tracks are left out by default: they cannot be licensed, so
        offering them to a client would be a false positive. Results are sorted
        by descending popularity, which is what a commercial assistant would
        present first.
        """
        resultados = []
        for pista in self.pistas:
            if not incluir_bloqueadas and pista["estado_derechos"] == "bloqueada":
                continue
            if mood is not None and pista["mood"] != mood:
                continue
            if genero is not None and pista["genero"] != genero:
                continue
            if instrumental is not None and pista["instrumental"] != instrumental:
                continue
            if duracion_seg_min is not None and pista["duracion_seg"] < duracion_seg_min:
                continue
            if duracion_seg_max is not None and pista["duracion_seg"] > duracion_seg_max:
                continue
            if presupuesto_max is not None and pista["tarifa_base_usd"] > presupuesto_max:
                continue
            resultados.append(pista)

        resultados.sort(key=lambda p: p["popularidad"], reverse=True)
        return resultados


def cargar_catalogo(ruta: Path | None = None) -> Catalogo:
    """Read the catalog from disk.

    Raises:
        CatalogoNoEncontrado: when the file does not exist yet.
    """
    ruta = ruta or DEFAULT_CATALOG_PATH
    if not ruta.exists():
        raise CatalogoNoEncontrado(
            f"Catalog not found at {ruta}. Build it first with: "
            "python scripts/seed_catalog.py --offline --count 800"
        )
    documento = json.loads(ruta.read_text(encoding="utf-8"))
    return Catalogo(documento)
