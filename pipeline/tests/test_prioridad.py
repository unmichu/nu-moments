"""ING-3 · Las dos listas son distintas, y es a propósito.

Orden de evaluación  `S0 → S6 → S1 → S2 → S5 → S3 → S7 → S4`
Prioridad de reporte `S0 > S6 > S3 > S2 > S5 > S7 > S4 > S1`

Si se reporta la primera puerta que se dispara en vez de la más informativa, el
momento clave de la demo dice algo aburrido.
"""
from __future__ import annotations

import copy

import pytest

from conftest import ficha_neutra, scores_altos          # noqa: E402
from pipeline import politica                            # noqa: E402
from pipeline.mapas import CATALOGO_DEMO, TODOS_LOS_PRODUCTOS   # noqa: E402


def decidir(f, tabla_valor):
    return politica.decide(f, "2026-06-16T12:00:00", scores_altos(),
                           {"tabla_valor": tabla_valor, "lambda": 266.0,
                            "modelo": "test", "cobertura": None})


def test_las_dos_listas_son_distintas():
    assert politica.ORDEN_EVALUACION != politica.PRIORIDAD_REPORTE
    assert sorted(politica.ORDEN_EVALUACION) == sorted(politica.PRIORIDAD_REPORTE)
    assert politica.ORDEN_EVALUACION == ["S0_opt_out", "S6_fecha", "S1_sin_senal",
                                         "S2_cupo", "S5_descartes", "S3_fragilidad",
                                         "S7_confianza", "S4_valor"]
    assert politica.PRIORIDAD_REPORTE == ["S0_opt_out", "S6_fecha", "S3_fragilidad",
                                          "S2_cupo", "S5_descartes", "S7_confianza",
                                          "S4_valor", "S1_sin_senal"]


def test_fragil_con_cupo_libre_reporta_fragilidad_y_no_un_silencio_generico(ficha, tabla_valor):
    """El caso que hace memorable la demo.

    Cliente frágil, con cupo libre, con señal en la pantalla de aumento de línea
    y SIN señal en el resto: S1 cierra tres productos y S3 cierra el cuarto.
    La respuesta debe reportar **veto por daño**, no «no hay señal».
    """
    f = ficha_neutra(ficha)
    f["decision"]["es_fragil"] = True
    f["decision"]["motivo_fragilidad"] = ["utilización 83.4 %", "2 días en negativo"]
    f["perfil"]["situacion_financiera"]["utilizacion_tarjeta_pct"] = 83.4
    for p in CATALOGO_DEMO:
        if p != "limit_increase":
            f["decision"]["senales_por_nudge"][p]["momento"] = "never"
            f["decision"]["senales_por_nudge"][p]["horas_desde_senal"] = None
    resp = decidir(f, tabla_valor)

    assert resp["decision"] == "silencio"
    assert resp["puerta_reportada"] == politica.S3, "debe reportar el veto por daño"
    assert resp["silencios"][0]["puerta"] == politica.S3, "S3 va primero en el reporte"
    # ...aunque en la traza S1 se haya disparado antes que S3
    orden_traza = [t["puerta"] for t in resp["traza"] if t["resultado"] == "cierra"]
    assert orden_traza.index(politica.S1) < orden_traza.index(politica.S3)


def test_el_orden_de_reporte_no_es_el_de_evaluacion(ficha, tabla_valor):
    f = ficha_neutra(ficha)
    f["decision"]["es_fragil"] = True
    for p in CATALOGO_DEMO:
        if p != "limit_increase":
            f["nudges"]["por_tipo"][p]["exposiciones"] = 2      # S2
    resp = decidir(f, tabla_valor)
    puertas = [s["puerta"] for s in resp["silencios"] if s["puerta"] != politica.C0]
    # S3 antes que S2 en el reporte, al revés que en la evaluación
    assert puertas.index(politica.S3) < puertas.index(politica.S2)


def test_opt_out_gana_a_todo(ficha, tabla_valor):
    f = ficha_neutra(ficha)
    f["nudges"]["opt_out"] = True
    f["decision"]["es_fragil"] = True
    for p in CATALOGO_DEMO:
        f["nudges"]["por_tipo"][p]["exposiciones"] = 9
        f["decision"]["senales_por_nudge"][p]["momento"] = "never"
    resp = decidir(f, tabla_valor)
    assert resp["puerta_reportada"] == politica.S0


# ------------------------------------------------------------ fuera de catálogo
def test_los_productos_fuera_de_catalogo_llevan_su_propio_codigo(ficha, tabla_valor):
    """D15 · un silencio por «sin señal» que en realidad es «no lo vendemos»
    sería mentir en la traza, y la traza es lo que hace auditable al sistema."""
    resp = decidir(ficha_neutra(ficha), tabla_valor)
    fuera = [p for p in TODOS_LOS_PRODUCTOS if p not in CATALOGO_DEMO]
    assert fuera, "el catálogo del piloto deja productos fuera"
    for p in fuera:
        s = next(s for s in resp["silencios"] if s["producto"] == p)
        assert s["puerta"] == politica.C0 == "C0_fuera_de_catalogo"
        assert s["puerta"] != politica.S1


def test_fuera_de_catalogo_nunca_es_la_razon_principal(ficha, tabla_valor):
    f = ficha_neutra(ficha)
    for p in CATALOGO_DEMO:
        f["decision"]["senales_por_nudge"][p]["momento"] = "never"
    resp = decidir(f, tabla_valor)
    assert resp["puerta_reportada"] != politica.C0
    assert resp["puerta_reportada"] == politica.S1


def test_cada_producto_del_universo_aparece_exactamente_una_vez(ficha, tabla_valor):
    f = ficha_neutra(ficha)
    for p in CATALOGO_DEMO:
        f["decision"]["senales_por_nudge"][p]["momento"] = "never"
    resp = decidir(f, tabla_valor)
    productos = [s["producto"] for s in resp["silencios"]]
    assert sorted(productos) == sorted(TODOS_LOS_PRODUCTOS)
    assert len(productos) == len(set(productos))


# ---------------------------------------------------------------- sustitución
def test_el_veto_se_convierte_en_sustitucion_cuando_hay_alternativa_sana(ficha, tabla_valor):
    f = ficha_neutra(ficha)
    f["decision"]["es_fragil"] = True
    f["perfil"]["situacion_financiera"]["utilizacion_tarjeta_pct"] = 83.4
    resp = decidir(f, tabla_valor)
    assert resp["decision"] == "sustitucion"
    assert resp["sustituye_a"] == "limit_increase"
    assert resp["ofertas"][0]["producto"] != "limit_increase"
    assert resp["ofertas"][0]["sustituye_a"] == "limit_increase"


def test_sin_alternativa_sana_el_veto_es_silencio(ficha, tabla_valor):
    f = ficha_neutra(ficha)
    f["decision"]["es_fragil"] = True
    for p in CATALOGO_DEMO:
        if p != "limit_increase":
            f["decision"]["senales_por_nudge"][p]["momento"] = "never"
    resp = decidir(f, tabla_valor)
    assert resp["decision"] == "silencio"
    assert resp["sustituye_a"] is None
