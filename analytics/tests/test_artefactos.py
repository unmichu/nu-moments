"""Contrato de artefactos: nombres exactos, corte declarado y modelos cargables.

`metadata.json` con el corte equivocado hace que el backend caiga al fallback
EN SILENCIO. Es el fallo más caro del proyecto, así que tiene su propia prueba.
"""
import json
import os

import joblib
import numpy as np
import pandas as pd
import pytest

from pipeline.features import ARTIFACTS, cargar
from pipeline.mapas import ACCIONES, CATALOGO_DEMO, CORTE_DEMO, CORTE_UMBRALES

CONTRATO = [
    "modelo_intencion.pkl",
    "modelo_momento.pkl",
    "umbrales.json",
    "tabla_valor.json",
    "razones.json",
    "metadata.json",
    f"features_asof_{CORTE_DEMO}.parquet",
]


@pytest.mark.parametrize("nombre", CONTRATO)
def test_artefacto_existe_con_el_nombre_exacto(nombre):
    p = os.path.join(ARTIFACTS, nombre)
    assert os.path.exists(p), f"falta {p} (docs/arquitectura.md)"
    assert os.path.getsize(p) > 0


def _meta():
    with open(os.path.join(ARTIFACTS, "metadata.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_metadata_declara_el_corte_del_demo():
    """Si no coincide, el backend cae al fallback y no avisa."""
    assert _meta()["corte"] == "2026-06-16" == CORTE_DEMO


def test_metadata_apunta_a_un_parquet_que_existe():
    m = _meta()
    assert os.path.exists(os.path.join(ARTIFACTS, m["features_parquet"]))
    assert m["n_features"] == 82
    assert len(m["features"]) == 82
    assert m["catalogo"] == list(CATALOGO_DEMO)


def test_modelo_intencion_puntua_y_explica():
    mx = joblib.load(os.path.join(ARTIFACTS, "modelo_intencion.pkl"))
    assert mx["acciones"] == list(ACCIONES)
    assert len(mx["features"]) == 82
    assert not any(c.startswith("customer_id") for c in mx["features"])
    X = cargar(CORTE_DEMO).set_index("customer_id").head(50)
    for a in ACCIONES:
        assert mx["arbol"][a].get_params()["max_depth"] == 4
        assert mx["arbol"][a].get_params()["random_state"] == 0
        p = mx["arbol"][a].predict_proba(X[mx["features"]])[:, 1]
        assert p.shape == (50,) and np.isfinite(p).all()
        # la regresión explica: coeficientes por feature, no una caja negra
        assert len(mx["coeficientes"][a]) == 82


def test_modelo_intencion_sin_class_weight_balanced():
    """Medido: `class_weight='balanced'` cuesta 10.07 pp."""
    mx = joblib.load(os.path.join(ARTIFACTS, "modelo_intencion.pkl"))
    for a in ACCIONES:
        lr = mx["regresion"][a].named_steps["logisticregression"]
        assert lr.class_weight is None


def test_modelo_momento_es_regresion_escalada_de_dos_variables():
    my = joblib.load(os.path.join(ARTIFACTS, "modelo_momento.pkl"))
    assert my["variables"] == ["senal", "exposure_no"]
    pasos = list(my["pipeline"].named_steps)
    assert pasos == ["standardscaler", "logisticregression"], pasos
    p = my["pipeline"].predict_proba(pd.DataFrame({"senal": [0, 3], "exposure_no": [1, 6]}))[:, 1]
    assert p[0] > p[1], "señal fresca y primera exposición deben enganchar más"


def test_tabla_valor_cumple_la_comprobacion_del_contrato():
    with open(os.path.join(ARTIFACTS, "tabla_valor.json"), encoding="utf-8") as fh:
        tv = json.load(fh)
    assert abs(tv["productos"]["savings_goal"]["V_lambda_266"] - 0.700) < 0.005
    assert abs(tv["productos"]["limit_increase"]["V_lambda_266"] - (-0.077)) < 0.005
    assert tv["lambda_defecto"] == 266.0


def test_umbrales_elegidos_en_el_corte_de_umbrales():
    with open(os.path.join(ARTIFACTS, "umbrales.json"), encoding="utf-8") as fh:
        um = json.load(fh)
    assert um["corte_seleccion"] == CORTE_UMBRALES
    assert um["corte_seleccion"] != CORTE_DEMO
    assert 0.0 < um["p_intencion_min"] < 1.0
    assert 0.0 < um["p_enganche_min"] < 1.0
    assert um["cap_exposiciones"] == 2


def test_razones_cubre_el_catalogo_y_los_silencios():
    with open(os.path.join(ARTIFACTS, "razones.json"), encoding="utf-8") as fh:
        rz = json.load(fh)
    assert set(rz["oferta"]) == set(CATALOGO_DEMO)
    for motivo in ("sin_senal", "cupo_agotado", "veto_fragilidad", "opt_out"):
        assert rz["silencio"][motivo]


# ---------------------------------------------------------------------------
# Nivel 3 · demo_pack.json  (esquema de app/scoring.py)
# ---------------------------------------------------------------------------
def _pack():
    with open(os.path.join(ARTIFACTS, "demo_pack.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_demo_pack_respeta_el_esquema_del_backend():
    p = _pack()
    assert p["corte"] == CORTE_DEMO
    for k in ("pct_silencio", "pct_oferta", "n_silencio", "n_oferta"):
        assert k in p["cobertura"]
    assert p["cobertura"]["n_silencio"] + p["cobertura"]["n_oferta"] == 38000
    assert abs(p["cobertura"]["pct_oferta"] - 14.0) <= 0.1
    assert isinstance(p["clientes"], dict) and p["clientes"]
    for k in p["clientes"]:
        assert isinstance(k, str) and k.isdigit(), f"clave no string: {k!r}"
    una = next(iter(p["clientes"].values()))
    assert set(una["scores"]) == set(CATALOGO_DEMO)


def test_demo_pack_trae_los_9_casos_del_pitch():
    p = _pack()
    casos = json.load(open(
        os.path.join(ARTIFACTS, "casos_ejemplo.json"),
        encoding="utf-8"))["casos"]
    assert len(casos) == 9
    for c in casos:
        assert str(c["customer_id"]) in p["clientes"], c["clave"]


def test_el_nivel_3_dice_lo_mismo_que_el_nivel_1():
    """Si el fallback divergiera del modelo, mentiría y nadie lo notaría."""
    from analytics.entrenar import _ficha_minima
    from app.scoring import ModeloEntrenado, _leer_json, _normalizar_tabla_valor

    p = _pack()
    n1 = ModeloEntrenado.cargar(corte=CORTE_DEMO)
    tabla = _normalizar_tabla_valor(_leer_json("tabla_valor"), 266.0)
    feats = cargar(CORTE_DEMO).set_index("customer_id")
    for cid in list(p["clientes"])[:25]:
        vivo = n1.scores(_ficha_minima(int(cid), feats.loc[int(cid)]), tabla)
        guardado = p["clientes"][cid]["scores"]
        for prod in CATALOGO_DEMO:
            for campo in ("p_intencion", "p_enganche", "score", "confianza"):
                assert guardado[prod][campo] == vivo[prod][campo], (cid, prod, campo)


def test_razones_marca_el_origen_de_la_explicacion():
    with open(os.path.join(ARTIFACTS, "razones.json"), encoding="utf-8") as fh:
        rz = json.load(fh)
    assert set(rz["origen"]) == {"modelo", "regla", "paquete"}
    assert rz["origen"]["regla"]["marca"] and rz["origen"]["paquete"]["marca"]
    assert rz["origen"]["modelo"]["marca"] is None


def test_las_ventanas_de_label_del_panel_acaban_antes_del_primer_corte_de_test():
    """La frase que cierra cualquier pregunta sobre fuga."""
    import pandas as pd

    from pipeline.features import VENTANA_LABEL_D
    from pipeline.mapas import CORTES_ROLLING

    m = _meta()
    ultimo = pd.Timestamp(max(m["cortes_entrenamiento"]))
    fin_label = ultimo + pd.Timedelta(days=VENTANA_LABEL_D)
    primer_test = pd.Timestamp(min(CORTES_ROLLING))
    assert fin_label == pd.Timestamp("2026-05-27"), fin_label
    assert fin_label < primer_test, f"{fin_label} no es anterior a {primer_test}"
