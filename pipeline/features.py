#!/usr/bin/env python3
"""BA-2 · Tabla de features as-of + BA-3 · Labels.

Grano: una fila por (customer_id, asof). El `asof` NO viaja como columna: va en
el nombre del archivo (`features_asof_<corte>.parquet`), tal y como manda el
contrato de `docs/arquitectura.md`. Así la verificación de BA-2

    assert len([c for c in df.columns if not c.startswith("customer_id")]) == 82

cuenta solo features.

REGLA INNEGOCIABLE
------------------
Toda feature se calcula con `event_ts < asof` **estricto**. No hay una sola
consulta con `<=`. La prueba negativa vive en `pipeline/tests/test_leakage.py`,
con su control positivo: se inyecta un evento en `asof + 1h` y ninguna feature se
mueve; el mismo evento en `asof − 1h` sí la mueve. `analytics/tests/test_fuga.py`
repite la afirmación sobre el SQL de este módulo, y
`pipeline/tests/test_fuga_en_servicio.py` la extiende al servicio: la foto as-of
que puntúa una petición nunca es posterior a su `asof`.

Nunca se usa `LEFT JOIN ... USING`: duplica la clave y mete `customer_id_2` en
la matriz. Todos los joins son `ON` explícito y las columnas se listan a mano.

COMPOSICIÓN DE LAS 82 COLUMNAS
------------------------------
| bloque                                    | columnas |
|-------------------------------------------|----------|
| recencia por pantalla `rec_h_*`           |    10    |
| eventos 24 h por pantalla `n24_*`         |    10    |
| eventos 72 h por pantalla `n72_*`         |    10    |
| `start` 24 h por pantalla `s24_*`         |    10    |
| `start` 72 h por pantalla `s72_*`         |    10    |
| señal por acción `senal_*` (0..3)         |     8    |
| proporción start/vista `ratio_start_*`    |     8    |
| tenencia `has_*`                          |     5    |
| calendario `dias_a_payday`                |     1    |
| exposición previa por producto `exp_*`    |     4    |
| agregados de navegación                   |     6    |
|-------------------------------------------|----------|
| **total**                                 | **82**   |

Los bloques `s24_*`/`s72_*` y los 6 agregados son la parte que la guía no
enumera columna a columna (su tabla suma 56). Se eligieron así porque *todas*
se calculan as-of desde `app_events`/`nudges`, sin depender de las columnas de
`customers` sin vintage que `recon/06_leakage_table.csv` marca como riesgo.

LISTA NEGRA (nunca entran, con motivo)
--------------------------------------
- `delta_*_90d`                  → es el target
- `engaged` / `dismissed` / `opted_out_after` → es el target
- `engagement_score`             → genera eventos Y avisos: es casi el label
- `abandon`                      → anti-predictivo (0.15 % vs 23.33 %)
- hora del día / día de semana   → ruido (0.98 pp y 0.35 pp de rango)
- `hours_since_last_nudge`       → efecto nulo controlando por exposición
- secuencia histórica de acciones→ predice peor que el baseline
- `customer_id_2` y similares    → artefacto de join

Uso:
    .venv/bin/python pipeline/features.py            # todos los cortes
    .venv/bin/python pipeline/features.py 2026-06-16 # uno concreto
"""
from __future__ import annotations

import os
import sys
import time

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.mapas import (  # noqa: E402  (import tras ajustar sys.path)
    ACCIONES,
    CATALOGO_DEMO,
    CORTE_DEMO,
    CORTE_MODELO,
    CORTE_UMBRALES,
    CORTES_ROLLING,
    PANTALLAS,
    PRODUCTO_A_ACCION,
    PRODUCTO_A_PANTALLA,
    UMBRAL_ON_TIME_H,
    UMBRAL_WARM_H,
)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(RAIZ, "data")
ARTIFACTS = os.path.join(RAIZ, "pipeline", "artifacts")

# Ventana del generador y recorte de bordes (BA-3): el primer día trae 7.36x la
# mediana de acciones y el final está censurado.
INICIO_DATOS = pd.Timestamp("2026-03-01")
FIN_DATOS = pd.Timestamp("2026-06-29")     # el último evento es 2026-06-28 23:59
DIAS_BORDE = 3
VENTANA_LABEL_D = 7

# Pantalla acoplada de cada una de las 8 acciones. Las cinco de producto salen
# de `mapas.py` (fuente de verdad); las tres restantes no tienen producto
# asociado pero sí pantalla evidente, y se necesitan porque hay 8 cabezas.
ACCION_A_PANTALLA = {
    PRODUCTO_A_ACCION[p]: PRODUCTO_A_PANTALLA[p] for p in PRODUCTO_A_ACCION
}
ACCION_A_PANTALLA.update(
    {"spei_out": "transfer_spei", "deposit_in": "home", "card_payment": "card_statement"}
)
assert set(ACCION_A_PANTALLA) == set(ACCIONES), "faltan pantallas acopladas"

PANTALLAS_ACOPLADAS = sorted(set(ACCION_A_PANTALLA.values()))   # 8 de las 10

# Estados de señal (ordinal: cuanto más bajo, más fresca).
SENAL_ON_TIME, SENAL_WARM, SENAL_COLD, SENAL_NUNCA = 0, 1, 2, 3

CORTES_POR_DEFECTO = sorted(
    set(CORTES_ROLLING) | {CORTE_MODELO, CORTE_UMBRALES, CORTE_DEMO}
)

# Patrones que jamás pueden aparecer en la matriz. Se comprueba en cada build.
PATRONES_PROHIBIDOS = (
    "customer_id",
    "engagement_score",
    "abandon",
    "engaged",
    "dismissed",
    "opted_out",
    "delta_",
    "_90d",
    "hours_since_last_nudge",
    "hour",
    "dow",
    "nps",
)


def _conexion() -> duckdb.DuckDBPyConnection:
    """Conexión con las 5 tablas registradas como vistas sobre `data/`."""
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    for t in ("customers", "app_events", "financial_actions", "nudges", "nudge_outcomes"):
        ruta = os.path.join(DATA, f"{t}.parquet")
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{ruta}')")
    return con


def _col(nombre: str) -> str:
    """Nombre de columna seguro para SQL/parquet."""
    return nombre.replace("-", "_")


def construir(asof: str, con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """Tabla as-of para un corte. Devuelve customer_id + 82 features."""
    propia = con is None
    con = con or _conexion()
    ts = pd.Timestamp(asof)

    try:
        # --- base: un cliente por fila, siempre los 38,000 -------------------
        df = con.execute(
            "SELECT customer_id, payday_day_of_month, has_cuenta_nu, has_cajita_turbo, "
            "has_personal_loan, has_investments, has_payroll_portability "
            "FROM customers ORDER BY customer_id"
        ).df()
        df = df.set_index("customer_id")

        # --- navegación por pantalla (corte ESTRICTO) ------------------------
        nav = con.execute(
            f"""
            SELECT e.customer_id AS customer_id,
                   e.screen      AS screen,
                   date_diff('second', max(e.event_ts), TIMESTAMP '{ts}') / 3600.0 AS rec_h,
                   count(*) FILTER (
                       WHERE e.event_ts >= TIMESTAMP '{ts}' - INTERVAL 24 HOUR) AS n24,
                   count(*) FILTER (
                       WHERE e.event_ts >= TIMESTAMP '{ts}' - INTERVAL 72 HOUR) AS n72,
                   count(*) FILTER (
                       WHERE e.action = 'start'
                         AND e.event_ts >= TIMESTAMP '{ts}' - INTERVAL 24 HOUR) AS s24,
                   count(*) FILTER (
                       WHERE e.action = 'start'
                         AND e.event_ts >= TIMESTAMP '{ts}' - INTERVAL 72 HOUR) AS s72,
                   count(*) FILTER (WHERE e.action = 'start') AS n_start_hist,
                   count(*) FILTER (WHERE e.action = 'view')  AS n_view_hist
            FROM app_events e
            WHERE e.event_ts < TIMESTAMP '{ts}'
            GROUP BY e.customer_id, e.screen
            """
        ).df()

        piv = {c: nav.pivot(index="customer_id", columns="screen", values=c)
               for c in ("rec_h", "n24", "n72", "s24", "s72", "n_start_hist", "n_view_hist")}

        for scr in PANTALLAS:
            c = _col(scr)
            df[f"rec_h_{c}"] = piv["rec_h"][scr].reindex(df.index) if scr in piv["rec_h"] else pd.NA
            for pref, key in (("n24", "n24"), ("n72", "n72"), ("s24", "s24"), ("s72", "s72")):
                s = piv[key][scr].reindex(df.index) if scr in piv[key] else 0
                df[f"{pref}_{c}"] = pd.Series(s, index=df.index).fillna(0).astype("int32")

        # recencia: sin visita histórica -> muy lejos, no 0 (0 sería "acaba de verlo")
        SIN_VISITA_H = 1e6
        for scr in PANTALLAS:
            col = f"rec_h_{_col(scr)}"
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(SIN_VISITA_H).astype("float32")

        # --- señal por acción: on_time / warm / cold / never -----------------
        for acc in ACCIONES:
            h = df[f"rec_h_{_col(ACCION_A_PANTALLA[acc])}"]
            estado = pd.Series(SENAL_COLD, index=df.index, dtype="int8")
            estado[h >= SIN_VISITA_H] = SENAL_NUNCA
            estado[h <= UMBRAL_WARM_H] = SENAL_WARM
            estado[h <= UMBRAL_ON_TIME_H] = SENAL_ON_TIME
            df[f"senal_{acc}"] = estado

        # --- proporción start/vista en las 8 pantallas acopladas -------------
        for scr in PANTALLAS_ACOPLADAS:
            st = (piv["n_start_hist"][scr].reindex(df.index)
                  if scr in piv["n_start_hist"] else pd.Series(0.0, index=df.index)).fillna(0.0)
            vw = (piv["n_view_hist"][scr].reindex(df.index)
                  if scr in piv["n_view_hist"] else pd.Series(0.0, index=df.index)).fillna(0.0)
            df[f"ratio_start_{_col(scr)}"] = (st / vw.where(vw > 0)).fillna(0.0).astype("float32")

        # --- tenencia --------------------------------------------------------
        for c in ("has_cuenta_nu", "has_cajita_turbo", "has_personal_loan",
                  "has_investments", "has_payroll_portability"):
            df[c] = df[c].astype("int8")

        # --- calendario: días hasta el próximo día de pago -------------------
        dom = ts.day
        df["dias_a_payday"] = ((df["payday_day_of_month"] - dom) % 30).astype("int16")
        df = df.drop(columns=["payday_day_of_month"])

        # --- exposición previa por producto del catálogo ---------------------
        exp = con.execute(
            f"""
            SELECT n.customer_id AS customer_id, n.nudge_type AS nudge_type, count(*) AS n
            FROM nudges n
            WHERE n.shown_ts < TIMESTAMP '{ts}'
            GROUP BY n.customer_id, n.nudge_type
            """
        ).df()
        pexp = exp.pivot(index="customer_id", columns="nudge_type", values="n")
        for prod in CATALOGO_DEMO:
            s = pexp[prod].reindex(df.index) if prod in pexp else 0
            df[f"exp_{prod}"] = pd.Series(s, index=df.index).fillna(0).astype("int16")
        df["n_exposiciones_total"] = (
            pexp.reindex(df.index).sum(axis=1).fillna(0).astype("int16"))

        # --- agregados de navegación -----------------------------------------
        agg = con.execute(
            f"""
            SELECT e.customer_id AS customer_id,
                   count(*) FILTER (
                       WHERE e.event_ts >= TIMESTAMP '{ts}' - INTERVAL 24 HOUR) AS n_eventos_24h,
                   count(*) FILTER (
                       WHERE e.event_ts >= TIMESTAMP '{ts}' - INTERVAL 72 HOUR) AS n_eventos_72h,
                   count(*) FILTER (
                       WHERE e.event_ts >= TIMESTAMP '{ts}' - INTERVAL 7 DAY)   AS n_eventos_7d,
                   count(DISTINCT e.screen) FILTER (
                       WHERE e.event_ts >= TIMESTAMP '{ts}' - INTERVAL 7 DAY)   AS pantallas_distintas_7d,
                   date_diff('second', max(e.event_ts), TIMESTAMP '{ts}') / 3600.0
                       AS horas_desde_ultimo_evento
            FROM app_events e
            WHERE e.event_ts < TIMESTAMP '{ts}'
            GROUP BY e.customer_id
            """
        ).df().set_index("customer_id")

        for c in ("n_eventos_24h", "n_eventos_72h", "n_eventos_7d", "pantallas_distintas_7d"):
            df[c] = agg[c].reindex(df.index).fillna(0).astype("int32")
        df["horas_desde_ultimo_evento"] = (
            agg["horas_desde_ultimo_evento"].reindex(df.index).fillna(SIN_VISITA_H).astype("float32"))

        df = df.reset_index()
        _verificar(df)
        return df
    finally:
        if propia:
            con.close()


def columnas_features(df: pd.DataFrame) -> list[str]:
    """Las columnas que entran a los modelos: todo menos los identificadores."""
    return [c for c in df.columns if not c.startswith("customer_id")]


def _verificar(df: pd.DataFrame) -> None:
    feats = columnas_features(df)
    if len(feats) != 82:
        raise AssertionError(f"se esperaban 82 features, hay {len(feats)}: {sorted(feats)}")
    for c in feats:
        low = c.lower()
        for pat in PATRONES_PROHIBIDOS:
            if pat in low:
                raise AssertionError(f"feature prohibida por patrón '{pat}': {c}")
    if df.customer_id.duplicated().any():
        raise AssertionError("customer_id duplicado: el grano no es (customer_id, asof)")
    if df.isna().any().any():
        malas = df.columns[df.isna().any()].tolist()
        raise AssertionError(f"nulos en la matriz: {malas}")


# ---------------------------------------------------------------------------
# BA-3 · Labels
# ---------------------------------------------------------------------------
def _ventana_valida(asof: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(inicio, fin] de la ventana de label, recortando los bordes del generador."""
    ini = pd.Timestamp(asof)
    fin = ini + pd.Timedelta(days=VENTANA_LABEL_D)
    borde_ini = INICIO_DATOS + pd.Timedelta(days=DIAS_BORDE)
    borde_fin = FIN_DATOS - pd.Timedelta(days=DIAS_BORDE)
    if ini < borde_ini or fin > borde_fin:
        raise ValueError(
            f"corte {asof}: la ventana ({ini.date()}, {fin.date()}] se sale del rango "
            f"utilizable ({borde_ini.date()}, {borde_fin.date()}]. "
            "Se descartan los 3 primeros días (7.36x la mediana de acciones) y los 3 últimos (censura)."
        )
    return ini, fin


def labels_intencion(asof: str, con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """8 columnas binarias `y_<accion>` en (asof, asof+7d], más la primera acción.

    `y_primera` es la clase multiclase para el top-1 (NaN si el cliente no actuó).
    `activo` marca a los clientes con al menos una acción en la ventana: es el
    universo sobre el que se mide la exactitud contra el baseline constante.
    """
    propia = con is None
    con = con or _conexion()
    ini, fin = _ventana_valida(asof)
    try:
        base = con.execute("SELECT customer_id FROM customers ORDER BY customer_id").df()
        w = con.execute(
            f"""
            SELECT f.customer_id AS customer_id,
                   f.action_type AS action_type,
                   min(f.action_ts) AS primera_ts,
                   count(*) AS n
            FROM financial_actions f
            WHERE f.action_ts >  TIMESTAMP '{ini}'
              AND f.action_ts <= TIMESTAMP '{fin}'
            GROUP BY f.customer_id, f.action_type
            """
        ).df()
        piv = w.pivot(index="customer_id", columns="action_type", values="n")
        out = base.set_index("customer_id")
        for acc in ACCIONES:
            s = piv[acc].reindex(out.index) if acc in piv else 0
            out[f"y_{acc}"] = (pd.Series(s, index=out.index).fillna(0) > 0).astype("int8")
        primera = (w.sort_values(["customer_id", "primera_ts"])
                     .groupby("customer_id", as_index=True).action_type.first())
        out["y_primera"] = primera.reindex(out.index)
        out["activo"] = out["y_primera"].notna().astype("int8")
        return out.reset_index()
    finally:
        if propia:
            con.close()


def labels_momento(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """Una fila por `nudge_id` con `y_engaged` y las 2 variables del modelo Y.

    `senal` es el estado de la pantalla acoplada en el instante `shown_ts`
    (corte estricto: solo eventos anteriores) y `exposure_no` es la exposición
    que ya traía el aviso. Ninguna de las dos mira al futuro.
    """
    propia = con is None
    con = con or _conexion()
    try:
        pares = " UNION ALL ".join(
            f"SELECT '{p}' AS nudge_type, '{s}' AS want_screen"
            for p, s in {**PRODUCTO_A_PANTALLA, "payroll_portability": "home"}.items()
        )
        con.execute(f"CREATE OR REPLACE TEMP TABLE nmap AS {pares}")
        con.execute(
            "CREATE OR REPLACE TEMP TABLE ek AS "
            "SELECT customer_id::VARCHAR || '|' || screen AS k, event_ts FROM app_events"
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE nn AS
            SELECT n.nudge_id, n.customer_id, n.nudge_type, n.exposure_no,
                   n.engaged, n.shown_ts,
                   n.customer_id::VARCHAR || '|' || m.want_screen AS k
            FROM nudges n JOIN nmap m ON m.nudge_type = n.nudge_type
            """
        )
        df = con.execute(
            """
            SELECT nn.nudge_id AS nudge_id, nn.customer_id AS customer_id,
                   nn.nudge_type AS nudge_type, nn.exposure_no AS exposure_no,
                   nn.shown_ts AS shown_ts,
                   CAST(nn.engaged AS INT) AS y_engaged,
                   coalesce(date_diff('second', ek.event_ts, nn.shown_ts) / 3600.0, 1e6) AS gap_h
            FROM nn ASOF LEFT JOIN ek ON nn.k = ek.k AND ek.event_ts < nn.shown_ts
            """
        ).df()
        df["shown_ts"] = pd.to_datetime(df.shown_ts)
        g = df.gap_h
        estado = pd.Series(SENAL_COLD, index=df.index, dtype="int8")
        estado[g >= 1e5] = SENAL_NUNCA
        estado[g <= UMBRAL_WARM_H] = SENAL_WARM
        estado[g <= UMBRAL_ON_TIME_H] = SENAL_ON_TIME
        df["senal"] = estado
        return df
    finally:
        if propia:
            con.close()


# ---------------------------------------------------------------------------
def ruta_features(asof: str) -> str:
    return os.path.join(ARTIFACTS, f"features_asof_{asof}.parquet")


def cargar(asof: str) -> pd.DataFrame:
    """Lee la tabla precomputada; la construye si falta."""
    p = ruta_features(asof)
    if not os.path.exists(p):
        escribir(asof)
    return pd.read_parquet(p)


def escribir(asof: str, con: duckdb.DuckDBPyConnection | None = None) -> str:
    os.makedirs(ARTIFACTS, exist_ok=True)
    t0 = time.perf_counter()
    df = construir(asof, con=con)
    p = ruta_features(asof)
    df.to_parquet(p, index=False, compression="zstd")
    print(f"  -> {p}  {len(df):,} x {df.shape[1]} cols "
          f"({len(columnas_features(df))} features)  {time.perf_counter() - t0:.1f}s")
    return p


def main(argv: list[str]) -> int:
    cortes = argv[1:] or CORTES_POR_DEFECTO
    con = _conexion()
    try:
        print(f"features as-of · corte estricto event_ts < asof · {len(cortes)} cortes")
        for a in cortes:
            escribir(a, con=con)

        # labels de intención en un único parquet con columna `asof` (BA-3)
        partes = []
        for a in cortes:
            lab = labels_intencion(a, con=con)
            lab.insert(1, "asof", a)
            partes.append(lab)
        li = pd.concat(partes, ignore_index=True)
        p = os.path.join(ARTIFACTS, "labels_intent.parquet")
        li.to_parquet(p, index=False, compression="zstd")
        print(f"  -> {p}  {len(li):,} filas  ({li['asof'].nunique()} cortes)")
        for a in cortes:
            sub = li[li["asof"] == a]
            act = int(sub.activo.sum())
            const = 100 * (sub.loc[sub.activo == 1, "y_primera"] == "spei_out").mean()
            print(f"     {a}: activos {act:,}  baseline constante {const:.2f}%")

        lm = labels_momento(con=con)
        p = os.path.join(ARTIFACTS, "labels_moment.parquet")
        lm.to_parquet(p, index=False, compression="zstd")
        print(f"  -> {p}  {len(lm):,} avisos  engaged {100 * lm.y_engaged.mean():.2f}%")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
