"""Utilidades compartidas de recon. Uso: from common import *"""
import os
import duckdb
import pandas as pd

BASE = "/Users/miguel.soto/Downloads/hackathon/d3_intent/data"
OUT = "/Users/miguel.soto/Downloads/hackathon/recon/out"
os.makedirs(OUT, exist_ok=True)

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 200)

START = pd.Timestamp("2026-03-01")   # del generador
DAYS = 120


def con():
    """Conexion duckdb con las 5 tablas registradas como vistas."""
    c = duckdb.connect()
    for t in ["customers", "app_events", "financial_actions", "nudges", "nudge_outcomes"]:
        c.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{BASE}/{t}.parquet')")
    return c


def load(name):
    return pd.read_parquet(f"{BASE}/{name}.parquet")


def dump(df, name, index=False):
    p = os.path.join(OUT, name + ".csv")
    df.to_csv(p, index=index)
    print(f"  -> {p}")
    return df


def show(title, df, index=False):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    print(df.to_string(index=index))
