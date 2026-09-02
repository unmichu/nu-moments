#!/usr/bin/env python3
"""Evaluación de los tres modelos contra TRES baselines, no uno.

    M0a · predictor constante   `spei_out`, elegido en entrenamiento
    M0b · regla de 24 h         la última pantalla accionable vista
    M1  · el modelo             HistGradientBoosting, 8 cabezas

Por qué la matriz NO lleva las columnas financieras de `customers`
-----------------------------------------------------------------
`tenure_months`, `age` y demás demográficos serían admisibles, pero
`days_negative_90d`, `savings_rate_90d_pct`, `card_utilization_pct`,
`avg_balance_mxn` y `revenue_ltm_mxn` **no entran**, y es una decisión, no un
olvido (`analytics/recon/out/06_leakage_table.csv` las marca una a una):

* El sufijo `_90d` declara una ventana de 90 días **sin fecha de corte**. Sea
  cual sea el `asof` que elijamos dentro de estos 120 días de datos, esa ventana
  lo solapa: el valor incluye días posteriores al corte. Es fuga por diseño.
* `card_utilization_pct`, `avg_balance_mxn` y `revenue_ltm_mxn` son *snapshots*
  sin vintage declarado: no se sabe a qué fecha corresponden, así que no se
  pueden reconstruir as-of y el modelo no sería reproducible.
* `engagement_score` queda fuera aparte: genera el volumen de eventos **y** el
  de avisos, o sea que es casi el label.

Las 82 columnas se calculan todas desde `app_events` y `nudges` con
`event_ts < asof` estricto, que sí tienen marca de tiempo por fila. Cuesta algo
de exactitud y compra reproducibilidad; ante un jurado, esa es la respuesta.

Lo primero que hay que decir, y se dice aquí arriba: **en el corte principal el
árbol empata con la regla** donde hay señal. La ganancia no es exactitud, es
estabilidad — el rango entre cortes del árbol es mucho menor que el de la
regla aplicada a toda la base. Esconderlo y que lo pregunten en el pitch es peor.

Uso: .venv/bin/python analytics/evaluar.py
"""
from __future__ import annotations

import json
import os
import sys

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.entrenar import VARS_MOMENTO, p_enganche, puntuar_intencion  # noqa: E402
from pipeline.features import (  # noqa: E402
    ACCION_A_PANTALLA,
    ARTIFACTS,
    _conexion,
    cargar,
    labels_intencion,
    labels_momento,
)
from pipeline.mapas import ACCIONES, CORTE_DEMO, CORTE_MODELO, CORTES_ROLLING  # noqa: E402

CLASE_BASELINE = "spei_out"
LOOKBACK_H = 24


def _cargar_modelos():
    mx = joblib.load(os.path.join(ARTIFACTS, "modelo_intencion.pkl"))
    my = joblib.load(os.path.join(ARTIFACTS, "modelo_momento.pkl"))
    with open(os.path.join(ARTIFACTS, "umbrales.json"), encoding="utf-8") as fh:
        um = json.load(fh)
    return mx, my, um


def regla_24h(X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Predicción de la regla y máscara de 'hay señal'."""
    rec = X[[f"rec_h_{ACCION_A_PANTALLA[a]}" for a in ACCIONES]].to_numpy()
    hay = rec.min(axis=1) <= LOOKBACK_H
    pred = np.array(ACCIONES)[rec.argmin(axis=1)]
    return pred, hay


def evaluar_intencion(mx: dict, cortes: list[str], con) -> pd.DataFrame:
    lbl = np.array(mx["acciones"])
    filas = []
    for c in cortes:
        X = cargar(c).set_index("customer_id")
        y = labels_intencion(c, con=con).set_index("customer_id").reindex(X.index)
        act = y.activo.to_numpy() == 1
        verdad = y.y_primera.to_numpy()

        P = puntuar_intencion(mx, X, "arbol")
        pred = lbl[P.argmax(axis=1)]
        orden = np.argsort(-P, axis=1)[:, :2]
        top2 = np.array([verdad[i] in lbl[orden[i]] for i in range(len(X))])

        r_pred, hay = regla_24h(X)
        hibrida = np.where(hay, r_pred, CLASE_BASELINE)
        m = act & hay

        # precisión en el tramo superior: decil más alto de p_max
        thr = np.quantile(P.max(axis=1), 0.90)
        alto = act & (P.max(axis=1) >= thr)

        filas.append(dict(
            corte=c, activos=int(act.sum()), pct_con_senal=round(100 * float(hay[act].mean()), 1),
            baseline_constante=round(100 * float((verdad[act] == CLASE_BASELINE).mean()), 2),
            regla_hibrida=round(100 * float((hibrida[act] == verdad[act]).mean()), 2),
            modelo_top1=round(100 * float((pred[act] == verdad[act]).mean()), 2),
            modelo_top2=round(100 * float(top2[act].mean()), 2),
            regla_donde_senal=round(100 * float((r_pred[m] == verdad[m]).mean()), 2),
            modelo_donde_senal=round(100 * float((pred[m] == verdad[m]).mean()), 2),
            modelo_decil_superior=round(100 * float((pred[alto] == verdad[alto]).mean()), 2),
        ))
    return pd.DataFrame(filas)


def evaluar_momento(my: dict, con) -> dict:
    lm = labels_momento(con=con)
    te = lm[lm.shown_ts > pd.Timestamp(my["corte_entrenamiento"])]
    p = p_enganche(my, te.senal, te.exposure_no)
    y = te.y_engaged.to_numpy()
    from sklearn.metrics import roc_auc_score
    k = int(round(0.01 * len(y)))
    thr = np.sort(p)[::-1][k - 1]
    top = p >= thr
    return {"n_test": int(len(te)), "auc": round(float(roc_auc_score(y, p)), 4),
            "precision_top1pct": round(100 * float(y[top].mean()), 2),
            "n_top1pct": int(top.sum()),
            "base_pct": round(100 * float(y.mean()), 2),
            "coeficientes": my["coeficientes"]}


def acuerdo_motores(mx: dict, cortes: list[str], con) -> pd.DataFrame:
    lbl = np.array(mx["acciones"])
    filas = []
    for c in cortes:
        X = cargar(c).set_index("customer_id")
        y = labels_intencion(c, con=con).set_index("customer_id").reindex(X.index)
        act = y.activo.to_numpy() == 1
        a = lbl[puntuar_intencion(mx, X, "arbol").argmax(axis=1)]
        r = lbl[puntuar_intencion(mx, X, "regresion").argmax(axis=1)]
        filas.append(dict(corte=c,
                          acuerdo_total_pct=round(100 * float((a == r).mean()), 2),
                          acuerdo_activos_pct=round(100 * float((a[act] == r[act]).mean()), 2)))
    return pd.DataFrame(filas)


def main() -> int:
    con = _conexion()
    try:
        mx, my, um = _cargar_modelos()
        cortes = list(CORTES_ROLLING)

        print("=" * 100)
        print("MODELO X · INTENCIÓN — top-1 / top-2 contra TRES baselines")
        ultimo = pd.Timestamp(max(mx["cortes_entrenamiento"]))
        fin_label = ultimo + pd.Timedelta(days=7)
        print(f"entrenado en {len(mx['cortes_entrenamiento'])} cortes "
              f"({mx['cortes_entrenamiento'][0]} → {mx['cortes_entrenamiento'][-1]}), "
              f"{mx['filas_entrenamiento']:,} filas")
        print(f"SIN FUGA: las ventanas de label del panel acaban el {fin_label.date()}, "
              f"antes del primer corte de test ({min(cortes)}).")
        print("      82 features, todas as-of desde app_events/nudges. Las columnas *_90d y los")
        print("      snapshots sin vintage de customers quedan EXCLUIDOS (ver docstring).")
        print("=" * 100)
        d = evaluar_intencion(mx, cortes, con)
        print(d.to_string(index=False))

        print("\n  medias y rango entre cortes:")
        # `esperado` = el valor medido por este mismo código, como prueba de
        # regresión. La fase de diseño publicó 43.75 / 2.61 pp antes de que
        # existiera el panel de 12 cortes; el medido con el panel es 43.80 / 2.65.
        for c, esp in (("baseline_constante", 33.63), ("modelo_top1", 43.80),
                       ("modelo_top2", None), ("regla_hibrida", None),
                       ("regla_donde_senal", None), ("modelo_donde_senal", None)):
            v = d[c]
            extra = f"   esperado {esp}" if esp is not None else ""
            print(f"    {c:22s} media {v.mean():6.2f}   rango {v.max() - v.min():5.2f} pp{extra}")

        print("\n  LO PRIMERO: en el corte principal ("
              f"{CORTE_MODELO}) el árbol "
              f"{'EMPATA' if abs(d.loc[d.corte == CORTE_MODELO, 'modelo_donde_senal'].iloc[0] - d.loc[d.corte == CORTE_MODELO, 'regla_donde_senal'].iloc[0]) < 2 else 'se separa de'}"
              " la regla de 24 h donde hay señal:")
        r = d[d.corte == CORTE_MODELO].iloc[0]
        print(f"    regla {r.regla_donde_senal} %  ·  árbol {r.modelo_donde_senal} %")
        print("  La ganancia es ESTABILIDAD: el rango entre cortes del árbol sobre toda la base es "
              f"{d.modelo_top1.max() - d.modelo_top1.min():.2f} pp contra "
              f"{d.regla_hibrida.max() - d.regla_hibrida.min():.2f} pp de la regla,")
        print("  y la regla solo cubre ~16 % de los activos: fuera de ahí no dice nada.")

        print("\n" + "=" * 100)
        print("ACUERDO ÁRBOL / REGRESIÓN (el árbol puntúa, la regresión explica)")
        print("=" * 100)
        print(acuerdo_motores(mx, cortes + [CORTE_DEMO], con).to_string(index=False))
        print("  Donde no coinciden, la respuesta lleva marca y la explicación cae a regla.")

        print("\n" + "=" * 100)
        print("MODELO Y · MOMENTO")
        print("=" * 100)
        m = evaluar_momento(my, con)
        print(f"  test: {m['n_test']:,} avisos posteriores a {my['corte_entrenamiento']}")
        print(f"  AUC                       {m['auc']:.4f}   objetivo 0.7107")
        print(f"  precisión 1 % superior    {m['precision_top1pct']:.2f} %   objetivo 33.02 % "
              f"(n={m['n_top1pct']:,}, empates incluidos)")
        print(f"  tasa base                 {m['base_pct']:.2f} %   objetivo 8.27 %")
        print(f"  coeficientes (escalados)  {m['coeficientes']}")

        print("\n" + "=" * 100)
        print("MODELO Z · VALOR")
        print("=" * 100)
        with open(os.path.join(ARTIFACTS, "tabla_valor.json"), encoding="utf-8") as fh:
            tv = json.load(fh)
        t = pd.DataFrame(tv["productos"]).T
        print(t[["delta_dias_negativos", "delta_ingreso_mxn", "delta_ahorro_pp",
                 "V_lambda_266", "V_lambda_165", "en_catalogo"]].to_string())
        print(f"  {tv['formula']}")
        print(f"  comprobación: V(ahorro,266)={tv['productos']['savings_goal']['V_lambda_266']:+.3f} "
              f"(esperado +0.700)   V(línea,266)={tv['productos']['limit_increase']['V_lambda_266']:+.3f} "
              "(esperado −0.077)")

        print("\n" + "=" * 100)
        print("UMBRALES (elegidos en el corte de umbrales, nunca en test)")
        print("=" * 100)
        print(f"  corte de selección     {um['corte_seleccion']}")
        print(f"  p_intencion_min        {um['p_intencion_min']}  "
              f"(precisión {um['p_intencion_precision_pct']} %, cobertura {um['p_intencion_cobertura_pct']} %)")
        print(f"  p_enganche_min         {um['p_enganche_min']}  (base {um['p_enganche_base_pct']} %)")
        print(f"  v_min                  {um['v_min']}   cap {um['cap_exposiciones']}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
