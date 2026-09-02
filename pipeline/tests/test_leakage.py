"""ING-7 · Pruebas anti-fuga. **Evidencia, no higiene.**

El reto las pide por nombre. Cuatro afirmaciones y una demostración:

1. Ninguna feature usa eventos con `ts >= asof`.
2. Ninguna columna de la lista negra entra en la matriz.
3. Ninguna columna que empiece por `customer_id`.
4. **Prueba negativa** — se inyecta un evento en `asof + 1 h` y NINGUNA feature
   se mueve. Con su control: el mismo evento en `asof − 1 h` **sí** mueve la
   matriz, que es lo que convierte el punto 4 en una prueba y no en un
   experimento que no puede fallar.
5. Barajado temporal: al romper la alineación entre la foto as-of y su futuro,
   el desempeño se cae al azar.

El corte es `ts < asof` **estricto**. Aquí se demuestra, no se afirma.
"""
from __future__ import annotations

import os
import shutil

import pandas as pd
import pytest

import comun
from pipeline import features
from pipeline.mapas import CORTE_DEMO, CORTE_MODELO

ASOF = CORTE_DEMO                      # las features se construyen por día
CLIENTE = comun.CLIENTE_AHORRO


@pytest.fixture(scope="module")
def matriz():
    """La matriz as-of del corte del demo, construida desde `data/`."""
    return features.construir(ASOF)


# ==========================================================================
# 1 · Ninguna feature usa eventos con ts >= asof
# ==========================================================================
def test_sin_eventos_futuros():
    """El corte del Store es estricto: nada con `ts >= asof` entra en la ficha."""
    asof = pd.Timestamp(f"{ASOF}T12:00:00")
    st = comun.store()
    eventos = st.eventos_de(CLIENTE, asof)
    assert len(eventos), "el cliente de prueba debería tener historial"
    assert eventos["ts"].max() < asof

    ficha = st.ficha(CLIENTE, asof)
    for e in ficha["linea_tiempo"]:
        assert pd.Timestamp(e["ts"]) < asof
    for m in ficha["movimientos"]["ultimos"]:
        assert pd.Timestamp(m["ts"]) < asof
    for n in ficha["nudges"]["ultimos"]:
        assert pd.Timestamp(n["ts"]) < asof


def test_las_recencias_nunca_son_negativas(matriz):
    """Una recencia negativa sería un evento del futuro contado como pasado."""
    recencias = [c for c in matriz.columns if c.startswith("rec_h_")]
    assert recencias, "la matriz debería traer columnas de recencia"
    for c in recencias:
        assert (matriz[c] >= 0).all(), f"{c} tiene valores negativos"


# ==========================================================================
# 2 · Columnas prohibidas
# ==========================================================================
def test_columnas_prohibidas(matriz):
    """Ninguna columna de la lista negra está en la matriz."""
    columnas = features.columnas_features(matriz)
    for c in columnas:
        for patron in features.PATRONES_PROHIBIDOS:
            assert patron not in c.lower(), f"feature prohibida por patrón {patron!r}: {c}"


def test_la_lista_negra_cubre_lo_posterior_a_la_decision():
    """Los resultados del aviso son posteriores a la decisión: nunca son entrada."""
    for patron in ("engaged", "dismissed", "opted_out", "delta_", "abandon"):
        assert patron in features.PATRONES_PROHIBIDOS


# ==========================================================================
# 3 · Identificadores
# ==========================================================================
def test_sin_columnas_id(matriz):
    """Ninguna columna que empiece por `customer_id` entra a los modelos."""
    columnas = features.columnas_features(matriz)
    assert not [c for c in columnas if c.startswith("customer_id")]
    assert "customer_id" in matriz.columns, "el identificador existe, pero fuera de la matriz"
    assert not matriz.customer_id.duplicated().any(), "el grano no es (customer_id, asof)"


# ==========================================================================
# 4 · La prueba negativa (y su control)
# ==========================================================================
def _datos_con_evento(tmp, cuando):
    """Copia `data/` a un directorio temporal y añade un evento en `cuando`.

    Se inyecta en las tres tablas con marca de tiempo —navegación, acción
    financiera y aviso— porque las tres alimentan features distintas y una fuga
    puede entrar por cualquiera de ellas.
    """
    destino = os.path.join(tmp, "data")
    os.makedirs(destino, exist_ok=True)
    for t in ("customers", "app_events", "financial_actions", "nudges", "nudge_outcomes"):
        shutil.copy(os.path.join(comun.RAIZ, "data", f"{t}.parquet"),
                    os.path.join(destino, f"{t}.parquet"))
    ts = pd.Timestamp(cuando)

    ev = pd.read_parquet(os.path.join(destino, "app_events.parquet"))
    ev = pd.concat([ev, pd.DataFrame([{
        "event_id": int(ev.event_id.max()) + 1, "customer_id": CLIENTE,
        "event_ts": ts, "screen": "savings_cajita", "action": "start"}])],
        ignore_index=True).astype(ev.dtypes.to_dict())
    ev.to_parquet(os.path.join(destino, "app_events.parquet"), index=False)

    fa = pd.read_parquet(os.path.join(destino, "financial_actions.parquet"))
    fa = pd.concat([fa, pd.DataFrame([{
        "action_id": int(fa.action_id.max()) + 1, "customer_id": CLIENTE,
        "action_ts": ts, "action_type": "savings_move", "amount_mxn": 9999.0,
        "is_recurring": False}])], ignore_index=True).astype(fa.dtypes.to_dict())
    fa.to_parquet(os.path.join(destino, "financial_actions.parquet"), index=False)

    nu = pd.read_parquet(os.path.join(destino, "nudges.parquet"))
    nu = pd.concat([nu, pd.DataFrame([{
        "nudge_id": int(nu.nudge_id.max()) + 1, "customer_id": CLIENTE,
        "shown_ts": ts, "nudge_type": "savings_goal", "surface": "in_app_modal",
        "exposure_no": 9, "hours_since_last_nudge": 1.0, "engaged": True,
        "dismissed": False, "opted_out_after": False}])],
        ignore_index=True).astype(nu.dtypes.to_dict())
    nu.to_parquet(os.path.join(destino, "nudges.parquet"), index=False)
    return destino


def test_negativo_evento_futuro(tmp_path, monkeypatch, matriz):
    """Se inyecta un evento en `asof + 1 h` y NINGUNA feature se mueve.

    La matriz as-of se construye al filo del día (`asof` = medianoche), así que
    `asof + 1 h` es la 01:00 de ese mismo día.
    """
    base = matriz.set_index("customer_id")
    destino = _datos_con_evento(str(tmp_path / "futuro"), f"{ASOF} 01:00:00")

    monkeypatch.setattr(features, "DATA", destino)
    con_futuro = features.construir(ASOF).set_index("customer_id")

    assert list(con_futuro.columns) == list(base.columns)
    pd.testing.assert_frame_equal(con_futuro, base)
    # y en particular, la fila del cliente al que se le inyectó el evento
    pd.testing.assert_series_equal(con_futuro.loc[CLIENTE], base.loc[CLIENTE])


def test_control_un_evento_anterior_al_corte_si_mueve_las_features(
        tmp_path, monkeypatch, matriz):
    """El control de la prueba negativa: sin esto, aquella no podría fallar."""
    base = matriz.set_index("customer_id")
    anterior = (pd.Timestamp(ASOF) - pd.Timedelta(hours=1)).isoformat(sep=" ")
    destino = _datos_con_evento(str(tmp_path / "pasado"), anterior)

    monkeypatch.setattr(features, "DATA", destino)
    con_pasado = features.construir(ASOF).set_index("customer_id")

    fila_base, fila_nueva = base.loc[CLIENTE], con_pasado.loc[CLIENTE]
    movidas = [c for c in base.columns if fila_base[c] != fila_nueva[c]]
    assert movidas, ("un evento ANTES del corte no movió ninguna feature: "
                     "la prueba negativa no estaría demostrando nada")


def test_la_ficha_tambien_ignora_el_futuro(tmp_path):
    """El mismo corte estricto, esta vez sobre el Store que sirve la demo."""
    from pipeline.ingesta import Store
    destino = _datos_con_evento(str(tmp_path / "ficha"), f"{ASOF} 13:00:00")
    st = Store.cargar(destino, evidencias=False)
    asof = pd.Timestamp(f"{ASOF}T12:00:00")

    ficha = st.ficha(CLIENTE, asof)
    base = comun.store().ficha(CLIENTE, asof)
    assert ficha["decision"]["senales_por_nudge"] == base["decision"]["senales_por_nudge"]
    assert ficha["nudges"]["por_tipo"] == base["nudges"]["por_tipo"]
    assert ficha["movimientos"]["agregado_30d"] == base["movimientos"]["agregado_30d"]


# ==========================================================================
# 5 · Barajado temporal
# ==========================================================================
def test_barajado_temporal_degrada():
    """Al romper la alineación foto as-of ↔ futuro, el modelo se cae al azar.

    Es el control negativo del diseño temporal completo: si con las etiquetas
    barajadas el AUC no bajara, la señal no vendría del orden de los hechos.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X = features.cargar(CORTE_MODELO).set_index("customer_id")
    etiquetas = features.labels_intencion(CORTE_MODELO).set_index("customer_id")
    y = etiquetas.loc[X.index, "y_savings_move"].astype(int)
    cols = features.columnas_features(X.reset_index())

    def auc(objetivo, semilla=0):
        Xtr, Xte, ytr, yte = train_test_split(
            X[cols], objetivo, test_size=0.3, random_state=semilla, stratify=objetivo)
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=400))
        m.fit(Xtr, ytr)
        return roc_auc_score(yte, m.predict_proba(Xte)[:, 1])

    real = auc(y)
    barajado = auc(pd.Series(np.random.RandomState(0).permutation(y.to_numpy()),
                             index=y.index))

    assert real > 0.60, f"sin señal temporal que degradar (AUC real {real:.4f})"
    assert barajado < real - 0.05, (
        f"barajar el tiempo no degradó nada: real {real:.4f} vs barajado {barajado:.4f}")
    assert 0.45 < barajado < 0.55, f"el barajado debería quedar en el azar: {barajado:.4f}"
