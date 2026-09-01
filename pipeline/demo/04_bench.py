"""
04_bench.py — Mide la viabilidad de servir la ficha en una API durante el pitch.

Compara 4 backends para la consulta "dame TODO de un customer_id a una fecha":
  A) DuckDB leyendo los parquets en cada query (sin estado)
  B) DuckDB con las tablas cargadas en su memoria (CREATE TABLE)
  C) pandas en memoria con índice por customer_id  (recon/demo/ficha.py)
  D) artefacto precalculado (JSON por cliente en un dict)

Uso: /tmp/hackenv/bin/python 04_bench.py
"""
import gc
import json
import os
import time

import duckdb
import numpy as np
import pandas as pd

BASE = "/Users/miguel.soto/Downloads/hackathon/d3_intent/data"
HERE = os.path.dirname(os.path.abspath(__file__))
TABLAS = ["customers", "app_events", "financial_actions", "nudges", "nudge_outcomes"]
ASOF = "2026-06-16"
N = 60


def p95(xs):
    return float(np.percentile(xs, 95))


def rep(nombre, xs, extra=""):
    xs = np.array(xs) * 1000
    print(f"  {nombre:52s} p50={np.median(xs):8.2f} ms  p95={p95(xs):8.2f} ms  "
          f"max={xs.max():8.2f} ms {extra}")


def main():
    print("=" * 108)
    print("1 · TAMAÑO EN DISCO Y EN MEMORIA")
    print("=" * 108)
    tot_d = tot_m = 0
    dfs = {}
    for t in TABLAS:
        p = f"{BASE}/{t}.parquet"
        d = os.path.getsize(p)
        t0 = time.perf_counter()
        df = pd.read_parquet(p)
        dt = time.perf_counter() - t0
        m = df.memory_usage(deep=True).sum()
        dfs[t] = df
        tot_d += d
        tot_m += m
        print(f"  {t:20s} {len(df):>9,} filas  disco {d/1e6:7.2f} MB  "
              f"RAM(pandas) {m/1e6:8.2f} MB  read_parquet {dt*1000:6.0f} ms")
    print(f"  {'TOTAL':20s} {'':>9}         disco {tot_d/1e6:7.2f} MB  RAM(pandas) {tot_m/1e6:8.2f} MB")
    print(f"  -> cabe de sobra en un proceso Python (referencia: laptop con 16 GB).")
    del dfs
    gc.collect()

    cids = pd.read_parquet(f"{BASE}/customers.parquet", columns=["customer_id"])["customer_id"]
    muestra = cids.sample(N, random_state=7).tolist()

    print()
    print("=" * 108)
    print(f"2 · LATENCIA DE 'dame todo de un customer_id' (asof={ASOF}, {N} clientes al azar)")
    print("=" * 108)

    SQL = """
      SELECT * FROM customers WHERE customer_id = {c};
      SELECT * FROM app_events WHERE customer_id = {c} AND event_ts < TIMESTAMP '{a}';
      SELECT * FROM financial_actions WHERE customer_id = {c} AND action_ts < TIMESTAMP '{a}';
      SELECT * FROM nudges WHERE customer_id = {c} AND shown_ts < TIMESTAMP '{a}';
    """

    # ---- A · DuckDB sobre parquets (vistas, sin estado) ----
    t0 = time.perf_counter()
    ca = duckdb.connect()
    for t in TABLAS:
        ca.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{BASE}/{t}.parquet')")
    boot_a = time.perf_counter() - t0
    xs = []
    for c in muestra:
        t0 = time.perf_counter()
        for q in SQL.format(c=c, a=ASOF).strip().split(";"):
            if q.strip():
                ca.execute(q).df()
        xs.append(time.perf_counter() - t0)
    rep("A · DuckDB VIEW sobre parquets", xs, f"| arranque {boot_a*1000:.0f} ms")

    # ---- B · DuckDB con tablas materializadas en RAM ----
    t0 = time.perf_counter()
    cb = duckdb.connect()
    for t in TABLAS:
        cb.execute(f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{BASE}/{t}.parquet')")
    boot_b = time.perf_counter() - t0
    xs = []
    for c in muestra:
        t0 = time.perf_counter()
        for q in SQL.format(c=c, a=ASOF).strip().split(";"):
            if q.strip():
                cb.execute(q).df()
        xs.append(time.perf_counter() - t0)
    rep("B · DuckDB CREATE TABLE en RAM", xs, f"| arranque {boot_b*1000:.0f} ms")

    # ---- C · pandas en memoria (ficha.Store, ficha completa ya agregada) ----
    from ficha import Store
    t0 = time.perf_counter()
    st = Store()
    boot_c = time.perf_counter() - t0
    xs = []
    for c in muestra:
        t0 = time.perf_counter()
        st.ficha(c, ASOF)
        xs.append(time.perf_counter() - t0)
    rep("C · pandas Store.ficha() (ficha COMPLETA, no solo rows)", xs, f"| arranque {boot_c*1000:.0f} ms")

    # ---- D · artefacto precalculado ----
    print()
    print("=" * 108)
    print("3 · ARTEFACTO PRECALCULADO — fichas.json / fichas.parquet")
    print("=" * 108)
    t0 = time.perf_counter()
    fichas = {int(c): st.ficha(c, ASOF) for c in muestra}
    dt = time.perf_counter() - t0
    blob = json.dumps(fichas, ensure_ascii=False)
    por_ficha = len(blob.encode()) / len(fichas)
    print(f"  construir {len(fichas)} fichas: {dt:.2f} s  ->  {dt/len(fichas)*1000:.1f} ms/ficha")
    print(f"  proyección 38,000 fichas: {dt/len(fichas)*38000:.0f} s de precálculo")
    print(f"  peso medio de una ficha JSON: {por_ficha/1024:.1f} KB")
    print(f"  proyección fichas.json (38,000 clientes, 1 corte): {por_ficha*38000/1e6:.1f} MB")
    print(f"  proyección con 3 cortes: {por_ficha*38000*3/1e6:.1f} MB")

    d = json.dumps(fichas[int(muestra[0])], ensure_ascii=False)
    print(f"  ejemplo: la ficha del cliente {muestra[0]} pesa {len(d.encode())/1024:.1f} KB")

    xs = []
    for c in muestra:
        t0 = time.perf_counter()
        _ = fichas[int(c)]
        xs.append(time.perf_counter() - t0)
    rep("D · dict precalculado en RAM (lookup puro)", xs)

    # ---- variante compacta: solo lo que la UI necesita ----
    def compacta(f):
        return {"perfil": f["perfil"], "decision": f["decision"],
                "mov_30d": f["movimientos"]["agregado_30d"],
                "ult_mov": f["movimientos"]["ultimos"][:5],
                "ult_pantallas": f["navegacion"]["ultimas_pantallas"][:8],
                "nudges_por_tipo": f["nudges"]["por_tipo"], "opt_out": f["nudges"]["opt_out"]}
    b2 = json.dumps({k: compacta(v) for k, v in fichas.items()}, ensure_ascii=False)
    print(f"  variante COMPACTA (lo que realmente pinta la UI): "
          f"{len(b2.encode())/len(fichas)/1024:.1f} KB/ficha -> "
          f"{len(b2.encode())/len(fichas)*38000/1e6:.1f} MB para 38,000")


def bench_sqlite():
    """E · SQLite precalculado (una tabla clave-valor customer_id|corte -> ficha JSON)."""
    import sqlite3, tempfile, json, time
    import numpy as np, pandas as pd
    from ficha import Store
    st = Store()
    cids = pd.read_parquet(f"{BASE}/customers.parquet", columns=["customer_id"])["customer_id"]
    muestra = cids.sample(N, random_state=7).tolist()
    p = os.path.join(tempfile.gettempdir(), "demo_fichas.sqlite")
    if os.path.exists(p):
        os.remove(p)
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE fichas (k TEXT PRIMARY KEY, j TEXT)")
    t0 = time.perf_counter()
    con.executemany("INSERT INTO fichas VALUES (?,?)",
                    [(f"{c}|{ASOF}", json.dumps(st.ficha(c, ASOF), ensure_ascii=False)) for c in muestra])
    con.commit()
    build = time.perf_counter() - t0
    xs = []
    for c in muestra:
        t0 = time.perf_counter()
        r = con.execute("SELECT j FROM fichas WHERE k=?", (f"{c}|{ASOF}",)).fetchone()
        json.loads(r[0])
        xs.append(time.perf_counter() - t0)
    print()
    print("=" * 108)
    print("4 · SQLITE PRECALCULADO")
    print("=" * 108)
    print(f"  construir {N} filas: {build:.2f} s  |  archivo {os.path.getsize(p)/1e6:.2f} MB "
          f"-> proyeccion 38,000: {os.path.getsize(p)/N*38000/1e6:.0f} MB")
    rep("E · SQLite SELECT + json.loads", xs)


if __name__ == "__main__":
    main()
    bench_sqlite()
