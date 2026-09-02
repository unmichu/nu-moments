"""Utilidades compartidas por la suite de ingeniería.

Están aquí y no en `conftest.py` a propósito: son funciones normales, no
fixtures, así que cualquier módulo de prueba puede importarlas sin depender del
orden de descubrimiento de pytest ni de qué fixtures existan.

Lo caro (las 5 tablas, la escalera de scoring, la app con su `lifespan`) se
monta **una sola vez por proceso** y se cachea aquí.
"""
from __future__ import annotations

import copy
import functools
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from pipeline.mapas import CATALOGO_DEMO, CORTE_DEMO, TODOS_LOS_PRODUCTOS  # noqa: E402

ASOF = f"{CORTE_DEMO}T12:00:00"

# Los clientes del guion. Cada uno existe para disparar una puerta distinta.
CLIENTE_ESTRELLA = 6016480      # frágil + señal fresca de línea + cupo libre → S3
CLIENTE_AHORRO = 6024615        # señal fresca de Cajita → oferta
CLIENTE_SUSTITUCION = 6007107   # frágil pide línea → se sustituye por bill_reminder
CLIENTE_FATIGADO = 6035011      # cupo agotado → S2
CLIENTE_SIN_SENAL = 6033683     # sin señal → S1
CLIENTE_OPT_OUT = 6011629       # baja de notificaciones → S0


@functools.lru_cache(maxsize=1)
def store():
    from pipeline.ingesta import Store
    return Store.cargar(os.path.join(RAIZ, "data"), evidencias=False)


@functools.lru_cache(maxsize=1)
def escalera():
    from app.scoring import Escalera
    return Escalera.cargar(store(), corte=CORTE_DEMO)


@functools.lru_cache(maxsize=1)
def tabla_valor():
    return escalera().tabla_valor


@functools.lru_cache(maxsize=1)
def _ficha_base():
    return store().ficha(CLIENTE_AHORRO, ASOF)


@functools.lru_cache(maxsize=1)
def casos_curados():
    ruta = os.path.join(RAIZ, "pipeline", "artifacts", "casos_ejemplo.json")
    with open(ruta, encoding="utf-8") as fh:
        return json.load(fh)["casos"]


@functools.lru_cache(maxsize=1)
def contrato():
    """`app/fixture.json` · la forma final de la respuesta del POST (ING-2)."""
    with open(os.path.join(RAIZ, "app", "fixture.json"), encoding="utf-8") as fh:
        return json.load(fh)


def asof_del_caso(caso):
    """El `asof` con el que se verificó el escenario, no una hora inventada."""
    return str(caso["ficha"]["decision"]["asof"]).replace(" ", "T")


# --------------------------------------------------------------------------
def ficha_neutra():
    """Ficha **real** con ninguna de las 8 puertas disparada.

    Se parte de una ficha de verdad (no de un diccionario inventado) para que la
    forma no se pueda alejar de la que produce `Store.ficha()`, y se neutraliza
    un hecho a la vez. Cada prueba de puerta mueve exactamente uno.
    """
    f = copy.deepcopy(_ficha_base())
    f["nudges"]["opt_out"] = False
    f["decision"]["fecha_contaminada"] = False
    f["decision"]["motivo_fecha"] = None
    f["decision"]["es_fragil"] = False
    f["decision"]["motivo_fragilidad"] = []
    f["perfil"]["solo_modelo"]["es_fragil"] = False
    f["perfil"]["situacion_financiera"]["utilizacion_tarjeta_pct"] = 30.0
    f["perfil"]["situacion_financiera"]["dias_en_negativo_90d"] = 0
    for p in TODOS_LOS_PRODUCTOS:
        f["nudges"]["por_tipo"][p].update({
            "exposiciones": 0, "exposure_no_max": 0, "n_enganchados": 0,
            "n_descartados": 0, "ultimo_ts": None, "cupo_restante": 2})
        f["decision"]["senales_por_nudge"][p].update({
            "momento": "on_time", "horas_desde_senal": 3.0,
            "exposure_no_siguiente": 1, "cupo_agotado": False, "n_descartados": 0})
    return f


def scores_sanos(valor=0.11):
    """Scores por encima del umbral de confianza: S7 no cierra por accidente."""
    return {p: {"score": valor, "p_intencion": 0.4, "p_enganche": 0.28,
                "V": 0.7, "confianza": 0.28, "explicacion": "prueba"}
            for p in CATALOGO_DEMO}


def artefactos(tv=None, **extra):
    d = {"tabla_valor": tv if tv is not None else tabla_valor(),
         "umbrales": {}, "lambda": 266.0, "modelo": "prueba",
         "cobertura": {"pct_silencio": 86.0, "pct_oferta": 14.0}}
    d.update(extra)
    return d


def decidir(ficha, tv=None, scores=None, fecha="2026-06-16T12:00:00", **extra):
    from pipeline import politica
    return politica.decide(ficha, fecha, scores or scores_sanos(),
                           artefactos(tv, **extra))


# --------------------------------------------------------------------------
def traza_de(resp, codigo):
    return next(f for f in resp["traza"] if f["puerta"] == codigo)


def silencio_de(resp, producto):
    return next((s for s in resp["silencios"] if s["producto"] == producto), None)


def productos_ofertados(resp):
    return [o["producto"] for o in resp["ofertas"]]
