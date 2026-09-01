"""
01_scan_candidatos.py — Escanea las 38,000 fichas a una fecha de corte y clasifica
a cada cliente según el arquetipo narrativo que puede contar en el pitch.

Salida: recon/demo/out/scan_<asof>.csv  (una fila por cliente, con las banderas)
        + un resumen por arquetipo en stdout.

Uso: /tmp/hackenv/bin/python 01_scan_candidatos.py 2026-06-09
"""
import os
import sys

import duckdb
import pandas as pd

BASE = "/Users/miguel.soto/Downloads/hackathon/d3_intent/data"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)

NUDGE_SCREEN = {"savings_goal": "savings_cajita", "limit_increase": "limit_increase",
                "bill_reminder": "bill_payment", "loan_offer": "loan_simulation",
                "invest_start": "investments", "payroll_portability": "home"}


def scan(asof_s):
    asof = pd.Timestamp(asof_s)
    c = duckdb.connect()
    for t in ["customers", "app_events", "financial_actions", "nudges"]:
        c.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{BASE}/{t}.parquet')")

    # --- recencia por pantalla (horas) y start en 24h
    rec = c.execute(f"""
        SELECT customer_id, screen,
               date_diff('second', max(event_ts), TIMESTAMP '{asof}')/3600.0 AS h,
               max(CASE WHEN action='start' AND event_ts >= TIMESTAMP '{asof}' - INTERVAL 24 HOUR
                        THEN 1 ELSE 0 END) AS start24
        FROM app_events WHERE event_ts < TIMESTAMP '{asof}'
        GROUP BY 1,2""").df()
    h = rec.pivot(index="customer_id", columns="screen", values="h")
    s24 = rec.pivot(index="customer_id", columns="screen", values="start24")

    # --- exposiciones por tipo de nudge + opt out
    exp = c.execute(f"""
        SELECT customer_id, nudge_type, count(*) n, max(exposure_no) mx,
               sum(engaged::int) eng
        FROM nudges WHERE shown_ts < TIMESTAMP '{asof}' GROUP BY 1,2""").df()
    expn = exp.pivot(index="customer_id", columns="nudge_type", values="n")
    expe = exp.pivot(index="customer_id", columns="nudge_type", values="eng")
    optout = c.execute(f"""SELECT customer_id, max(opted_out_after::int) oo FROM nudges
        WHERE shown_ts < TIMESTAMP '{asof}' GROUP BY 1""").df().set_index("customer_id")["oo"]

    # --- riqueza de datos
    rich = c.execute(f"""
        SELECT customer_id,
          sum(CASE WHEN event_ts >= TIMESTAMP '{asof}' - INTERVAL 24 HOUR THEN 1 ELSE 0 END) ev1,
          sum(CASE WHEN event_ts >= TIMESTAMP '{asof}' - INTERVAL 7 DAY THEN 1 ELSE 0 END) ev7,
          sum(CASE WHEN event_ts >= TIMESTAMP '{asof}' - INTERVAL 30 DAY THEN 1 ELSE 0 END) ev30,
          count(*) ev_tot
        FROM app_events WHERE event_ts < TIMESTAMP '{asof}' GROUP BY 1""").df().set_index("customer_id")
    fa = c.execute(f"""
        SELECT customer_id,
          sum(CASE WHEN action_ts >= TIMESTAMP '{asof}' - INTERVAL 30 DAY THEN 1 ELSE 0 END) fa30,
          count(*) fa_tot
        FROM financial_actions WHERE action_ts < TIMESTAMP '{asof}' GROUP BY 1""").df().set_index("customer_id")

    cust = c.execute("SELECT * FROM customers").df().set_index("customer_id")
    df = cust.copy()
    df["fragil"] = (df.card_utilization_pct > 70) | (df.days_negative_90d >= 3)
    dom = asof.day
    df["dias_a_payday"] = df.payday_day_of_month.apply(
        lambda p: min((p - dom) % 30, (dom - p) % 30))
    df["ventana_payday"] = df.dias_a_payday <= 2

    for nt, scr in NUDGE_SCREEN.items():
        hh = h[scr].reindex(df.index) if scr in h else pd.Series(index=df.index, dtype=float)
        df[f"h_{nt}"] = hh
        df[f"on_time_{nt}"] = hh <= 24
        df[f"warm_{nt}"] = (hh > 24) & (hh <= 168)
        df[f"start24_{nt}"] = (s24[scr].reindex(df.index).fillna(0) == 1) if scr in s24 else False
        df[f"exp_{nt}"] = expn[nt].reindex(df.index).fillna(0).astype(int) if nt in expn else 0
        df[f"eng_{nt}"] = expe[nt].reindex(df.index).fillna(0).astype(int) if nt in expe else 0

    df["opt_out"] = optout.reindex(df.index).fillna(0).astype(bool)
    for col in ["ev1", "ev7", "ev30", "ev_tot"]:
        df[col] = rich[col].reindex(df.index).fillna(0).astype(int)
    for col in ["fa30", "fa_tot"]:
        df[col] = fa[col].reindex(df.index).fillna(0).astype(int)
    df["n_nudges"] = expn.reindex(df.index).sum(axis=1).fillna(0).astype(int)
    df["senal_fresca_alguna"] = df[[f"on_time_{n}" for n in NUDGE_SCREEN]].any(axis=1)
    df["senal_7d_alguna"] = df[[f"warm_{n}" for n in NUDGE_SCREEN]].any(axis=1) | df["senal_fresca_alguna"]

    p = os.path.join(OUT, f"scan_{asof_s[:10]}.csv")
    df.reset_index().to_csv(p, index=False)
    print(f"-> {p}   ({len(df)} clientes)")
    return df


if __name__ == "__main__":
    asof = sys.argv[1] if len(sys.argv) > 1 else "2026-06-09"
    df = scan(asof)
    print(f"\n== resumen corte {asof} ==")
    print(f"clientes con >=1 senal on_time (<=24h): {df.senal_fresca_alguna.sum()} "
          f"({df.senal_fresca_alguna.mean()*100:.1f}%)")
    print(f"clientes con >=1 senal <=7d          : {df.senal_7d_alguna.sum()} "
          f"({df.senal_7d_alguna.mean()*100:.1f}%)")
    print(f"fragiles                             : {df.fragil.sum()} ({df.fragil.mean()*100:.1f}%)")
    print(f"en ventana payday (<=2d)             : {df.ventana_payday.sum()} ({df.ventana_payday.mean()*100:.1f}%)")
    print(f"con opt_out previo                   : {df.opt_out.sum()}")
    print("\nsenal on_time por tipo de nudge:")
    for n in NUDGE_SCREEN:
        print(f"  {n:22s} {df[f'on_time_{n}'].sum():6d}   fragiles con senal: {(df[f'on_time_{n}'] & df.fragil).sum():5d}"
              f"   cupo agotado(exp>=2): {(df[f'on_time_{n}'] & (df[f'exp_{n}']>=2)).sum():5d}")
