"""BA-4 · Canario de baselines. PUERTA DE CALIDAD.

Sin esto en verde nada de lo que sigue es confiable: si el label se construye
mal (ventana equivocada, `<=` en vez de `<`, activos mal definidos) los cuatro
baselines se mueven y todo lo demás mide otra cosa.

El baseline es un **predictor constante** elegido en entrenamiento
(`spei_out`), no "la clase mayoritaria de cada corte": en el corte d90 la
mayoritaria es `deposit_in` (26.83 %) y elegirla por corte sería usar el test
para decidir qué predecir.
"""
import pandas as pd
import pytest

from analytics.metricas import acc_baseline
from pipeline.features import labels_intencion

# corte -> (accuracy del predictor constante, clientes activos)
ESPERADO = {
    "2026-05-30": (25.63, 24268),   # d90
    "2026-06-09": (41.62, 18606),   # d100 · corte del modelo
    "2026-06-14": (33.64, 20701),   # d105
    "2026-05-23": (45.89, 16999),   # d83 · corte de umbrales
}
TOL = 0.05


@pytest.mark.parametrize("corte,esperado", [(k, v[0]) for k, v in ESPERADO.items()])
def test_baseline_constante(con, corte, esperado):
    obtenido = acc_baseline(corte, con=con)
    assert abs(obtenido - esperado) < TOL, f"{corte}: {obtenido} != {esperado}"


@pytest.mark.parametrize("corte,activos", [(k, v[1]) for k, v in ESPERADO.items()])
def test_activos_por_corte(con, corte, activos):
    lab = labels_intencion(corte, con=con)
    assert int(lab.activo.sum()) == activos


def test_el_baseline_no_es_la_mayoritaria_de_cada_corte(con):
    """En d90 la mayoritaria es deposit_in: el predictor constante pierde ahí.

    Si alguien "arregla" el baseline eligiendo la mayoritaria por corte, esta
    prueba lo detecta: estaría usando el test para decidir qué predecir.
    """
    lab = labels_intencion("2026-05-30", con=con)
    act = lab[lab.activo == 1]
    vc = act.y_primera.value_counts(normalize=True) * 100
    assert vc.index[0] == "deposit_in"
    assert round(vc.iloc[0], 2) == 26.83
    assert acc_baseline("2026-05-30", con=con) < vc.iloc[0]


def test_ventana_de_label_recorta_los_bordes(con):
    """Los 3 primeros y los 3 últimos días quedan fuera: el día 1 trae 7.36x la
    mediana de acciones (artefacto del generador) y el final está censurado."""
    with pytest.raises(ValueError):
        labels_intencion("2026-03-01", con=con)     # borde inicial
    with pytest.raises(ValueError):
        labels_intencion("2026-06-20", con=con)     # ventana censurada al final


def test_label_es_estrictamente_posterior_al_corte(con):
    """Ninguna acción de la ventana puede ocurrir en el corte o antes."""
    corte = "2026-06-09"
    n = con.execute(
        f"""SELECT count(*) FROM financial_actions
            WHERE action_ts > TIMESTAMP '{corte}'
              AND action_ts <= TIMESTAMP '{corte}' + INTERVAL 7 DAY"""
    ).fetchone()[0]
    lab = labels_intencion(corte, con=con)
    total = con.execute(
        f"""SELECT count(*) FROM (
              SELECT customer_id, action_type FROM financial_actions
              WHERE action_ts > TIMESTAMP '{corte}'
                AND action_ts <= TIMESTAMP '{corte}' + INTERVAL 7 DAY
              GROUP BY 1,2)"""
    ).fetchone()[0]
    marcados = int(lab[[c for c in lab.columns if c.startswith("y_") and c != "y_primera"]].sum().sum())
    assert marcados == total, f"{marcados} pares marcados vs {total} observados"
    assert n > 0
