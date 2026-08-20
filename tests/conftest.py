"""Shared test fixtures.

Puts the repository root on ``sys.path`` so the tests import the package the
same way a user does (``python -m synclicense_mcp``), with no install step.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synclicense_mcp.catalog import Catalogo, cargar_catalogo  # noqa: E402
from synclicense_mcp.server import Servidor  # noqa: E402


@pytest.fixture(scope="session")
def catalogo() -> Catalogo:
    """The real catalog, so the tests exercise the data the server ships with."""
    return cargar_catalogo()


def _primera_con_estado(catalogo: Catalogo, estado: str) -> dict:
    """First track in the catalog with a given rights status.

    The fixtures look tracks up by status instead of by a fixed id so the suite
    passes against any catalog: the offline seed, a Jamendo pull, or a catalog
    regenerated with a different seed.
    """
    for pista in catalogo.pistas:
        if pista["estado_derechos"] == estado:
            return pista
    pytest.skip(f"the catalog has no track with rights status '{estado}'")


@pytest.fixture
def pista_libre(catalogo: Catalogo) -> dict:
    """A track cleared for synchronisation."""
    return _primera_con_estado(catalogo, "libre")


@pytest.fixture
def pista_con_samples(catalogo: Catalogo) -> dict:
    """A track with samples still pending clearance."""
    return _primera_con_estado(catalogo, "samples_pendientes")


@pytest.fixture
def pista_bloqueada(catalogo: Catalogo) -> dict:
    """A track frozen by an authorship dispute."""
    return _primera_con_estado(catalogo, "bloqueada")


@pytest.fixture
def otra_pista_libre(catalogo: Catalogo, pista_libre: dict) -> dict:
    """A second cleared track, to test that a quote is bound to its own track."""
    for pista in catalogo.pistas:
        if pista["estado_derechos"] == "libre" and pista["pista_id"] != pista_libre["pista_id"]:
            return pista
    pytest.skip("the catalog needs at least two cleared tracks")


@pytest.fixture
def servidor(catalogo: Catalogo, tmp_path, monkeypatch) -> Servidor:
    """A server with the handshake already done and an isolated usage log."""
    from synclicense_mcp import contracts

    monkeypatch.setattr(contracts, "REGISTRO_USOS", tmp_path / "usage_log.jsonl")

    srv = Servidor(catalogo)
    srv.manejar_mensaje(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        }
    )
    srv.manejar_mensaje({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return srv
