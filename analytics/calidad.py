#!/usr/bin/env python3
"""BA-9 · Los seis controles de calidad.

| Control                     | Criterio                                  |
|-----------------------------|-------------------------------------------|
| Integridad de uniones       | 0 huérfanos en las tres tablas            |
| Canario de baselines        | los cuatro valores dentro de ±0.05        |
| Distribución de clases      | estable entre los tres cortes             |
| Sin fuga                    | ninguna feature se mueve con un evento futuro |
| Sin columnas de identificador | ninguna `customer_id*` en la matriz     |
| Cobertura                   | 14.0 % ± 0.1 con el catálogo de 4         |

Cada control devuelve (ok, detalle). El script sale con código 1 si alguno
falla: **el fallo silencioso es el enemigo**. Los mismos controles viven como
pruebas en `analytics/tests/`; aquí están juntos para poder enseñarlos de una
sola pasada en el pitch.

Uso: .venv/bin/python analytics/calidad.py
"""
from __future__ import annotations

import os
import sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.metricas import acc_baseline, cobertura  # noqa: E402
from pipeline.features import (  # noqa: E402
    DATA,
    _conexion,
    columnas_features,
    construir,
    labels_intencion,
)
from pipeline.mapas import ACCIONES, CATALOGO_DEMO, CORTE_DEMO, CORTES_ROLLING  # noqa: E402

BASELINES = {"2026-05-30": 25.63, "2026-06-09": 41.62, "2026-06-14": 33.64, "2026-05-23": 45.89}
TOL_BASELINE = 0.05
COBERTURA_ESPERADA = 14.0
TOL_COBERTURA = 0.1


# ---------------------------------------------------------------------------
def control_integridad(con) -> tuple[bool, pd.DataFrame]:
    filas = []
    for tabla, col in (("app_events", "customer_id"), ("financial_actions", "customer_id"),
                       ("nudges", "customer_id")):
        n = con.execute(
            f"""SELECT count(*) FROM {tabla} t
                LEFT JOIN customers c ON c.customer_id = t.{col}
                WHERE c.customer_id IS NULL"""
        ).fetchone()[0]
        filas.append(dict(chequeo=f"{tabla}.{col} huérfanos", n=int(n), criterio=0))
    filas.append(dict(chequeo="nudge_outcomes sin nudge", criterio=0, n=int(con.execute(
        """SELECT count(*) FROM nudge_outcomes o
           LEFT JOIN nudges n ON n.nudge_id = o.nudge_id WHERE n.nudge_id IS NULL"""
    ).fetchone()[0])))
    filas.append(dict(chequeo="nudges sin outcome", criterio=0, n=int(con.execute(
        """SELECT count(*) FROM nudges n
           LEFT JOIN nudge_outcomes o ON o.nudge_id = n.nudge_id WHERE o.nudge_id IS NULL"""
    ).fetchone()[0])))
    d = pd.DataFrame(filas)[["chequeo", "n", "criterio"]]
    return bool((d.n == 0).all()), d


def control_canario(con) -> tuple[bool, pd.DataFrame]:
    filas = []
    for corte, esp in BASELINES.items():
        obt = acc_baseline(corte, con=con)
        filas.append(dict(corte=corte, obtenido=obt, esperado=esp,
                          delta=round(abs(obt - esp), 4), tol=TOL_BASELINE))
    d = pd.DataFrame(filas)
    return bool((d.delta < TOL_BASELINE).all()), d


def control_distribucion(con) -> tuple[bool, pd.DataFrame]:
    """La distribución de la primera acción no puede desmoronarse entre cortes.

    Criterio: ninguna clase cambia más de 20 pp entre el corte más alto y el
    más bajo, y las 8 clases están presentes en los tres cortes.
    """
    filas = {}
    for c in CORTES_ROLLING:
        lab = labels_intencion(c, con=con)
        act = lab[lab.activo == 1]
        filas[c] = (act.y_primera.value_counts(normalize=True) * 100).reindex(ACCIONES).fillna(0)
    d = pd.DataFrame(filas).round(2)
    d["rango_pp"] = (d.max(axis=1) - d.min(axis=1)).round(2)
    ok = bool((d[list(CORTES_ROLLING)] > 0).all().all() and (d.rango_pp <= 20).all())
    return ok, d


def _conexion_con_evento_futuro(asof: str, customer_id: int, screen: str):
    """Conexión idéntica salvo por un evento inyectado en `asof + 1h`."""
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    for t in ("customers", "financial_actions", "nudges", "nudge_outcomes"):
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{os.path.join(DATA, t + '.parquet')}')")
    ruta = os.path.join(DATA, "app_events.parquet")
    con.execute(
        f"""
        CREATE VIEW app_events AS
        SELECT * FROM read_parquet('{ruta}')
        UNION ALL
        SELECT 999999999::INT32 AS event_id, {customer_id}::INT32 AS customer_id,
               TIMESTAMP '{asof}' + INTERVAL 1 HOUR AS event_ts,
               '{screen}' AS screen, 'start' AS action
        """
    )
    return con


def control_sin_fuga(con, asof: str = CORTE_DEMO) -> tuple[bool, pd.DataFrame]:
    """Prueba negativa: se inyecta un evento en asof+1h y NADA puede moverse."""
    base = construir(asof, con=con).set_index("customer_id")
    cid = int(base.index[0])
    con2 = _conexion_con_evento_futuro(asof, cid, "savings_cajita")
    try:
        con_fut = construir(asof, con=con2).set_index("customer_id")
    finally:
        con2.close()
    F = columnas_features(base.reset_index())
    difs = []
    for c in F:
        a, b = base[c], con_fut[c]
        n = int((a.to_numpy() != b.to_numpy()).sum())
        if n:
            difs.append(dict(feature=c, filas_distintas=n))
    d = pd.DataFrame(difs) if difs else pd.DataFrame(columns=["feature", "filas_distintas"])
    # y la prueba positiva: con el evento en asof-1h SÍ se mueve (si no, la
    # prueba negativa no demuestra nada, solo que el pipeline ignora el evento)
    con3 = _conexion_con_evento_futuro(
        str(pd.Timestamp(asof) - pd.Timedelta(hours=2)), cid, "savings_cajita")
    try:
        pasado = construir(asof, con=con3).set_index("customer_id")
    finally:
        con3.close()
    movio = int(sum((base[c].to_numpy() != pasado[c].to_numpy()).sum() for c in F))
    d.attrs["control_positivo_filas_movidas"] = movio
    return bool(len(d) == 0 and movio > 0), d


def control_sin_identificadores(con, asof: str = CORTE_DEMO) -> tuple[bool, pd.DataFrame]:
    df = construir(asof, con=con)
    F = columnas_features(df)
    ids = [c for c in df.columns if c.startswith("customer_id")]
    d = pd.DataFrame([
        dict(chequeo="columnas de features", valor=len(F), criterio=82),
        dict(chequeo="columnas customer_id* en la matriz",
             valor=len([c for c in F if "customer_id" in c]), criterio=0),
        dict(chequeo="customer_id_2 (artefacto de LEFT JOIN USING)",
             valor=int("customer_id_2" in df.columns), criterio=0),
        dict(chequeo="identificadores fuera de la matriz", valor=len(ids), criterio=1),
    ])
    return bool(len(F) == 82 and not any("customer_id" in c for c in F)
                and "customer_id_2" not in df.columns), d


def control_cobertura(con) -> tuple[bool, pd.DataFrame]:
    pct, motivos = cobertura(CORTE_DEMO, CATALOGO_DEMO, con=con)
    d = motivos.rename("clientes").to_frame()
    d["pct"] = (100 * d.clientes / d.clientes.sum()).round(2)
    d.attrs["cobertura"] = pct
    return bool(abs(pct - COBERTURA_ESPERADA) <= TOL_COBERTURA), d


# ---------------------------------------------------------------------------
CONTROLES = [
    ("Integridad de uniones", control_integridad, "0 huérfanos en las tres tablas"),
    ("Canario de baselines", control_canario, "los cuatro valores dentro de ±0.05"),
    ("Distribución de clases", control_distribucion, "estable entre los tres cortes"),
    ("Sin fuga", control_sin_fuga, "ninguna feature se mueve con un evento futuro"),
    ("Sin columnas de identificador", control_sin_identificadores, "ninguna customer_id* en la matriz"),
    ("Cobertura", control_cobertura, "14.0 % ± 0.1 con el catálogo de 4"),
]


def main() -> int:
    con = _conexion()
    fallos = []
    try:
        for i, (nombre, fn, criterio) in enumerate(CONTROLES, 1):
            ok, detalle = fn(con)
            marca = "OK    " if ok else "FALLA "
            print("=" * 88)
            print(f"{marca} {i}/{len(CONTROLES)} · {nombre}   [{criterio}]")
            print("=" * 88)
            print(detalle.to_string())
            if "control_positivo_filas_movidas" in detalle.attrs:
                print(f"  control positivo (evento en asof−2h): "
                      f"{detalle.attrs['control_positivo_filas_movidas']:,} celdas se mueven "
                      "→ el pipeline SÍ ve el pasado, así que el cero de arriba significa algo")
            if "cobertura" in detalle.attrs:
                print(f"  cobertura = {detalle.attrs['cobertura']:.2f} %  "
                      f"(esperado {COBERTURA_ESPERADA} ± {TOL_COBERTURA})")
            print()
            if not ok:
                fallos.append(nombre)
        if fallos:
            print(f"CONTROLES FALLIDOS: {fallos}")
            return 1
        print(f"los {len(CONTROLES)} controles en verde")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
