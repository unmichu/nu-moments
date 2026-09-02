"""ING-4 · El nivel 3 **activo**, y que no mienta.

Dos defectos reales que esta suite cierra:

* `demo_pack.json` se indexaba solo por `customer_id` y se construyó a un único
  corte. `multi_senal` (#6030902) está curado al 2026-06-09, así que el nivel 3
  devolvía sus números del 2026-06-16: misma oferta, otros scores. Un fallback
  que devuelve otra cosa que el nivel que sustituye, miente.
* Al nivel 3 no se llegaba quitando artefactos —`ReglaVeinticuatroHoras.cargar()`
  nunca falla— así que ninguna prueba corría con `demo_pack` como nivel activo.
  Ahora hay un interruptor explícito, `NU_MOMENTS_NIVEL_MAX`, y se ejercita.
"""
from __future__ import annotations

import pytest

import comun
from app import scoring
from pipeline import politica
from pipeline.mapas import CATALOGO_DEMO, CORTE_DEMO

CAMPOS = ("p_intencion", "p_enganche", "V", "score", "confianza")
TOLERANCIA = 1e-6


@pytest.fixture(scope="module")
def nivel1():
    return scoring.ModeloEntrenado.cargar(corte=CORTE_DEMO)


@pytest.fixture(scope="module")
def nivel3():
    return scoring.PaquetePrecalculado.cargar()


# ==========================================================================
# 1 · El nivel 3 dice lo mismo que el nivel 1 en los 9 escenarios
# ==========================================================================
@pytest.mark.parametrize("caso", comun.casos_curados(),
                         ids=[c["clave"] for c in comun.casos_curados()])
def test_el_nivel_3_no_miente_en_ninguno_de_los_9(nivel1, nivel3, caso):
    """Misma decisión y **los mismos números**, no solo la misma oferta."""
    cid = int(caso["customer_id"])
    asof = comun.asof_del_caso(caso)
    ficha = comun.store().ficha(cid, asof)
    tv = comun.tabla_valor()

    s1 = nivel1.scores(ficha, tv)
    s3 = nivel3.scores(ficha, tv)

    assert set(s3) == set(s1) == set(CATALOGO_DEMO)
    for prod in CATALOGO_DEMO:
        for campo in CAMPOS:
            assert abs(float(s3[prod][campo]) - float(s1[prod][campo])) <= TOLERANCIA, (
                f"{caso['clave']} · {prod} · {campo}: "
                f"nivel 1 {s1[prod][campo]} vs nivel 3 {s3[prod][campo]}")

    d1 = comun.decidir(ficha, scores=s1, fecha=asof, modelo="v1")
    d3 = comun.decidir(ficha, scores=s3, fecha=asof, modelo="demo_pack")
    assert d3["decision"] == d1["decision"]
    assert comun.productos_ofertados(d3) == comun.productos_ofertados(d1)
    assert d3["puerta_reportada"] == d1["puerta_reportada"]
    assert d3.get("sustituye_a") == d1.get("sustituye_a")


def test_el_paquete_esta_indexado_por_cliente_y_corte(nivel3):
    """El grano es la pareja, no el cliente: si no, un corte pisa al otro."""
    caso = next(c for c in comun.casos_curados() if c["clave"] == "multi_senal")
    cid = str(caso["customer_id"])
    assert "2026-06-09" in nivel3.cortes and CORTE_DEMO in nivel3.cortes

    e9, c9 = nivel3.entrada(cid, "2026-06-09T00:00:00")
    e16, c16 = nivel3.entrada(cid, f"{CORTE_DEMO}T12:00:00")
    assert (c9, c16) == ("2026-06-09", CORTE_DEMO)
    assert e9["scores"] != e16["scores"], (
        "los dos cortes guardan lo mismo: el paquete sigue teniendo un solo corte")


def test_un_asof_desconocido_resuelve_al_corte_del_demo(nivel3):
    """Retrocompatibilidad: un `customer_id` sin `asof` conocido no revienta."""
    cid = str(comun.CLIENTE_AHORRO)
    esperado, _ = nivel3.entrada(cid, f"{CORTE_DEMO}T12:00:00")
    for asof in (None, "1999-01-01T00:00:00", "2030-12-31T23:00:00"):
        entrada, corte = nivel3.entrada(cid, asof)
        assert corte == nivel3.corte_defecto == CORTE_DEMO
        assert entrada == esperado


def test_un_cliente_ausente_no_se_inventa(nivel3):
    with pytest.raises(scoring.NivelNoDisponible):
        nivel3.entrada("-1", f"{CORTE_DEMO}T12:00:00")


# ==========================================================================
# 2 · Se puede llegar al nivel 3 a propósito, y se ve en /health
# ==========================================================================
def test_el_interruptor_apaga_los_niveles_de_arriba(monkeypatch):
    """`NU_MOMENTS_NIVEL_MAX` degrada sin corromper un solo artefacto."""
    monkeypatch.setenv(scoring.VAR_NIVEL_MAX, "demo_pack")
    e = scoring.Escalera.cargar(comun.store())
    assert e.nivel_activo == "demo_pack"
    estado = e.estado()
    assert estado["nivel_max"] == "demo_pack"
    assert estado["niveles_montados"] == ["demo_pack"]
    for nivel in ("v1", "regla_24h"):
        assert scoring.VAR_NIVEL_MAX in estado["niveles_caidos"][nivel]


def test_el_interruptor_intermedio_deja_la_regla_de_24h(monkeypatch):
    monkeypatch.setenv(scoring.VAR_NIVEL_MAX, "regla_24h")
    e = scoring.Escalera.cargar(comun.store())
    assert e.nivel_activo == "regla_24h"
    assert e.estado()["niveles_montados"] == ["regla_24h", "demo_pack"]


def test_un_valor_invalido_no_pasa_desapercibido(monkeypatch):
    monkeypatch.setenv(scoring.VAR_NIVEL_MAX, "v2")
    with pytest.raises(scoring.NivelNoDisponible):
        scoring.nivel_max()


def test_sin_la_variable_la_escalera_corre_en_el_modelo(monkeypatch):
    monkeypatch.delenv(scoring.VAR_NIVEL_MAX, raising=False)
    assert scoring.nivel_max() is None
    assert scoring.Escalera.cargar(comun.store()).nivel_activo == "v1"


# ==========================================================================
# 3 · La demo entera corriendo en el nivel 3
# ==========================================================================
@pytest.fixture(scope="module")
def api_nivel3():
    """La app real, con el lifespan real, con la escalera topada en el nivel 3."""
    import os

    from fastapi.testclient import TestClient

    from app.main import app
    previo = os.environ.get(scoring.VAR_NIVEL_MAX)
    os.environ[scoring.VAR_NIVEL_MAX] = "demo_pack"
    try:
        with TestClient(app) as c:
            yield c
    finally:
        if previo is None:
            os.environ.pop(scoring.VAR_NIVEL_MAX, None)
        else:
            os.environ[scoring.VAR_NIVEL_MAX] = previo


def test_health_declara_que_corre_en_el_nivel_3(api_nivel3):
    h = api_nivel3.get("/health").json()
    assert h["modelo"] == "demo_pack"
    assert h["en_fallback"] is True and h["en_modelo"] is False
    assert h["escalera"]["nivel_max"] == "demo_pack"
    assert h["escalera"]["cortes_demo_pack"] == ["2026-06-09", CORTE_DEMO]


@pytest.mark.parametrize("caso", comun.casos_curados(),
                         ids=[c["clave"] for c in comun.casos_curados()])
def test_los_9_escenarios_sobreviven_al_nivel_3(api_nivel3, caso):
    """Con el modelo apagado, el guion sigue siendo el mismo guion."""
    r = api_nivel3.post("/api/decidir", json={"customer_id": caso["customer_id"],
                                              "asof": comun.asof_del_caso(caso)})
    assert r.status_code == 200
    d = r.json()
    assert d["modelo"] == "demo_pack", "el nivel 3 no llegó a servir la petición"
    esperado = caso["decision"].get("nudge_type")
    obtenido = d["ofertas"][0]["producto"] if d["ofertas"] else None
    assert obtenido == esperado, (
        f"{caso['clave']}: el nivel 3 promete {esperado!r} y dio {obtenido!r}")
