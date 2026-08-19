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


@pytest.fixture
def pista_libre(catalogo: Catalogo) -> dict:
    """TRK-00001 "Sunburst": pinned by the seed script as a cleared track."""
    return catalogo.obtener("TRK-00001")


@pytest.fixture
def pista_con_samples(catalogo: Catalogo) -> dict:
    """TRK-00002: pinned as a track with samples pending clearance."""
    return catalogo.obtener("TRK-00002")


@pytest.fixture
def pista_bloqueada(catalogo: Catalogo) -> dict:
    """TRK-00003: pinned as a track frozen by an authorship dispute."""
    return catalogo.obtener("TRK-00003")


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
