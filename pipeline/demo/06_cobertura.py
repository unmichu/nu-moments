"""
06_cobertura.py — Qué se vería VACÍO en la UI y qué fracción de la base recibe oferta.

Responde dos preguntas del demo:
  a) para cada campo de la ficha, ¿en qué % de clientes está vacío?
  b) aplicando la política a los 38,000 clientes, ¿cuántos reciben oferta y cuántos silencio?

Uso: /tmp/hackenv/bin/python 06_cobertura.py [corte]
"""
import os
import sys

import duckdb
import numpy as np
import pandas as pd

BASE = "/Users/miguel.soto/Downloads/hackathon/d3_intent/data"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
NUDGES = ["savings_goal", "limit_increase", "bill_reminder", "loan_offer",
          "invest_start", "payroll_portability"]
PRIORIDAD = ["savings_goal", "bill_reminder", "payroll_portability",
             "invest_start", "loan_offer", "limit_increase"]


def main(asof):
    p = os.path.join(OUT, f"scan_{asof}.csv")
    if not os.path.exists(p):
        os.system(f'cd {HERE} && /tmp/hackenv/bin/python 01_scan_candidatos.py {asof} >/dev/null')
    d = pd.read_csv(p)
    n = len(d)
    c = duckdb.connect()
    c.execute(f"CREATE VIEW customers AS SELECT * FROM read_parquet('{BASE}/customers.parquet')")

    print("=" * 96)
    print(f"A · CAMPOS VACÍOS EN LA UI  (corte {asof}, n={n:,})")
    print("=" * 96)
    filas = [
        ("nps_last_score nulo", d.nps_last_score.isna().sum()),
        ("sin NINGÚN producto contratado", (d[["has_cuenta_nu", "has_cajita_turbo", "has_personal_loan",
                                               "has_investments", "has_payroll_portability"]].sum(axis=1) == 0).sum()),
        ("sin has_cuenta_nu", (~d.has_cuenta_nu).sum()),
        ("0 eventos de app en 24h", (d.ev1 == 0).sum()),
        ("0 eventos de app en 7d", (d.ev7 == 0).sum()),
        ("0 eventos de app en 30d", (d.ev30 == 0).sum()),
        ("0 acciones financieras en 30d", (d.fa30 == 0).sum()),
        ("nunca vio un nudge", (d.n_nudges == 0).sum()),
        ("SIN señal fresca (>24h) en toda pantalla", (~d.senal_fresca_alguna).sum()),
        ("SIN señal ni siquiera a 7d", (~d.senal_7d_alguna).sum()),
    ]
    for lab, v in filas:
        print(f"  {lab:46s} {int(v):>7,}   {v/n*100:5.1f}%")

    print("\n  recencia por pantalla acoplada — % de clientes SIN ninguna visita histórica:")
    for t in NUDGES:
        vac = d[f"h_{t}"].isna().sum()
        print(f"    {t:22s} {vac:>7,}   {vac/n*100:5.1f}%   (on_time: {d[f'on_time_{t}'].sum():,})")

    print("\n" + "=" * 96)
    print("B · INCOHERENCIAS DEL DATASET QUE ROMPERÍAN LA UI")
    print("=" * 96)
    inc = c.execute("""SELECT count(*) FROM customers WHERE
      (income_band='<8k' AND monthly_income_est_mxn>=8000) OR
      (income_band='8k-15k' AND (monthly_income_est_mxn<8000 OR monthly_income_est_mxn>=15000)) OR
      (income_band='15k-30k' AND (monthly_income_est_mxn<15000 OR monthly_income_est_mxn>=30000)) OR
      (income_band='30k-60k' AND (monthly_income_est_mxn<30000 OR monthly_income_est_mxn>=60000)) OR
      (income_band='>60k' AND monthly_income_est_mxn<60000)""").fetchone()[0]
    print(f"  income_band NO coincide con monthly_income_est_mxn : {inc:,}  ({inc/n*100:.1f}%)")
    edad = c.execute("SELECT count(*) FROM customers WHERE age - tenure_months/12.0 < 18").fetchone()[0]
    print(f"  antigüedad implica alta antes de los 18 años       : {edad:,}  ({edad/n*100:.1f}%)")
    ing = c.execute("SELECT count(*) FROM customers WHERE avg_balance_mxn > monthly_income_est_mxn*3").fetchone()[0]
    print(f"  saldo promedio > 3x el ingreso mensual             : {ing:,}  ({ing/n*100:.1f}%)")

    print("\n" + "=" * 96)
    print(f"C · DECISIÓN DE LA POLÍTICA SOBRE LOS {n:,} CLIENTES  (corte {asof})")
    print("=" * 96)
    dec = pd.Series("silencio:sin_senal", index=d.index)
    fresco = {t: (d[f"on_time_{t}"] | d[f"warm_{t}"]) & (d[f"exp_{t}"] < 2) for t in NUDGES}
    hay = pd.Series(False, index=d.index)
    for t in NUDGES:
        hay |= (d[f"on_time_{t}"] | d[f"warm_{t}"])
    dec[hay] = "silencio:cupo_agotado"
    veto = d.on_time_limit_increase | d.warm_limit_increase
    dec[hay & d.fragil & veto] = "silencio:veto_fragilidad"
    # asignar el mejor candidato (on_time primero, luego prioridad salud)
    for pref_on in (True, False):
        for t in PRIORIDAD:
            m = (d[f"on_time_{t}"] if pref_on else d[f"warm_{t}"]) & (d[f"exp_{t}"] < 2)
            if t == "limit_increase":
                m = m & ~d.fragil
            m = m & dec.str.startswith("silencio")
            dec[m] = t
    dec[d.opt_out] = "silencio:opt_out"
    vc = dec.value_counts()
    for k, v in vc.items():
        print(f"  {k:28s} {v:>7,}   {v/n*100:5.1f}%")
    envia = (~dec.str.startswith("silencio")).sum()
    print(f"  {'-'*28} {'-'*7}")
    print(f"  {'RECIBE OFERTA':28s} {envia:>7,}   {envia/n*100:5.1f}%")
    print(f"  {'SILENCIO':28s} {n-envia:>7,}   {(n-envia)/n*100:5.1f}%")
    return dec


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-06-16")
