"""Tests for the catalog seed script.

The offline generator is the reason the project can be demoed without network
access or credentials, so its two guarantees are worth locking down: the same
seed produces the same catalog, and the business layer keeps the distribution
of rights statuses the use case depends on.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The seed script is a standalone CLI, not part of the package, so it is loaded
# by path rather than imported as a module.
_spec = importlib.util.spec_from_file_location(
    "seed_catalog", REPO_ROOT / "scripts" / "seed_catalog.py"
)
seed_catalog = importlib.util.module_from_spec(_spec)
sys.modules["seed_catalog"] = seed_catalog
_spec.loader.exec_module(seed_catalog)


def test_el_mismo_seed_produce_el_mismo_catalogo():
    """Determinism is what makes the committed catalog reviewable."""
    primero = seed_catalog.generar_offline(200, seed=23016)
    segundo = seed_catalog.generar_offline(200, seed=23016)
    assert primero == segundo


def test_seeds_distintos_producen_catalogos_distintos():
    assert seed_catalog.generar_offline(50, seed=1) != seed_catalog.generar_offline(50, seed=2)


def test_las_pistas_fijas_encabezan_el_catalogo():
    """The demo and the test suite rely on TRK-00001..00003 being pinned."""
    pistas = seed_catalog.generar_offline(50, seed=23016)
    assert pistas[0]["pista_id"] == "TRK-00001"
    assert pistas[0]["titulo"] == "Sunburst"
    assert pistas[0]["estado_derechos"] == "libre"
    assert pistas[1]["estado_derechos"] == "samples_pendientes"
    assert pistas[2]["estado_derechos"] == "bloqueada"


def test_los_ids_son_unicos_y_correlativos():
    pistas = seed_catalog.generar_offline(300, seed=7)
    ids = [p["pista_id"] for p in pistas]
    assert len(set(ids)) == len(ids)
    assert ids[-1] == f"TRK-{len(pistas):05d}"


def test_la_distribucion_de_derechos_es_realista():
    """Most of a catalog is cleared; blocked tracks are the rare exception."""
    pistas = seed_catalog.generar_offline(1000, seed=23016)
    total = len(pistas)
    proporcion = {
        estado: sum(1 for p in pistas if p["estado_derechos"] == estado) / total
        for estado in ("libre", "samples_pendientes", "bloqueada")
    }
    assert proporcion["libre"] == pytest.approx(0.82, abs=0.05)
    assert proporcion["samples_pendientes"] == pytest.approx(0.13, abs=0.05)
    assert proporcion["bloqueada"] == pytest.approx(0.05, abs=0.03)


def test_la_tarifa_base_crece_con_duracion_y_popularidad():
    corta = seed_catalog.tarifa_base(30, 10)
    larga = seed_catalog.tarifa_base(300, 10)
    popular = seed_catalog.tarifa_base(30, 99)
    assert larga > corta and popular > corta
    # The band the rate card was designed around.
    assert 18 <= corta <= 130 and 18 <= seed_catalog.tarifa_base(300, 99) <= 130


def test_un_client_id_vacio_no_llega_a_la_api(tmp_path, monkeypatch):
    """A .env copied from the example but left blank must explain what to do."""
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    monkeypatch.setattr(seed_catalog, "REPO_ROOT", tmp_path)
    (tmp_path / ".env").write_text("JAMENDO_CLIENT_ID=\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        seed_catalog.cargar_client_id()
    assert "devportal.jamendo.com" in str(exc.value)


def test_se_lee_el_client_id_del_archivo_env(tmp_path, monkeypatch):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    monkeypatch.setattr(seed_catalog, "REPO_ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        '# comment\nJAMENDO_CLIENT_ID="abc123"\n', encoding="utf-8"
    )
    assert seed_catalog.cargar_client_id() == "abc123"


def test_el_entorno_tiene_prioridad_sobre_el_archivo(tmp_path, monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "desde-el-entorno")
    monkeypatch.setattr(seed_catalog, "REPO_ROOT", tmp_path)
    (tmp_path / ".env").write_text("JAMENDO_CLIENT_ID=desde-el-archivo\n", encoding="utf-8")
    assert seed_catalog.cargar_client_id() == "desde-el-entorno"
