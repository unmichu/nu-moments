"""Fixtures compartidas.

El Store se carga una sola vez por sesión (~1.1 s). La ficha que reciben las
pruebas de puertas viene **neutralizada**: ninguna puerta se dispara, así que
cada prueba mueve un solo hecho y el cierre no se puede atribuir a otra cosa.
"""
from __future__ import annotations

import copy
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from pipeline.ingesta import Store                                    # noqa: E402
from pipeline.mapas import CATALOGO_DEMO, CORTE_DEMO, LAMBDA_DEFECTO, TODOS_LOS_PRODUCTOS  # noqa: E402

ASOF = f"{CORTE_DEMO}T12:00:00"
CLIENTE_BASE = 6024615          # `ahorro_fresco` de los escenarios curados


def ficha_neutra(base):
    """Una ficha que NO dispara ninguna puerta: todo pasa.

    Señal fresca en las 4 pantallas del catálogo, cupo libre, sin descartes,
    sin opt-out, fecha limpia y cliente sano.
    """
    f = copy.deepcopy(base)
    f["nudges"]["opt_out"] = False
    f["decision"]["fecha_contaminada"] = False
    f["decision"]["motivo_fecha"] = None
    f["decision"]["es_fragil"] = False
    f["decision"]["motivo_fragilidad"] = []
    f["perfil"]["solo_modelo"]["es_fragil"] = False
    f["perfil"]["situacion_financiera"]["utilizacion_tarjeta_pct"] = 30.0
    f["perfil"]["situacion_financiera"]["dias_en_negativo_90d"] = 0
    for p in TODOS_LOS_PRODUCTOS:
        f["nudges"]["por_tipo"][p] = {
            "exposiciones": 0, "exposure_no_max": 0, "n_enganchados": 0,
            "n_descartados": 0, "ultimo_ts": None, "cupo_restante": 2,
        }
        s = f["decision"]["senales_por_nudge"][p]
        s["momento"] = "on_time"
        s["horas_desde_senal"] = 3.0
        s["hubo_start_24h"] = True
        s["exposure_no_siguiente"] = 1
        s["cupo_agotado"] = False
        s["n_descartados"] = 0
    return f


def scores_altos(valor=0.5):
    return {p: {"score": valor, "p_intencion": 0.6, "p_enganche": 0.5,
                "V": 0.7, "confianza": 0.3} for p in CATALOGO_DEMO}


# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def store():
    return Store.cargar(os.path.join(RAIZ, "data"), evidencias=False)


@pytest.fixture(scope="session")
def tabla_valor(store):
    return store.tabla_valor()


@pytest.fixture(scope="session")
def cliente(store):
    """Un cliente real del demo, tal cual sale del Store."""
    return store.ficha(CLIENTE_BASE, ASOF)


@pytest.fixture
def ficha_cruda(cliente):
    """La ficha real, sin neutralizar."""
    return copy.deepcopy(cliente)


@pytest.fixture
def ficha(cliente):
    """La ficha neutralizada: punto de partida de las pruebas de puertas."""
    return ficha_neutra(cliente)


@pytest.fixture
def scores():
    return scores_altos()


@pytest.fixture
def artefactos(tabla_valor):
    return {"tabla_valor": tabla_valor, "umbrales": {}, "lambda": LAMBDA_DEFECTO,
            "modelo": "test", "cobertura": None}
