#!/usr/bin/env python3
"""BA-5 · Entrenamiento y serialización de los tres modelos.

    X · Intención  8 cabezas binarias: HistGradientBoosting puntúa, LogisticRegression explica
    Y · Momento    LogisticRegression escalada, 2 variables (señal, exposición)
    Z · Valor      aritmética determinista, no es aprendizaje automático

Decisiones medidas, no opinables
--------------------------------
* Sin `class_weight='balanced'`: cuesta 10.07 pp.
* `StandardScaler` obligatorio antes de la regresión, o no converge.
* El árbol puntúa, la regresión explica. Cuando discrepan, la respuesta lleva marca.
* Momento: regresión con 2 variables. El árbol aporta +0.0011 de AUC: no se usa.
* Umbrales elegidos en el corte de umbrales (2026-05-23), nunca en test.

Diseño temporal (sin fuga, comprobable)
--------------------------------------
    entrenamiento X   12 cortes semanales  2026-03-04 → 2026-05-20
                      (sus ventanas de label acaban el 2026-05-27)
    umbrales          2026-05-23
    test              2026-05-30 · 2026-06-09 · 2026-06-14   (todos posteriores)
    demo              2026-06-16   ← el corte que declara metadata.json

El panel de cortes no es un capricho: entrenando en UN solo corte,
`dias_a_payday` toma solo 3 valores (el día del mes es constante) y el modelo
no puede aprender el efecto de la quincena. Con el panel, el top-1 medio pasa
de 38.45 % a 43.80 % y el rango entre cortes de 16.26 pp a 2.66 pp.

Fases
-----
    --v0   entrena en un único corte. Segundos. Mismos nombres de archivo.
    (por defecto) v1, el panel completo. El backend no cambia una línea.

Uso: .venv/bin/python analytics/entrenar.py [--v0]
     .venv/bin/python analytics/entrenar.py --solo-demo-pack   # solo el nivel 3
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.metricas import cobertura, motivo_por_cliente  # noqa: E402
from pipeline.features import (  # noqa: E402
    ARTIFACTS,
    columnas_features,
    construir,
    labels_intencion,
    labels_momento,
    _conexion,
)
from pipeline.mapas import (  # noqa: E402
    ACCIONES,
    CAP_EXPOSICIONES,
    CATALOGO_DEMO,
    CORTE_DEMO,
    CORTE_MODELO,
    CORTE_UMBRALES,
    CORTES_ROLLING,
    LAMBDA_DEFECTO,
    PESO_AHORRO,
    PRODUCTO_A_ACCION,
    PRODUCTO_A_PANTALLA,
    TODOS_LOS_PRODUCTOS,
    UMBRAL_ON_TIME_H,
    UMBRAL_WARM_H,
)

VERSION = "v1"
PANEL_INICIO = "2026-03-04"      # primer día utilizable: se descartan 3 (7.36x la mediana)
PANEL_FIN = "2026-05-23"         # exclusivo de facto: el último corte semanal cae en 05-20
PANEL_FREQ = "7D"
LAMBDA_ALT = 165.0               # precio sombra en el margen (162.7 y 164.8 convergen)
ESCALA_AHORRO = 10.0             # Δahorro en pp/10, para que no domine la escala de días


# ---------------------------------------------------------------------------
def cortes_panel(v0: bool) -> list[str]:
    if v0:
        return [CORTE_MODELO]
    return [str(d.date()) for d in pd.date_range(PANEL_INICIO, PANEL_FIN, freq=PANEL_FREQ)]


def _matriz(corte: str, con) -> tuple[pd.DataFrame, pd.DataFrame]:
    X = construir(corte, con=con).set_index("customer_id")
    y = labels_intencion(corte, con=con).set_index("customer_id").reindex(X.index)
    return X, y


# ---------------------------------------------------------------------------
# X · Intención
# ---------------------------------------------------------------------------
def entrenar_intencion(cortes: list[str], con) -> dict:
    Xs, ys = [], []
    for c in cortes:
        X, y = _matriz(c, con)
        Xs.append(X)
        ys.append(y)
    XT = pd.concat(Xs)
    YT = pd.concat(ys)
    F = columnas_features(XT.reset_index())
    assert not any(c.startswith("customer_id") for c in F), "identificador en la matriz"

    arbol, regresion, coefs, acuerdo = {}, {}, {}, {}
    for a in ACCIONES:
        # label = "la PRIMERA acción de la ventana es `a`": es lo que mide el top-1
        lab = (YT.y_primera == a).astype(int).to_numpy()
        hgb = HistGradientBoostingClassifier(max_depth=4, random_state=0)   # sin class_weight
        hgb.fit(XT[F], lab)
        lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        lr.fit(XT[F], lab)
        arbol[a] = hgb
        regresion[a] = lr
        coefs[a] = dict(sorted(
            zip(F, lr.named_steps["logisticregression"].coef_[0].round(4).tolist()),
            key=lambda kv: -abs(kv[1]),
        ))
    return {"tipo": "intencion", "acciones": list(ACCIONES), "features": F,
            "arbol": arbol, "regresion": regresion, "coeficientes": coefs,
            "cortes_entrenamiento": cortes, "filas_entrenamiento": int(len(XT)),
            "acuerdo": acuerdo}


def puntuar_intencion(modelo: dict, X: pd.DataFrame, motor: str = "arbol") -> np.ndarray:
    F = modelo["features"]
    m = modelo[motor]
    return np.column_stack([m[a].predict_proba(X[F])[:, 1] for a in modelo["acciones"]])


# ---------------------------------------------------------------------------
# Y · Momento
# ---------------------------------------------------------------------------
VARS_MOMENTO = ["senal", "exposure_no"]


def entrenar_momento(con, corte: str = CORTE_MODELO) -> dict:
    lm = labels_momento(con=con)
    tr = lm[lm.shown_ts <= pd.Timestamp(corte)]
    te = lm[lm.shown_ts > pd.Timestamp(corte)]
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    pipe.fit(tr[VARS_MOMENTO], tr.y_engaged)

    p = pipe.predict_proba(te[VARS_MOMENTO])[:, 1]
    y = te.y_engaged.to_numpy()
    auc = roc_auc_score(y, p)
    k = int(round(0.01 * len(y)))
    umbral = np.sort(p)[::-1][k - 1]
    top = p >= umbral                       # sin desempate arbitrario: entran todos los empates
    coef = pipe.named_steps["logisticregression"].coef_[0]
    return {"tipo": "momento", "variables": VARS_MOMENTO, "pipeline": pipe,
            "corte_entrenamiento": corte,
            "coeficientes": dict(zip(VARS_MOMENTO, coef.round(4).tolist())),
            "metricas": {"auc": round(float(auc), 4),
                         "precision_top1pct": round(float(100 * y[top].mean()), 2),
                         "base_pct": round(float(100 * y.mean()), 2),
                         "n_train": int(len(tr)), "n_test": int(len(te))}}


def p_enganche(modelo: dict, senal, exposicion) -> np.ndarray:
    X = pd.DataFrame({"senal": np.asarray(senal), "exposure_no": np.asarray(exposicion)})
    return modelo["pipeline"].predict_proba(X[VARS_MOMENTO])[:, 1]


# ---------------------------------------------------------------------------
# Z · Valor  (aritmética, no aprendizaje automático)
# ---------------------------------------------------------------------------
def tabla_valor(con, lam: float = LAMBDA_DEFECTO) -> dict:
    """V(producto, λ) = (−Δdías_negativos) + (Δingreso/λ) + 0.3·Δahorro.

    Los tres deltas son los del cliente que **enganchó** (el efecto de un aviso
    ignorado es 0 por construcción: ver `recon/05_by_type_not_engaged.csv`),
    y Δahorro se normaliza a pp/10 para que un punto de tasa de ahorro no
    domine la escala de "días en descubierto", que es la unidad North Star.

    Comprobación del contrato: V(ahorro,266)=+0.700 y V(línea,266)=−0.077.
    """
    d = con.execute(
        """
        SELECT n.nudge_type AS producto, count(*) AS n,
               avg(o.delta_days_negative_90d)   AS d_dias_neg,
               avg(o.delta_revenue_mxn_90d)     AS d_ingreso,
               avg(o.delta_savings_rate_pct_90d) AS d_ahorro_pp
        FROM nudges n JOIN nudge_outcomes o ON o.nudge_id = n.nudge_id
        WHERE n.engaged GROUP BY n.nudge_type
        """
    ).df().set_index("producto")

    out = {}
    for p in TODOS_LOS_PRODUCTOS:
        r = d.loc[p]
        def v(l):
            return (-float(r.d_dias_neg)
                    + float(r.d_ingreso) / l
                    + PESO_AHORRO * float(r.d_ahorro_pp) / ESCALA_AHORRO)
        out[p] = {
            "n_enganches": int(r.n),
            "delta_dias_negativos": round(float(r.d_dias_neg), 4),
            "delta_ingreso_mxn": round(float(r.d_ingreso), 3),
            "delta_ahorro_pp": round(float(r.d_ahorro_pp), 4),
            "V_lambda_266": round(v(LAMBDA_DEFECTO), 4),
            "V_lambda_165": round(v(LAMBDA_ALT), 4),
            "en_catalogo": p in CATALOGO_DEMO,
        }
    return {
        "formula": "V = (-Δdías_negativos) + (Δingreso/λ) + 0.3·(Δahorro_pp/10)",
        "unidad": "días de descubierto evitados por enganche",
        "lambda_defecto": LAMBDA_DEFECTO,
        "lambda_alternativa": LAMBDA_ALT,
        "peso_ahorro": PESO_AHORRO,
        "escala_ahorro_pp": ESCALA_AHORRO,
        "nota_deltas": "medias condicionadas a engaged=true; el aviso ignorado tiene efecto 0",
        "productos": out,
    }


# ---------------------------------------------------------------------------
# Umbrales · se eligen en el corte de umbrales, nunca en test
# ---------------------------------------------------------------------------
def elegir_umbrales(mx: dict, my: dict, con, corte: str = CORTE_UMBRALES) -> dict:
    X, y = _matriz(corte, con)
    P = puntuar_intencion(mx, X)
    top = P.max(axis=1)
    pred = np.array(mx["acciones"])[P.argmax(axis=1)]
    act = y.activo.to_numpy() == 1
    verdad = y.y_primera.to_numpy()

    barrido = []
    for q in np.arange(0.50, 0.96, 0.05):
        thr = float(np.quantile(top, q))
        sel = (top >= thr) & act
        if sel.sum() == 0:
            continue
        barrido.append(dict(cuantil=round(float(q), 2), umbral=round(thr, 4),
                            cobertura_pct=round(100 * float((top >= thr).mean()), 2),
                            precision_pct=round(100 * float((pred[sel] == verdad[sel]).mean()), 2),
                            n=int(sel.sum())))
    b = pd.DataFrame(barrido)
    # regla de selección: el umbral MÁS BAJO cuya precisión iguala a la regla de
    # 24 h (63.45 %). Más bajo = más cobertura a igualdad de precisión.
    OBJETIVO = 63.45
    cand = b[b.precision_pct >= OBJETIVO]
    fila = (cand.iloc[0] if len(cand) else b.iloc[b.precision_pct.idxmax()])

    # momento: umbral que duplica la tasa base de enganche, elegido sobre los
    # avisos del mes anterior al corte de umbrales (nunca sobre el test).
    lm = labels_momento(con=con)
    val = lm[(lm.shown_ts > pd.Timestamp(corte) - pd.Timedelta(days=30))
             & (lm.shown_ts <= pd.Timestamp(corte))]
    pe = p_enganche(my, val.senal, val.exposure_no)
    base = float(val.y_engaged.mean())
    orden = np.argsort(-pe)
    acum = np.cumsum(val.y_engaged.to_numpy()[orden]) / np.arange(1, len(pe) + 1)
    ok = np.where(acum >= 2 * base)[0]
    thr_y = float(pe[orden][ok[-1]]) if len(ok) else float(np.quantile(pe, 0.9))

    return {
        "corte_seleccion": corte,
        "nota": "elegidos en el corte de umbrales; el test no participa",
        "p_intencion_min": round(float(fila.umbral), 4),
        "p_intencion_precision_pct": round(float(fila.precision_pct), 2),
        "p_intencion_cobertura_pct": round(float(fila.cobertura_pct), 2),
        "p_enganche_min": round(thr_y, 4),
        "p_enganche_base_pct": round(100 * base, 2),
        "v_min": 0.0,
        "cap_exposiciones": CAP_EXPOSICIONES,
        "umbral_on_time_h": UMBRAL_ON_TIME_H,
        "umbral_warm_h": UMBRAL_WARM_H,
        "barrido": barrido,
    }


# ---------------------------------------------------------------------------
# Nivel 3 · demo_pack.json
# ---------------------------------------------------------------------------
# Estado ordinal de señal -> etiqueta que espera app/scoring.py.
MOMENTO = {0: "on_time", 1: "warm", 2: "cold", 3: "never"}


def _ficha_minima(cid: int, fila, asof: str = CORTE_DEMO) -> dict:
    """La parte de la ficha que `ModeloEntrenado.scores` consume, y solo esa.

    El `asof` va dentro: el nivel 1 elige con él la foto de features del corte
    que toca, así que omitirlo sería puntuar con la foto de otro día.
    """
    return {
        "perfil": {"customer_id": int(cid)},
        "decision": {
            "asof": str(asof),
            "senales_por_nudge": {
                p: {"momento": MOMENTO[int(fila[f"senal_{PRODUCTO_A_ACCION[p]}"])],
                    "exposure_no_siguiente": int(fila[f"exp_{p}"]) + 1}
                for p in CATALOGO_DEMO}},
    }


def construir_demo_pack(con, corte: str = CORTE_DEMO) -> dict:
    """Paquete de respaldo (nivel 3) generado POR EL NIVEL 1, nunca a mano.

    Se instancia `app.scoring.ModeloEntrenado` —el mismo objeto que sirve el
    nivel 1 en caliente— y se guarda su salida literal. Si el nivel 3 dijera
    algo distinto del nivel 1, el fallback mentiría y nadie lo notaría.

    **El grano es (customer_id, corte), no customer_id.** Con un único corte el
    fallback mentía en 1 de los 9 escenarios: `multi_senal` se decide el
    2026-06-09 y el paquete guardaba sus números del 2026-06-16 —la misma
    oferta, otros scores—. Ahora cada corte curado tiene su bloque:

        clientes            → el corte por defecto (retrocompatible)
        clientes_por_corte  → los demás cortes curados, uno por clave

    Cada hoja se guarda como diccionario (`p_intencion`, `p_enganche`, `score`,
    `confianza`), que es la forma que `PaquetePrecalculado.scores` reinyecta
    tal cual. Un escalar solo podría llevar `score` y dejaría `p_intencion`,
    `p_enganche` y `confianza` divergiendo del nivel 1.
    `V` y `explicacion` NO se guardan: los pone el backend al leer, para que el
    paquete no pueda quedarse con una λ vieja.
    """
    from app.scoring import ModeloEntrenado, _leer_json, _normalizar_tabla_valor

    nivel1 = ModeloEntrenado.cargar(corte=corte)
    tabla = _normalizar_tabla_valor(_leer_json("tabla_valor"), LAMBDA_DEFECTO)

    pct, motivos = cobertura(corte, CATALOGO_DEMO, con=con)
    n_total = int(motivos.sum())
    n_oferta = int(motivos.get("oferta", 0))

    motivo = motivo_por_cliente(corte, CATALOGO_DEMO, con=con)
    con_oferta = [int(c) for c in motivo.index[motivo == "oferta"]]

    por_corte_casos = _casos_por_corte()

    def bloque(c: str, ids: list[int]) -> dict:
        """Los scores del nivel 1 en el corte `c`, para esos clientes."""
        feats = construir(c, con=con).set_index("customer_id")
        out = {}
        for cid in ids:
            if cid not in feats.index:
                continue
            sc = nivel1.scores(_ficha_minima(cid, feats.loc[cid], c), tabla)
            out[str(cid)] = {"scores": {
                p: {k: v[k] for k in ("p_intencion", "p_enganche", "score", "confianza")}
                for p, v in sc.items()}}
        return out

    clientes = bloque(corte, list(dict.fromkeys(por_corte_casos.get(corte, []) + con_oferta)))
    otros = {c: bloque(c, ids) for c, ids in sorted(por_corte_casos.items()) if c != corte}

    return {
        "corte": corte,
        "cortes": sorted({corte, *otros}),
        "generado_por": "analytics/entrenar.py · app.scoring.ModeloEntrenado (nivel 1)",
        "cobertura": {"pct_silencio": round(100 - pct, 2), "pct_oferta": round(pct, 2),
                      "n_silencio": n_total - n_oferta, "n_oferta": n_oferta},
        "casos_ejemplo": _clientes_de_casos(),
        "casos_ejemplo_por_corte": por_corte_casos,
        "clientes": clientes,
        "clientes_por_corte": otros,
    }


def _casos_curados() -> list[dict]:
    p = os.path.join(ARTIFACTS, "casos_ejemplo.json")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)["casos"]


def _clientes_de_casos() -> list[int]:
    """Los customer_id curados del pitch, sea cual sea el corte de cada caso."""
    return [int(c["customer_id"]) for c in _casos_curados()]


def _casos_por_corte() -> dict[str, list[int]]:
    """{corte: [customer_id]} · el corte es el `asof` con el que se curó el caso.

    Se toma del `asof` de la ficha, que es el que la demo va a pedir de verdad,
    no del campo `corte` (que es una etiqueta y podría divergir).
    """
    fuera: dict[str, list[int]] = {}
    for c in _casos_curados():
        asof = str(c["ficha"]["decision"]["asof"])[:10]
        fuera.setdefault(asof, []).append(int(c["customer_id"]))
    return fuera


# ---------------------------------------------------------------------------
def plantillas_razones() -> dict:
    return {
        "version": VERSION,
        "oferta": {
            "savings_goal": {"boton": "Crear una Cajita",
                             "razon": "Entró a Cajitas {cuando}{start}. Es su exposición #{exp} de {cap}."},
            "limit_increase": {"boton": "Aumentar tu línea",
                               "razon": "Entró a aumento de línea {cuando}{start}. Es su exposición #{exp} de {cap}."},
            "loan_offer": {"boton": "Simular un préstamo",
                           "razon": "Entró al simulador de préstamo {cuando}{start}. Es su exposición #{exp} de {cap}."},
            "bill_reminder": {"boton": "Programar tu pago",
                              "razon": "Entró a pago de servicios {cuando}{start}. Es su exposición #{exp} de {cap}."},
        },
        "momento": {
            "on_time": "hace {h:.0f} h",
            "warm": "hace {d:.0f} días",
        },
        # De dónde sale cada explicación. La interfaz DEBE poder distinguirlas:
        # el acuerdo árbol/regresión va de 94.07 % en el corte del modelo a
        # 62.76 % en el del demo, así que en el demo más de un tercio de las
        # explicaciones las firma la regla, no el modelo.
        "origen": {
            "modelo": {"etiqueta": "Lo explica el modelo",
                       "detalle": "El árbol y la regresión coinciden en la clase principal.",
                       "marca": None},
            "regla": {"etiqueta": "Lo explica la regla",
                      "detalle": "El árbol y la regresión no coinciden: la explicación cae a la regla de recencia.",
                      "marca": "explicación por regla"},
            "paquete": {"etiqueta": "Paquete precalculado",
                        "detalle": "Respuesta servida por el nivel 3 (demo_pack.json).",
                        "marca": "respaldo precalculado"},
        },
        "coletillas": {
            "start": " y llegó a iniciar el flujo",
            "payday": " Además está a {dias} días de su día de pago, cuando esa acción es hasta 5x más probable.",
            "sustitucion": " Sustituimos el aumento de línea, que hoy le haría daño.",
            "desacuerdo": " (explicación por regla: el árbol y la regresión no coinciden en la clase principal)",
        },
        "silencio": {
            "sin_senal": "No hay ninguna señal fresca de intención en la app. Sin señal el enganche cae a 10.3 %: hoy el asistente permanece en silencio.",
            "cupo_agotado": "Tiene la intención, pero ya vio ese mensaje {n} veces. La 3ª exposición convierte 3.51 % y provoca 2.53 % de baja —0.72 bajas por cada clic—. El cupo es 2.",
            "veto_fragilidad": "Detectamos que quiere ampliar su línea, pero {motivo}. Ofrecerle más crédito hoy le costaría días en descubierto mañana. Nos callamos.",
            "opt_out": "Este cliente desactivó las notificaciones. No le hablamos.",
            "fuera_de_catalogo": "La señal apunta a un producto fuera del catálogo del piloto ({producto}).",
        },
    }


# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    v0 = "--v0" in argv
    ver = "v0" if v0 else VERSION
    t0 = time.perf_counter()
    os.makedirs(ARTIFACTS, exist_ok=True)
    con = _conexion()

    # El nivel 3 se deriva del nivel 1 ya serializado: se puede regenerar solo
    # él, sin volver a entrenar (y sin tocar los .pkl que ya están verificados).
    if "--solo-demo-pack" in argv:
        try:
            print(f"[{ver}] demo_pack — nivel 3 generado por el nivel 1 (sin reentrenar)")
            pack = construir_demo_pack(con)
            _json("demo_pack.json", pack)
            print(f"      cortes {', '.join(pack['cortes'])}  ·  "
                  f"{len(pack['clientes']):,} clientes en {pack['corte']}  ·  "
                  + "  ".join(f"{c}: {len(v)}" for c, v in pack["clientes_por_corte"].items()))
            return 0
        finally:
            con.close()

    try:
        cortes = cortes_panel(v0)
        print(f"[{ver}] X · intención — {len(cortes)} corte(s) de entrenamiento "
              f"({cortes[0]} → {cortes[-1]})")
        mx = entrenar_intencion(cortes, con)
        print(f"      {mx['filas_entrenamiento']:,} filas x {len(mx['features'])} features, "
              f"{len(ACCIONES)} cabezas")

        # acuerdo árbol / regresión en el corte del demo
        Xd, _ = _matriz(CORTE_DEMO, con)
        pa = np.array(mx["acciones"])[puntuar_intencion(mx, Xd, "arbol").argmax(1)]
        pr = np.array(mx["acciones"])[puntuar_intencion(mx, Xd, "regresion").argmax(1)]
        acuerdo = round(100 * float((pa == pr).mean()), 2)
        mx["acuerdo"] = {"corte": CORTE_DEMO, "pct_coincide_clase_principal": acuerdo}
        print(f"      acuerdo árbol/regresión en la clase principal: {acuerdo} % "
              f"(el resto cae a explicación por regla, con marca)")

        print(f"[{ver}] Y · momento — regresión escalada, 2 variables")
        my = entrenar_momento(con)
        print(f"      AUC {my['metricas']['auc']}  precisión 1 % superior "
              f"{my['metricas']['precision_top1pct']} % vs base {my['metricas']['base_pct']} %")

        print(f"[{ver}] Z · valor — aritmética")
        tv = tabla_valor(con)
        va = tv["productos"]["savings_goal"]["V_lambda_266"]
        vl = tv["productos"]["limit_increase"]["V_lambda_266"]
        print(f"      V(ahorro,266)={va:+.3f} (esperado +0.700)   "
              f"V(línea,266)={vl:+.3f} (esperado −0.077)")

        print(f"[{ver}] umbrales — seleccionados en {CORTE_UMBRALES}")
        um = elegir_umbrales(mx, my, con)
        print(f"      p_intencion_min={um['p_intencion_min']} "
              f"(precisión {um['p_intencion_precision_pct']} %, cobertura {um['p_intencion_cobertura_pct']} %)")
        print(f"      p_enganche_min={um['p_enganche_min']} (base {um['p_enganche_base_pct']} %)")

        # ---------------- serialización ----------------
        joblib.dump(mx, os.path.join(ARTIFACTS, "modelo_intencion.pkl"))
        joblib.dump(my, os.path.join(ARTIFACTS, "modelo_momento.pkl"))
        _json("tabla_valor.json", tv)
        _json("umbrales.json", um)
        _json("razones.json", plantillas_razones())

        meta = {
            "version": ver,
            "corte": CORTE_DEMO,                       # ← el backend compara ESTO
            "corte_modelo": CORTE_MODELO,
            "corte_umbrales": CORTE_UMBRALES,
            "cortes_test": list(CORTES_ROLLING),
            "cortes_entrenamiento": cortes,
            "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "catalogo": list(CATALOGO_DEMO),
            "acciones": list(ACCIONES),
            "n_features": len(mx["features"]),
            "features": mx["features"],
            "producto_a_accion": dict(PRODUCTO_A_ACCION),
            "producto_a_pantalla": dict(PRODUCTO_A_PANTALLA),
            "modelo_intencion": {"algoritmo": "HistGradientBoostingClassifier(max_depth=4, random_state=0)",
                                 "explicador": "StandardScaler + LogisticRegression(max_iter=1000)",
                                 "class_weight": None,
                                 "acuerdo_pct": acuerdo},
            "modelo_momento": my["metricas"] | {"variables": VARS_MOMENTO},
            "lambda": LAMBDA_DEFECTO,
            "cap_exposiciones": CAP_EXPOSICIONES,
            "features_parquet": f"features_asof_{CORTE_DEMO}.parquet",
            "artefactos": ["modelo_intencion.pkl", "modelo_momento.pkl", "umbrales.json",
                           "tabla_valor.json", "razones.json", "metadata.json",
                           "demo_pack.json", f"features_asof_{CORTE_DEMO}.parquet"],
        }
        _json("metadata.json", meta)

        print(f"[{ver}] demo_pack — nivel 3 generado por el nivel 1")
        pack = construir_demo_pack(con)
        _json("demo_pack.json", pack)
        print(f"      {len(pack['clientes']):,} clientes  "
              f"(oferta {pack['cobertura']['n_oferta']:,} + {len(pack['casos_ejemplo'])} casos del pitch)")

        print(f"\nartefactos en {ARTIFACTS}  ({time.perf_counter() - t0:.1f}s)")
        for n in sorted(os.listdir(ARTIFACTS)):
            if n.startswith("."):
                continue
            p = os.path.join(ARTIFACTS, n)
            print(f"  {n:44s} {os.path.getsize(p) / 1e6:7.2f} MB")
        print(f"\nmetadata.json declara corte={meta['corte']} (CORTE_DEMO). "
              "Si no coincide, el backend cae al fallback EN SILENCIO.")
        return 0
    finally:
        con.close()


def _json(nombre: str, obj) -> None:
    with open(os.path.join(ARTIFACTS, nombre), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
