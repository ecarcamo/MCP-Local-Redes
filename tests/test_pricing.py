"""Tests for the rate card rules."""

from __future__ import annotations

import pytest

from synclicense_mcp import pricing
from synclicense_mcp.errors import ErrorDeNegocio


def test_caso_de_referencia_de_la_propuesta(pista_libre):
    """Social media, local, non-exclusive, six months is the reference scenario.

    Every multiplier is 1.0 there, so the total must equal the base fee. This
    is the USD 45 figure quoted in the approved project proposal.
    """
    desglose = pricing.calcular(pista_libre, "redes_sociales", "local", "no", 6)
    assert desglose["total_usd"] == 45.00
    assert desglose["multiplicadores"] == {
        "tipo_uso": 1.0,
        "territorio": 1.0,
        "exclusividad": 1.0,
        "vigencia": 1.0,
    }


def test_los_multiplicadores_se_componen(pista_libre):
    """The four dimensions multiply together rather than being applied apart."""
    desglose = pricing.calcular(pista_libre, "cine", "mundial", "total", 12)
    esperado = 45.0 * 8.0 * 3.2 * 4.5 * 1.5
    assert desglose["subtotal_usd"] == pytest.approx(round(esperado, 2))


def test_un_uso_mas_caro_sube_el_precio(pista_libre):
    barato = pricing.calcular(pista_libre, "redes_sociales", "local", "no", 6)
    caro = pricing.calcular(pista_libre, "tv_nacional", "local", "no", 6)
    assert caro["total_usd"] > barato["total_usd"]


def test_licencia_perpetua_es_la_vigencia_mas_cara():
    assert pricing.multiplicador_vigencia(0) == pricing.MULT_VIGENCIA_PERPETUA
    assert pricing.multiplicador_vigencia(0) > pricing.multiplicador_vigencia(120)


@pytest.mark.parametrize(
    "meses, esperado",
    [(1, 0.8), (3, 0.8), (4, 1.0), (6, 1.0), (12, 1.5), (24, 2.2), (36, 2.8), (60, 3.2)],
)
def test_escala_de_vigencia(meses, esperado):
    assert pricing.multiplicador_vigencia(meses) == esperado


def test_recargo_de_escrow_para_samples_pendientes(pista_con_samples):
    """A track with unresolved samples carries a 15% surcharge over the subtotal."""
    desglose = pricing.calcular(pista_con_samples, "redes_sociales", "local", "no", 6)
    assert desglose["recargo_escrow_pct"] == 15.0
    assert desglose["recargo_escrow_usd"] == pytest.approx(
        round(desglose["subtotal_usd"] * 0.15, 2)
    )
    assert desglose["total_usd"] == pytest.approx(
        round(desglose["subtotal_usd"] + desglose["recargo_escrow_usd"], 2)
    )


def test_sin_recargo_cuando_la_pista_esta_libre(pista_libre):
    desglose = pricing.calcular(pista_libre, "podcast", "latam", "no", 12)
    assert desglose["recargo_escrow_usd"] == 0.0
    assert desglose["total_usd"] == desglose["subtotal_usd"]


def test_una_pista_bloqueada_no_se_puede_cotizar(pista_bloqueada):
    with pytest.raises(ErrorDeNegocio) as exc:
        pricing.calcular(pista_bloqueada, "redes_sociales", "local", "no", 6)
    assert exc.value.motivo == "pista_bloqueada"


def test_los_montos_se_redondean_a_dos_decimales(pista_con_samples):
    desglose = pricing.calcular(pista_con_samples, "videojuego", "europa", "sectorial", 24)
    for clave in ("subtotal_usd", "recargo_escrow_usd", "total_usd"):
        assert round(desglose[clave], 2) == desglose[clave]
