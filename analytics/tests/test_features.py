"""BA-2 · La matriz de features: forma, lista negra e integridad de uniones."""
import pandas as pd
import pytest

from pipeline.features import (
    PATRONES_PROHIBIDOS,
    columnas_features,
    construir,
    ruta_features,
)
from pipeline.mapas import ACCIONES, CATALOGO_DEMO, CORTE_DEMO, CORTE_MODELO, PANTALLAS

CORTES = [CORTE_DEMO, CORTE_MODELO]


@pytest.fixture(scope="module")
def demo(con):
    return construir(CORTE_DEMO, con=con)


def test_82_columnas_de_features(demo):
    assert len(columnas_features(demo)) == 82


def test_ninguna_columna_customer_id_en_la_matriz(demo):
    """`LEFT JOIN ... USING` mete `customer_id_2`. Un modelo llegó a usarla con peso 0.070."""
    feats = columnas_features(demo)
    assert not [c for c in feats if "customer_id" in c]
    assert "customer_id_2" not in demo.columns
    assert [c for c in demo.columns if c.startswith("customer_id")] == ["customer_id"]


def test_lista_negra_de_features(demo):
    for c in columnas_features(demo):
        for pat in PATRONES_PROHIBIDOS:
            assert pat not in c.lower(), f"{c} contiene el patrón prohibido {pat}"


def test_bloques_de_features_completos(demo):
    cols = set(demo.columns)
    assert all(f"rec_h_{s}" in cols for s in PANTALLAS)
    assert all(f"n24_{s}" in cols and f"n72_{s}" in cols for s in PANTALLAS)
    assert all(f"senal_{a}" in cols for a in ACCIONES)
    assert all(f"exp_{p}" in cols for p in CATALOGO_DEMO)
    assert "dias_a_payday" in cols


def test_grano_y_sin_nulos(demo):
    assert len(demo) == 38000
    assert not demo.customer_id.duplicated().any()
    assert not demo.isna().any().any()


def test_senal_solo_toma_los_cuatro_estados(demo):
    for a in ACCIONES:
        assert set(demo[f"senal_{a}"].unique()) <= {0, 1, 2, 3}


@pytest.mark.parametrize("corte", CORTES)
def test_el_parquet_del_contrato_existe(corte):
    """Los nombres de `docs/arquitectura.md` son ley: otra área los consume."""
    import os
    assert os.path.exists(ruta_features(corte)), ruta_features(corte)
    df = pd.read_parquet(ruta_features(corte))
    assert len(columnas_features(df)) == 82


def test_integridad_de_uniones_cero_huerfanos(con):
    for tabla in ("app_events", "financial_actions", "nudges"):
        n = con.execute(
            f"""SELECT count(*) FROM {tabla} t
                LEFT JOIN customers c ON c.customer_id = t.customer_id
                WHERE c.customer_id IS NULL"""
        ).fetchone()[0]
        assert n == 0, f"{tabla}: {n} huérfanos"
    for a, b, k in (("nudge_outcomes", "nudges", "nudge_id"), ("nudges", "nudge_outcomes", "nudge_id")):
        n = con.execute(
            f"SELECT count(*) FROM {a} x LEFT JOIN {b} y ON y.{k} = x.{k} WHERE y.{k} IS NULL"
        ).fetchone()[0]
        assert n == 0, f"{a} sin par en {b}: {n}"


def test_recencia_coincide_con_el_maximo_evento_anterior(con, demo):
    """Comprobación directa del corte estricto sobre un cliente concreto."""
    cid = int(demo.customer_id.iloc[0])
    esperado = con.execute(
        f"""SELECT date_diff('second', max(event_ts), TIMESTAMP '{CORTE_DEMO}') / 3600.0
            FROM app_events
            WHERE customer_id = {cid} AND screen = 'home' AND event_ts < TIMESTAMP '{CORTE_DEMO}'"""
    ).fetchone()[0]
    obtenido = float(demo.set_index("customer_id").loc[cid, "rec_h_home"])
    assert abs(obtenido - float(esperado)) < 0.01
