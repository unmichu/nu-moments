"""ING-7 · Fuga temporal **en tiempo de servicio**.

`pipeline/tests/test_leakage.py` demuestra que la *construcción* de features no
mira el futuro. Esto demuestra lo otro, que no cubría nadie: que el **servicio**
tampoco lo mira.

El defecto real: `app/scoring.ModeloEntrenado` cargaba
`features_asof_2026-06-16.parquet` y lo usaba para cualquier `asof`. El caso
curado `multi_senal` (#6030902) se decide el **2026-06-09**, así que su
`p_intencion` salía de una foto tomada **7 días después** de la decisión que se
enseña en pantalla.

La regla, y lo que aquí se comprueba:

1. corte exacto si lo hay;
2. si no, el más reciente **anterior o igual** al `asof`;
3. **nunca uno posterior**;
4. si no hay ninguno válido, el nivel se declara caído para esa petición y la
   escalera baja, con el motivo publicado en `/health`.

Estas pruebas fallan si alguien revierte el arreglo: la afirmación central no
es «se eligió tal archivo» sino «el número servido es el de la foto del día de
la decisión y **no** el de la foto posterior».
"""
from __future__ import annotations

import pytest

import comun
from app import scoring
from pipeline.mapas import CATALOGO_DEMO, CORTE_DEMO

CASO_ANTERIOR = "multi_senal"      # #6030902, curado al 2026-06-09
CORTE_ANTERIOR = "2026-06-09"


@pytest.fixture(scope="module")
def modelo():
    """El nivel 1 tal cual lo monta el arranque: con todas las fotos dentro."""
    return scoring.ModeloEntrenado.cargar(corte=CORTE_DEMO)


@pytest.fixture(scope="module")
def api():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


# ==========================================================================
# 1 · La elección del corte
# ==========================================================================
def test_las_fotos_se_cargan_en_el_arranque_no_por_peticion(modelo):
    """Las 5 tablas as-of están en memoria antes de la primera petición."""
    assert len(modelo.cortes) >= 2, "solo hay una foto: no hay nada que elegir"
    assert CORTE_DEMO in modelo.cortes and CORTE_ANTERIOR in modelo.cortes
    for c in modelo.cortes:
        assert not modelo.tablas[c].empty


def test_corte_exacto_cuando_existe(modelo):
    for c in modelo.cortes:
        assert modelo.corte_para(f"{c}T12:00:00") == c


def test_sin_coincidencia_se_toma_el_anterior_mas_reciente_nunca_el_posterior(modelo):
    """Un `asof` en el hueco entre dos fotos usa la de antes, no la de después."""
    hueco = "2026-06-12T12:00:00"       # entre 2026-06-09 y 2026-06-14
    elegido = modelo.corte_para(hueco)
    assert elegido == "2026-06-09"
    assert elegido <= hueco[:10], "se eligió una foto POSTERIOR al asof: es fuga"


@pytest.mark.parametrize("asof", ["2026-05-23", "2026-05-30", "2026-06-09",
                                  "2026-06-11", "2026-06-14", "2026-06-16",
                                  "2026-06-20"])
def test_el_corte_elegido_jamas_es_posterior_al_asof(modelo, asof):
    elegido = modelo.corte_para(f"{asof}T12:00:00")
    assert elegido is not None
    assert elegido <= asof, f"para asof={asof} se eligió la foto {elegido}"


def test_un_asof_anterior_a_todas_las_fotos_no_se_adivina(modelo):
    """Antes de la foto más antigua no hay respuesta honesta: el nivel cae."""
    with pytest.raises(scoring.NivelNoDisponible) as err:
        modelo.tabla_para("2026-01-05T12:00:00")
    assert "fuga" in str(err.value) or "no hay tabla" in str(err.value)


# ==========================================================================
# 2 · La prueba que falla si se revierte el arreglo
# ==========================================================================
def _caso(clave):
    return next(c for c in comun.casos_curados() if c["clave"] == clave)


def test_una_decision_anterior_al_corte_del_demo_no_usa_la_foto_posterior(modelo):
    """El corazón del asunto, sobre el caso real que lo destapó.

    Se puntúa #6030902 al 2026-06-09 y se compara contra las dos fotos
    candidatas. Debe coincidir con la del **día de la decisión** y diferir de la
    del 2026-06-16, que es la que servía el código con fuga.
    """
    caso = _caso(CASO_ANTERIOR)
    cid = int(caso["customer_id"])
    asof = comun.asof_del_caso(caso)
    assert asof[:10] == CORTE_ANTERIOR < CORTE_DEMO

    ficha = comun.store().ficha(cid, asof)
    servido = modelo.scores(ficha, comun.tabla_valor())

    cabezas = modelo._cabezas(modelo.intencion)

    def p_intencion_con(corte, producto):
        from pipeline.mapas import PRODUCTO_A_ACCION
        x = modelo.tablas[corte].loc[[cid], modelo.columnas]
        return round(float(cabezas[PRODUCTO_A_ACCION[producto]].predict_proba(x)[0][1]), 4)

    for prod in CATALOGO_DEMO:
        assert servido[prod]["corte_features"] == CORTE_ANTERIOR
        assert servido[prod]["p_intencion"] == p_intencion_con(CORTE_ANTERIOR, prod), (
            f"{prod}: el servicio no usó la foto del día de la decisión")

    # y el control: la foto posterior daba OTRO número. Sin esto, lo de arriba
    # podría pasar por casualidad y la prueba no demostraría nada.
    distintos = [p for p in CATALOGO_DEMO
                 if p_intencion_con(CORTE_DEMO, p) != p_intencion_con(CORTE_ANTERIOR, p)]
    assert distintos, ("las dos fotos dan lo mismo: esta prueba no podría fallar "
                       "aunque se reintrodujera la fuga")


def test_el_post_declara_de_que_foto_salio_cada_oferta(api):
    """La misma comprobación, extremo a extremo, por el endpoint que ve la demo."""
    caso = _caso(CASO_ANTERIOR)
    asof = comun.asof_del_caso(caso)
    r = api.post("/api/decidir", json={"customer_id": caso["customer_id"], "asof": asof})
    assert r.status_code == 200
    d = r.json()
    assert d["modelo"] == "v1"
    assert d["ofertas"], "el escenario curado promete oferta"
    for o in d["ofertas"]:
        assert o["corte_features"] is not None
        assert o["corte_features"] <= asof[:10], (
            f"la oferta se puntuó con la foto {o['corte_features']}, posterior a {asof}")


def test_cada_escenario_curado_se_puntua_con_su_propio_corte(api):
    """Los 9 del guion. Ninguno puede puntuarse con una foto de su futuro."""
    for caso in comun.casos_curados():
        asof = comun.asof_del_caso(caso)
        d = api.post("/api/decidir", json={"customer_id": caso["customer_id"],
                                           "asof": asof}).json()
        for o in d.get("ofertas") or []:
            assert o["corte_features"] <= asof[:10], (
                f"{caso['clave']}: foto {o['corte_features']} para asof {asof}")


# ==========================================================================
# 3 · Sin foto válida el nivel baja, y se dice
# ==========================================================================
def test_sin_foto_valida_baja_de_nivel_con_el_motivo_en_health():
    """Un `asof` anterior a todas las fotos no se inventa: se degrada y se explica."""
    e = comun.escalera()
    ficha = comun.store().ficha(comun.CLIENTE_AHORRO, "2026-01-05T12:00:00")
    scores, nivel = e.puntuar(ficha)
    assert nivel != "v1", "puntuar sin foto vigente sería adivinar"
    assert set(scores) == set(CATALOGO_DEMO)

    estado = e.estado()
    motivo = estado["descensos_en_peticion"].get("v1")
    assert motivo, "el nivel bajó sin dejar motivo publicable en /health"
    assert "features" in motivo or "fuga" in motivo

    # y el descenso no es pegajoso: con un asof válido se vuelve al nivel 1
    _, nivel_ok = e.puntuar(comun.store().ficha(comun.CLIENTE_AHORRO, comun.ASOF))
    assert nivel_ok == "v1"
    assert "v1" not in e.estado()["descensos_en_peticion"]
