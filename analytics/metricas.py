#!/usr/bin/env python3
"""BA-8 · Embudo M1–M5, métricas por producto, fatiga y simulación de políticas.

Todo se calcula desde `data/`; los valores de `docs/metricas.md` entran aquí
como **prueba de regresión**, no como referencia. Cada tabla se imprime con la
columna `esperado` al lado y una marca OK/DIFIERE.

Nota de denominadores (está en `docs/metricas.md` y no es una inconsistencia):
la tasa de clic global vale 10.98 % sobre los 237,603 avisos **con acción
acoplada** y 11.45 % sobre los 285,000 totales. `payroll_portability` no tiene
acción acoplada y queda fuera del primero.

Uso: .venv/bin/python analytics/metricas.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.features import _conexion, cargar, labels_intencion  # noqa: E402
from pipeline.mapas import (  # noqa: E402
    CAP_EXPOSICIONES,
    CATALOGO_DEMO,
    CORTE_DEMO,
    FRAGIL_DIAS_NEGATIVOS,
    FRAGIL_UTILIZACION_PCT,
    PRODUCTO_A_ACCION,
)

CLASE_BASELINE = "spei_out"     # elegida en entrenamiento, no por corte
VENTANA_D = 7


# ---------------------------------------------------------------------------
# BA-4 · el baseline que consume el canario
# ---------------------------------------------------------------------------
def acc_baseline(corte: str, con=None, clase: str = CLASE_BASELINE) -> float:
    """Exactitud (%) del predictor constante sobre los clientes activos del corte."""
    propia = con is None
    con = con or _conexion()
    try:
        lab = labels_intencion(corte, con=con)
        act = lab[lab.activo == 1]
        return round(100.0 * (act.y_primera == clase).mean(), 4)
    finally:
        if propia:
            con.close()


# ---------------------------------------------------------------------------
# Tabla base de avisos con su conversión a 7 días
# ---------------------------------------------------------------------------
def _tabla_avisos(con) -> pd.DataFrame:
    """Un aviso por fila con `convirtio` = hizo la acción acoplada en 7 días."""
    pares = " UNION ALL ".join(
        f"SELECT '{p}' AS nudge_type, '{a}' AS action_type"
        for p, a in PRODUCTO_A_ACCION.items()
    )
    con.execute(f"CREATE OR REPLACE TEMP TABLE amap AS {pares}")
    return con.execute(
        f"""
        WITH conv AS (
          SELECT n.nudge_id AS nudge_id,
                 max(CASE WHEN f.action_ts IS NULL THEN 0 ELSE 1 END) AS convirtio
          FROM nudges n
          JOIN amap m ON m.nudge_type = n.nudge_type
          LEFT JOIN financial_actions f
                 ON f.customer_id = n.customer_id
                AND f.action_type  = m.action_type
                AND f.action_ts >  n.shown_ts
                AND f.action_ts <= n.shown_ts + INTERVAL {VENTANA_D} DAY
          GROUP BY n.nudge_id
        )
        SELECT n.nudge_id AS nudge_id, n.customer_id AS customer_id,
               n.nudge_type AS nudge_type, n.surface AS surface,
               n.exposure_no AS exposure_no,
               CAST(n.engaged AS INT) AS engaged,
               CAST(n.dismissed AS INT) AS dismissed,
               CAST(n.opted_out_after AS INT) AS opted_out,
               coalesce(c.convirtio, 0) AS convirtio,
               CASE WHEN c.nudge_id IS NULL THEN 0 ELSE 1 END AS tiene_accion_acoplada,
               o.delta_revenue_mxn_90d AS d_revenue,
               o.delta_days_negative_90d AS d_dias_neg,
               o.delta_savings_rate_pct_90d AS d_ahorro,
               (cu.card_utilization_pct > {FRAGIL_UTILIZACION_PCT}
                OR cu.days_negative_90d >= {FRAGIL_DIAS_NEGATIVOS}) AS fragil
        FROM nudges n
        LEFT JOIN conv c ON c.nudge_id = n.nudge_id
        JOIN nudge_outcomes o ON o.nudge_id = n.nudge_id
        JOIN customers cu ON cu.customer_id = n.customer_id
        """
    ).df()


# ---------------------------------------------------------------------------
# M1–M5
# ---------------------------------------------------------------------------
def embudo(av: pd.DataFrame, cobertura_pct: float) -> pd.DataFrame:
    ac = av[av.tiene_accion_acoplada == 1]
    m2 = 100 * ac.engaged.mean()
    m3 = 100 * ac.convirtio.mean()
    con_clic = 100 * ac.loc[ac.engaged == 1, "convirtio"].mean()
    sin_clic = 100 * ac.loc[ac.engaged == 0, "convirtio"].mean()
    filas = [
        ("M1", "Cobertura de oferta (política, catálogo de 4)", cobertura_pct, 14.0, "%"),
        ("M2", "Tasa de clic (avisos con acción acoplada)", m2, 10.98, "%"),
        ("M3", "Conversión a 7 días", m3, 4.47, "%"),
        ("M4", "Eficiencia del clic (M3/M2)", m3 / m2, 0.41, ""),
        ("M5", "Brecha con-clic / sin-clic", con_clic - sin_clic, 3.47, "pp"),
    ]
    return pd.DataFrame(filas, columns=["#", "metrica", "obtenido", "esperado", "u"])


def por_producto(av: pd.DataFrame) -> pd.DataFrame:
    ac = av[av.tiene_accion_acoplada == 1]
    g = ac.groupby("nudge_type")
    d = pd.DataFrame({
        "n": g.size(),
        "clic_%": 100 * g.engaged.mean(),
        "conv_7d_%": 100 * g.convirtio.mean(),
    })
    d["eficiencia"] = d["conv_7d_%"] / d["clic_%"]
    d["con_clic_%"] = 100 * ac[ac.engaged == 1].groupby("nudge_type").convirtio.mean()
    d["sin_clic_%"] = 100 * ac[ac.engaged == 0].groupby("nudge_type").convirtio.mean()
    d["brecha_pp"] = d["con_clic_%"] - d["sin_clic_%"]
    return d.round(2).sort_values("conv_7d_%", ascending=False)


def curva_fatiga(av: pd.DataFrame) -> pd.DataFrame:
    e = av.copy()
    e["exp"] = e.exposure_no.clip(upper=6).astype(int)
    g = e.groupby("exp")
    d = pd.DataFrame({"n": g.size(),
                      "enganche_%": (100 * g.engaged.mean()).round(2),
                      "baja_%": (100 * g.opted_out.mean()).round(3)})
    d.index = [str(i) if i < 6 else "6+" for i in d.index]
    return d


def motivo_por_cliente(asof: str = CORTE_DEMO, catalogo=CATALOGO_DEMO, con=None) -> pd.Series:
    """Serie indexada por `customer_id`: "oferta" o "silencio:<motivo>".

    Puertas replicadas aquí para poder medir sin depender de `pipeline/politica.py`
    (que pertenece a Ingeniería): momento on_time/warm, cap de exposición,
    veto de `limit_increase` a frágiles y silencio absoluto tras un opt-out.
    """
    propia = con is None
    con = con or _conexion()
    try:
        f = cargar(asof).set_index("customer_id")
        cu = con.execute(
            "SELECT customer_id, card_utilization_pct, days_negative_90d FROM customers"
        ).df().set_index("customer_id")
        fragil = ((cu.card_utilization_pct > FRAGIL_UTILIZACION_PCT)
                  | (cu.days_negative_90d >= FRAGIL_DIAS_NEGATIVOS)).reindex(f.index)
        oo = con.execute(
            f"""SELECT customer_id, max(CAST(opted_out_after AS INT)) AS oo FROM nudges
                WHERE shown_ts < TIMESTAMP '{asof}' GROUP BY customer_id"""
        ).df().set_index("customer_id")["oo"]
        opt_out = oo.reindex(f.index).fillna(0).astype(bool)

        motivo = pd.Series("silencio:sin_senal", index=f.index)
        hay_senal = pd.Series(False, index=f.index)
        elegible = pd.Series(False, index=f.index)
        vetado = pd.Series(False, index=f.index)
        for p in catalogo:
            s = f[f"senal_{PRODUCTO_A_ACCION[p]}"] <= 1          # on_time (0) o warm (1)
            hay_senal |= s
            m = s & (f[f"exp_{p}"] < CAP_EXPOSICIONES)
            if p == "limit_increase":
                vetado |= m & fragil
                m = m & ~fragil
            elegible |= m
        motivo[hay_senal] = "silencio:cupo_agotado"
        motivo[hay_senal & vetado & ~elegible] = "silencio:veto_fragilidad"
        motivo[elegible] = "oferta"
        motivo[opt_out] = "silencio:opt_out"
        return motivo
    finally:
        if propia:
            con.close()


def cobertura(asof: str = CORTE_DEMO, catalogo=CATALOGO_DEMO, con=None) -> tuple[float, pd.Series]:
    """(% de clientes con ≥1 oferta, conteo por motivo) bajo la política final."""
    motivo = motivo_por_cliente(asof, catalogo, con=con)
    return round(100.0 * float((motivo == "oferta").mean()), 4), motivo.value_counts()


def simulacion_politicas(av: pd.DataFrame) -> pd.DataFrame:
    base = av
    pol = {
        "P0 · enviar todo": pd.Series(True, index=av.index),
        "P1 · cap 2": av.exposure_no <= CAP_EXPOSICIONES,
        "P6 · solo salud": None,   # se rellena abajo (necesita la señal as-of)
        "P8 · cap 2 ∧ veto": (av.exposure_no <= CAP_EXPOSICIONES)
                             & ~((av.nudge_type == "limit_increase") & av.fragil),
    }
    del pol["P6 · solo salud"]
    rev0 = base.d_revenue.sum()
    filas = []
    for nombre, m in pol.items():
        s = base[m]
        filas.append(dict(politica=nombre, enviados=len(s),
                          pct_vol=round(100 * len(s) / len(base), 1),
                          enganche_pct=round(100 * s.engaged.mean(), 2),
                          pct_ingreso_retenido=round(100 * s.d_revenue.sum() / rev0, 1),
                          dias_negativos=round(s.d_dias_neg.sum())))
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
def _marca(obt, esp, tol):
    return "OK" if abs(obt - esp) <= tol else "DIFIERE"


def main() -> int:
    con = _conexion()
    try:
        av = _tabla_avisos(con)
        cob, motivos = cobertura(CORTE_DEMO, con=con)

        print("=" * 84)
        print(f"EMBUDO M1–M5   (M1 en el corte {CORTE_DEMO}, catálogo de {len(CATALOGO_DEMO)})")
        print("=" * 84)
        e = embudo(av, cob)
        for _, r in e.iterrows():
            tol = 0.1 if r["u"] != "" else 0.01
            print(f"  {r['#']}  {r['metrica']:46s} {r['obtenido']:8.2f}{r['u']:2s}"
                  f"  esperado {r['esperado']:7.2f}{r['u']:2s}  {_marca(r['obtenido'], r['esperado'], tol)}")

        print(f"\n  denominador alternativo · clic sobre los {len(av):,} avisos totales: "
              f"{100 * av.engaged.mean():.2f}%  (esperado 11.45%)")
        print(f"  avisos con acción acoplada: {int(av.tiene_accion_acoplada.sum()):,}  (esperado 237,603)")

        print("\n" + "=" * 84)
        print("POR PRODUCTO")
        print("=" * 84)
        print(por_producto(av).to_string())

        print("\n" + "=" * 84)
        print("GUARDRAILS")
        print("=" * 84)
        for lab, obt, esp, u in [
            ("Baja de notificaciones", 100 * av.opted_out.mean(), 0.969, "%"),
            ("Descarte", 100 * av.dismissed.mean(), 37.24, "%"),
            ("Silencio (política, corte demo)", 100 - cob, 86.0, "%"),
        ]:
            print(f"  {lab:34s} {obt:8.3f}{u}  esperado {esp:7.3f}{u}  {_marca(obt, esp, 0.1)}")

        print("\n" + "=" * 84)
        print("CURVA DE FATIGA")
        print("=" * 84)
        cf = curva_fatiga(av)
        esp_eng = [15.68, 7.83, 3.51, 1.75, 0.70, 0.00]
        esp_baja = [0.279, 1.270, 2.531, 3.308, 4.502, 6.112]
        cf["enganche_esperado"] = esp_eng
        cf["baja_esperada"] = esp_baja
        print(cf.to_string())

        print("\n" + "=" * 84)
        print("DECISIÓN DE LA POLÍTICA SOBRE LOS 38,000 CLIENTES")
        print("=" * 84)
        for k, v in motivos.items():
            print(f"  {k:28s} {v:7,}   {100 * v / 38000:5.2f}%")

        print("\n" + "=" * 84)
        print("SIMULACIÓN DE POLÍTICAS (sobre los avisos observados; no enviar = efecto 0)")
        print("=" * 84)
        print(simulacion_politicas(av).to_string(index=False))
        print("\n  esperado P0 285,000 / 100 % / 11.45 % / 100 % / +1,679")
        print("           P1 240,110 / 84.2 % / 13.06 % / 96.1 % / +1,612")
        print("           P8 232,500 / 81.6 % / 12.55 % / 75.2 % / −2,895")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
