"""ING-3 · Una prueba por puerta: un caso que la dispara y uno que no.

Ocho puertas, dos pruebas cada una. Todas parten de la misma ficha real
neutralizada y mueven **un solo hecho**, para que el cierre no se pueda
atribuir a otra cosa.

Las puertas que el piloto declara no activas (S5 y S7) se prueban en dos
niveles: la función *sí* detecta la condición, y `decide()` la registra como
`no_activa` sin callar a nadie. Declararlas no activas es una decisión de
producto, no un hueco de implementación.
"""
from __future__ import annotations

import pytest

from pipeline import politica
from pipeline.ingesta import zona_contaminada
from pipeline.mapas import CATALOGO_DEMO
from pipeline.politica import C0, S0, S1, S2, S3, S4, S5, S6, S7


def traza_de(resp, codigo):
    return next(f for f in resp["traza"] if f["puerta"] == codigo)


def silencio_de(resp, producto):
    return next((s for s in resp["silencios"] if s["producto"] == producto), None)


# ==========================================================================
# S0 · opt-out
# ==========================================================================
def test_S0_cierra_cuando_hay_opt_out(ficha, scores, artefactos):
    ficha["nudges"]["opt_out"] = True
    assert politica.puerta_S0(ficha, "savings_goal", {})[0] is True

    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert r["decision"] == "silencio"
    assert traza_de(r, S0)["resultado"] == "cierra"
    # el opt-out es de cliente: calla el catálogo entero, no un producto
    assert {s["producto"] for s in r["silencios"] if s["puerta"] == S0} == set(CATALOGO_DEMO)
    assert r["puerta_reportada"] == S0


def test_S0_no_cierra_sin_opt_out(ficha, scores, artefactos):
    assert politica.puerta_S0(ficha, "savings_goal", {})[0] is False
    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert traza_de(r, S0)["resultado"] == "pasa"


# ==========================================================================
# S6 · zona de datos contaminada
# ==========================================================================
@pytest.mark.parametrize("fecha", ["2026-03-01", "2026-03-02", "2026-06-28", "2027-01-01"])
def test_S6_cierra_en_fechas_contaminadas(fecha):
    contaminada, motivo = zona_contaminada(fecha)
    assert contaminada is True
    assert motivo


@pytest.mark.parametrize("fecha", ["2026-03-05", "2026-05-23", "2026-06-16"])
def test_S6_no_cierra_en_fechas_usables(fecha):
    assert zona_contaminada(fecha)[0] is False


def test_S6_calla_el_catalogo_entero(ficha, scores, artefactos):
    ficha["decision"]["fecha_contaminada"] = True
    ficha["decision"]["motivo_fecha"] = "los primeros 3 días del panel son un artefacto"
    r = politica.decide(ficha, "2026-03-01T12:00:00", scores, artefactos)
    assert r["decision"] == "silencio"
    assert traza_de(r, S6)["resultado"] == "cierra"
    assert r["puerta_reportada"] == S6
    assert r["ofertas"] == []


def test_S6_pasa_con_la_fecha_del_demo(ficha, scores, artefactos):
    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert traza_de(r, S6)["resultado"] == "pasa"


# ==========================================================================
# S1 · sin señal reciente
# ==========================================================================
@pytest.mark.parametrize("momento", ["cold", "never"])
def test_S1_cierra_sin_senal_reciente(ficha, scores, artefactos, momento):
    for p in CATALOGO_DEMO:
        ficha["decision"]["senales_por_nudge"][p]["momento"] = momento
        ficha["decision"]["senales_por_nudge"][p]["horas_desde_senal"] = None
    assert politica.puerta_S1(ficha, "savings_goal", {})[0] is True

    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert r["decision"] == "silencio"
    assert traza_de(r, S1)["resultado"] == "cierra"
    assert silencio_de(r, "savings_goal")["puerta"] == S1


@pytest.mark.parametrize("momento", ["on_time", "warm"])
def test_S1_no_cierra_con_senal(ficha, scores, artefactos, momento):
    ficha["decision"]["senales_por_nudge"]["savings_goal"]["momento"] = momento
    assert politica.puerta_S1(ficha, "savings_goal", {})[0] is False

    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert "savings_goal" in [o["producto"] for o in r["ofertas"]]


# ==========================================================================
# S2 · cupo de exposiciones (cap = 2)
# ==========================================================================
def test_S2_cierra_con_el_cupo_agotado(ficha, scores, artefactos):
    ficha["nudges"]["por_tipo"]["savings_goal"]["exposiciones"] = 2
    assert politica.puerta_S2(ficha, "savings_goal", {})[0] is True

    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert silencio_de(r, "savings_goal")["puerta"] == S2
    assert traza_de(r, S2)["resultado"] == "cierra"
    assert "savings_goal" not in [o["producto"] for o in r["ofertas"]]


def test_S2_no_cierra_con_una_sola_exposicion(ficha, scores, artefactos):
    ficha["nudges"]["por_tipo"]["savings_goal"]["exposiciones"] = 1
    assert politica.puerta_S2(ficha, "savings_goal", {})[0] is False

    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert traza_de(r, S2)["resultado"] == "pasa"
    assert "savings_goal" in [o["producto"] for o in r["ofertas"]]


# ==========================================================================
# S5 · descartes repetidos — implementada, NO activa
# ==========================================================================
def test_S5_detecta_los_descartes_pero_no_calla(ficha, scores, artefactos):
    ficha["nudges"]["por_tipo"]["savings_goal"]["n_descartados"] = 3
    # la función sí ve la condición…
    assert politica.puerta_S5(ficha, "savings_goal", {})[0] is True
    # …pero la puerta está declarada no activa en el piloto
    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert traza_de(r, S5)["resultado"] == "no_activa"
    assert silencio_de(r, "savings_goal") is None
    assert "savings_goal" in [o["producto"] for o in r["ofertas"]]


def test_S5_no_se_dispara_sin_descartes(ficha):
    ficha["nudges"]["por_tipo"]["savings_goal"]["n_descartados"] = 0
    assert politica.puerta_S5(ficha, "savings_goal", {})[0] is False


# ==========================================================================
# S3 · fragilidad
# ==========================================================================
def test_S3_cierra_para_el_fragil_en_el_producto_que_daña(ficha, scores, artefactos):
    ficha["decision"]["es_fragil"] = True
    ficha["decision"]["motivo_fragilidad"] = ["utilización 89.6 % (arriba de 70 %)"]
    assert politica.puerta_S3(ficha, "limit_increase", {})[0] is True

    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert silencio_de(r, "limit_increase")["puerta"] == S3
    assert traza_de(r, S3)["resultado"] == "cierra"
    assert traza_de(r, S3)["producto"] == "limit_increase"


def test_S3_no_cierra_productos_sanos_ni_a_clientes_sanos(ficha, scores, artefactos):
    ficha["decision"]["es_fragil"] = True
    # el veto es duro y acotado: solo el aumento de línea (D5)
    assert politica.puerta_S3(ficha, "savings_goal", {})[0] is False
    assert politica.puerta_S3(ficha, "bill_reminder", {})[0] is False

    ficha["decision"]["es_fragil"] = False
    assert politica.puerta_S3(ficha, "limit_increase", {})[0] is False
    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert traza_de(r, S3)["resultado"] == "pasa"


# ==========================================================================
# S7 · confianza del modelo — implementada, NO activa
# ==========================================================================
def test_S7_detecta_la_baja_confianza_pero_no_calla(ficha, scores, artefactos):
    scores["savings_goal"]["confianza"] = 0.0001
    ctx = {"scores": scores, "umbral_confianza": politica.UMBRAL_CONFIANZA_DEFECTO}
    assert politica.puerta_S7(ficha, "savings_goal", ctx)[0] is True

    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert traza_de(r, S7)["resultado"] == "no_activa"
    assert silencio_de(r, "savings_goal") is None


def test_S7_no_se_dispara_con_confianza_alta(ficha, scores):
    ctx = {"scores": scores, "umbral_confianza": politica.UMBRAL_CONFIANZA_DEFECTO}
    assert politica.puerta_S7(ficha, "savings_goal", ctx)[0] is False


# ==========================================================================
# S4 · valor esperado
# ==========================================================================
def test_S4_cierra_con_valor_negativo(ficha, scores, artefactos):
    artefactos["tabla_valor"] = dict(artefactos["tabla_valor"])
    artefactos["tabla_valor"]["savings_goal"] = {"V": -0.5}
    ctx = {"tabla_valor": artefactos["tabla_valor"], "lambda": 266.0}
    assert politica.puerta_S4(ficha, "savings_goal", ctx)[0] is True

    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert silencio_de(r, "savings_goal")["puerta"] == S4
    assert traza_de(r, S4)["resultado"] == "cierra"


def test_S4_no_cierra_con_valor_positivo(ficha, scores, artefactos, tabla_valor):
    ctx = {"tabla_valor": tabla_valor, "lambda": 266.0}
    assert tabla_valor["savings_goal"]["V"] > 0
    assert politica.puerta_S4(ficha, "savings_goal", ctx)[0] is False

    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert "savings_goal" in [o["producto"] for o in r["ofertas"]]


def test_S4_revienta_si_falta_el_producto_en_la_tabla(ficha):
    ctx = {"tabla_valor": {}, "lambda": 266.0}
    with pytest.raises(politica.ErrorDePolitica):
        politica.puerta_S4(ficha, "savings_goal", ctx)


# ==========================================================================
# La traza es un contrato: 8 filas, siempre, pase lo que pase.
# ==========================================================================
def test_la_traza_trae_las_ocho_puertas_en_orden_de_evaluacion(ficha, scores, artefactos):
    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert [f["puerta"] for f in r["traza"]] == politica.ORDEN_EVALUACION
    assert len(r["traza"]) == 8


def test_la_traza_se_emite_tambien_cuando_hay_oferta(ficha, scores, artefactos):
    r = politica.decide(ficha, "2026-06-16T12:00:00", scores, artefactos)
    assert r["ofertas"], "esta ficha debería producir al menos una oferta"
    assert len(r["traza"]) == 8
    assert r["silencios"], "los silencios se emiten siempre, también con oferta"


def test_el_orden_de_evaluacion_y_la_prioridad_de_reporte_son_distintos():
    assert politica.ORDEN_EVALUACION == [S0, S6, S1, S2, S5, S3, S7, S4]
    assert politica.PRIORIDAD_REPORTE == [S0, S6, S3, S2, S5, S7, S4, S1]
    assert politica.ORDEN_EVALUACION != politica.PRIORIDAD_REPORTE
