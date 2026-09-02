"""Orden temporal: se prueba, no se promete.

Tres pruebas, en este orden:
  1. NEGATIVA  — se inyecta un evento en `asof + 1h`: ninguna feature se mueve.
  2. POSITIVA  — el mismo evento en `asof − 2h`: alguna feature SÍ se mueve.
     Sin esta, la negativa solo demostraría que el pipeline ignora la tabla.
  3. Ninguna consulta de features usa `<=` sobre el corte.
"""
import inspect
import re

import pandas as pd

from analytics.calidad import _conexion_con_evento_futuro
from pipeline import features as feat
from pipeline.features import columnas_features, construir
from pipeline.mapas import CORTE_DEMO

PANTALLA = "savings_cajita"


def _base(con):
    return construir(CORTE_DEMO, con=con).set_index("customer_id")


def test_evento_futuro_no_mueve_ninguna_feature(con):
    base = _base(con)
    cid = int(base.index[0])
    c2 = _conexion_con_evento_futuro(CORTE_DEMO, cid, PANTALLA)
    try:
        fut = construir(CORTE_DEMO, con=c2).set_index("customer_id")
    finally:
        c2.close()
    movidas = {c: int((base[c].to_numpy() != fut[c].to_numpy()).sum())
               for c in columnas_features(base.reset_index())}
    assert not {k: v for k, v in movidas.items() if v}, \
        f"fuga: {[k for k, v in movidas.items() if v]}"


def test_evento_pasado_si_mueve_features(con):
    base = _base(con)
    cid = int(base.index[0])
    antes = str(pd.Timestamp(CORTE_DEMO) - pd.Timedelta(hours=2))
    c3 = _conexion_con_evento_futuro(antes, cid, PANTALLA)
    try:
        pas = construir(CORTE_DEMO, con=c3).set_index("customer_id")
    finally:
        c3.close()
    movidas = sum(int((base[c].to_numpy() != pas[c].to_numpy()).sum())
                  for c in columnas_features(base.reset_index()))
    assert movidas > 0, "el pipeline no ve ni el pasado: la prueba negativa no vale nada"


def test_todas_las_comparaciones_con_el_corte_son_estrictas():
    """Del lado de las features el corte es `< asof`, siempre.

    `action_ts <= fin` sí es correcto y NO cuenta aquí: es el cierre de la
    ventana de label, que es semiabierta `(asof, asof+7d]`. Lo que no puede
    existir es un `event_ts <=` o un `shown_ts <=` contra el corte.
    """
    src = inspect.getsource(feat)
    malas = re.findall(r"(event_ts|shown_ts)\s*<=\s*TIMESTAMP", src)
    assert not malas, f"comparación no estricta contra el corte: {malas}"
    # la ventana de label abre en estricto y cierra en inclusivo
    assert "action_ts >  TIMESTAMP" in src or "action_ts > TIMESTAMP" in src
    assert "action_ts <= TIMESTAMP" in src


def test_el_label_no_entra_en_las_features(con):
    """Ninguna columna de resultado ni de target aparece en la matriz."""
    df = construir(CORTE_DEMO, con=con)
    prohibidas = {
        "engaged", "dismissed", "opted_out_after", "engagement_score",
        "delta_card_utilization_pct_90d", "delta_savings_rate_pct_90d",
        "delta_days_negative_90d", "delta_revenue_mxn_90d",
        "days_negative_90d", "savings_rate_90d_pct", "hours_since_last_nudge",
    }
    assert not (prohibidas & set(df.columns))
