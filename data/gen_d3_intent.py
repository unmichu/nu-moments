"""
Desafio 3 · Proxima intencao e o momento certo
Gerador sintetico reproduzivel. Nenhum dado real de cliente.

Duas perguntas ficam abertas de proposito e sao respondidas pela equipe:
  1. qual acao financeira o cliente esta prestes a querer fazer
  2. se este e o momento de falar com ele, dado que repetir cansa
E uma terceira, que e o coracao do desafio: o que estamos otimizando.
Os dados carregam o conflito entre engajamento, saude financeira e receita.

Uso:  python gen_d3_intent.py [--customers 38000] [--out ./data]
"""
import argparse, os
import numpy as np
import pandas as pd

SEED = 20260806
DAYS = 120
START = pd.Timestamp("2026-03-01")

ACTIONS = ["spei_out", "bill_payment", "deposit_in", "savings_move",
           "loan_request", "limit_increase_request", "card_payment", "investment_buy"]
SCREEN_OF = {
    "spei_out": "transfer_spei", "bill_payment": "bill_payment", "deposit_in": "home",
    "savings_move": "savings_cajita", "loan_request": "loan_simulation",
    "limit_increase_request": "limit_increase", "card_payment": "card_statement",
    "investment_buy": "investments",
}
SCREENS = ["home", "transfer_spei", "bill_payment", "card_statement", "savings_cajita",
           "loan_simulation", "limit_increase", "investments", "support", "card_settings"]
NUDGES = ["savings_goal", "limit_increase", "bill_reminder", "loan_offer",
          "invest_start", "payroll_portability"]
NUDGE_INTENT = {"savings_goal": "savings_move", "limit_increase": "limit_increase_request",
                "bill_reminder": "bill_payment", "loan_offer": "loan_request",
                "invest_start": "investment_buy", "payroll_portability": "deposit_in"}
SURFACES = ["home_card", "push", "in_app_modal"]
BANDS = ["<8k", "8k-15k", "15k-30k", "30k-60k", ">60k"]
STATES = ["CDMX", "Estado de Mexico", "Jalisco", "Nuevo Leon", "Puebla",
          "Guanajuato", "Veracruz", "Chihuahua", "Baja California", "Queretaro"]


def build(n, rng):
    cust = np.arange(6_000_000, 6_000_000 + n)
    tenure = rng.integers(1, 61, n)
    age = np.clip(rng.normal(35, 11, n), 18, 80).round().astype(int)
    band = rng.choice(BANDS, n, p=[0.21, 0.28, 0.27, 0.17, 0.07])
    band_ix = pd.Series({b: i for i, b in enumerate(BANDS)}).reindex(band).to_numpy()
    income = np.round(np.clip(rng.lognormal(9.2, 0.5, n) * (1 + 0.45 * band_ix), 3500, 260000), -2)
    payday = rng.choice([1, 15, 30], n, p=[0.28, 0.44, 0.28])

    # tracos latentes que geram intencao
    saver = rng.random(n) < 0.29
    borrower = rng.random(n) < 0.21
    biller = rng.random(n) < 0.46
    investor = rng.random(n) < 0.12
    engagement = np.round(np.clip(rng.beta(2.4, 2.1, n) * 100, 1, 100), 1)

    # condicao financeira, base do conflito de objetivo
    util = np.round(np.clip(rng.beta(2.0, 2.8, n) * 100 + 16 * borrower, 0, 100), 1)
    days_neg = rng.poisson(np.clip(0.6 + 0.09 * util / 10 - 2.2 * saver, 0.05, None))
    savings_rate = np.round(np.clip(rng.beta(2.0, 6.0, n) * 100 + 14 * saver - 0.10 * util, 0, 100), 1)
    balance = np.round(np.clip(rng.lognormal(7.4, 1.05, n) * (1 + 1.3 * saver), 0, 600000), 0)
    fragile = (util > 70) | (days_neg >= 3)
    revenue = np.round(np.clip(income * rng.uniform(0.006, 0.05, n) + util * 12 + 90 * borrower, 20, 60000), 0)
    nps = np.where(rng.random(n) < 0.31,
                   np.clip(rng.normal(np.where(fragile, 6.2, 8.4), 1.9, n), 0, 10).round(), np.nan)

    customers = pd.DataFrame({
        "customer_id": cust, "tenure_months": tenure, "age": age, "state": rng.choice(STATES, n),
        "income_band": band, "monthly_income_est_mxn": income, "payday_day_of_month": payday,
        "engagement_score": engagement, "avg_balance_mxn": balance,
        "card_utilization_pct": util, "days_negative_90d": days_neg,
        "savings_rate_90d_pct": savings_rate, "revenue_ltm_mxn": revenue,
        "nps_last_score": nps,
        "has_cuenta_nu": rng.random(n) < 0.58, "has_cajita_turbo": saver & (rng.random(n) < 0.52),
        "has_personal_loan": borrower & (rng.random(n) < 0.31),
        "has_investments": investor & (rng.random(n) < 0.44),
        "has_payroll_portability": rng.random(n) < 0.19,
    })

    # ---------------- acoes financeiras ----------------
    rate = {
        "spei_out": 0.85 + 0.60 * engagement / 100,
        "bill_payment": 0.20 + 1.10 * biller,
        "deposit_in": 0.70 + 0.35 * saver,
        "savings_move": 0.09 + 0.95 * saver,
        "loan_request": 0.02 + 0.16 * borrower,
        "limit_increase_request": 0.02 + 0.19 * borrower,
        "card_payment": 0.36 + 0.18 * (util > 30),
        "investment_buy": 0.02 + 0.55 * investor,
    }
    months = DAYS / 30.0
    parts = []
    for a in ACTIONS:
        k = rng.poisson(np.clip(rate[a] * months, 0.01, None))
        idx = np.repeat(np.arange(n), k)
        if idx.size == 0:
            continue
        d = rng.integers(0, DAYS, idx.size).astype(float)
        # efeito do dia de pagamento: deposito, poupanca e conta caem perto do payday
        if a in ("deposit_in", "savings_move", "bill_payment"):
            dom = (START + pd.to_timedelta(d, "D")).day
            pull = (dom - payday[idx]) % 30
            move = rng.random(idx.size) < 0.62
            d = np.where(move, np.clip(d - pull + rng.integers(0, 3, idx.size), 0, DAYS - 1), d)
        h = rng.choice(np.arange(6, 24), idx.size)
        ts = START + pd.to_timedelta(d, "D") + pd.to_timedelta(h, "h") + pd.to_timedelta(rng.integers(0, 3600, idx.size), "s")
        amt = {
            "spei_out": income[idx] * rng.uniform(0.01, 0.30, idx.size),
            "bill_payment": rng.uniform(180, 2600, idx.size),
            "deposit_in": income[idx] * rng.uniform(0.35, 1.05, idx.size),
            "savings_move": income[idx] * rng.uniform(0.02, 0.22, idx.size),
            "loan_request": income[idx] * rng.uniform(1.0, 6.0, idx.size),
            "limit_increase_request": income[idx] * rng.uniform(0.5, 3.0, idx.size),
            "card_payment": income[idx] * rng.uniform(0.05, 0.45, idx.size),
            "investment_buy": income[idx] * rng.uniform(0.05, 0.6, idx.size),
        }[a]
        parts.append(pd.DataFrame({
            "customer_id": cust[idx], "_ci": idx, "action_ts": ts, "action_type": a,
            "amount_mxn": np.round(np.clip(amt, 20, 900000), 2),
            "is_recurring": rng.random(idx.size) < (0.55 if a in ("bill_payment", "deposit_in") else 0.08),
        }))
    fa = pd.concat(parts, ignore_index=True).sort_values("action_ts").reset_index(drop=True)
    fa.insert(0, "action_id", np.arange(1, len(fa) + 1))

    # ---------------- eventos de app ----------------
    # precursores: a maior parte das acoes tem visita a tela correspondente antes
    pre = fa.sample(frac=0.66, random_state=11)
    reps = rng.integers(1, 3, len(pre))
    pi = np.repeat(np.arange(len(pre)), reps)
    lead_h = rng.gamma(2.0, 11, pi.size)
    ev_ts = pre["action_ts"].to_numpy()[pi] - pd.to_timedelta(np.clip(lead_h, 0.2, 72), "h")
    ev_screen = pd.Series(SCREEN_OF).reindex(pre["action_type"].to_numpy()[pi]).to_numpy()
    ev_action = np.where(rng.random(pi.size) < 0.34, "start", "view")
    prec = pd.DataFrame({
        "customer_id": pre["customer_id"].to_numpy()[pi], "_ci": pre["_ci"].to_numpy()[pi],
        "event_ts": ev_ts, "screen": ev_screen, "action": ev_action,
    })
    # navegacao de fundo
    n_bg = int(len(prec) * 0.45)
    bi = rng.choice(n, n_bg, p=(engagement / engagement.sum()))
    bg = pd.DataFrame({
        "customer_id": cust[bi], "_ci": bi,
        "event_ts": START + pd.to_timedelta(rng.integers(0, DAYS, n_bg), "D")
                    + pd.to_timedelta(rng.integers(6, 24, n_bg), "h")
                    + pd.to_timedelta(rng.integers(0, 3600, n_bg), "s"),
        "screen": rng.choice(SCREENS, n_bg, p=[.30, .12, .09, .11, .08, .05, .04, .04, .09, .08]),
        "action": rng.choice(["view", "start", "abandon"], n_bg, p=[.74, .16, .10]),
    })
    ae = pd.concat([prec, bg], ignore_index=True).sort_values("event_ts").reset_index(drop=True)
    ae = ae[ae["event_ts"] >= START].reset_index(drop=True)
    ae.insert(0, "event_id", np.arange(1, len(ae) + 1))

    # ---------------- nudges ----------------
    n_nudge = int(n * 7.5)
    ni = rng.choice(n, n_nudge, p=(0.35 + engagement / 100) / (0.35 + engagement / 100).sum())
    ntype = rng.choice(NUDGES, n_nudge)
    nday = rng.integers(0, DAYS, n_nudge)
    nhour = rng.choice(np.arange(8, 22), n_nudge)
    nts = START + pd.to_timedelta(nday, "D") + pd.to_timedelta(nhour, "h") + pd.to_timedelta(rng.integers(0, 3600, n_nudge), "s")
    surface = rng.choice(SURFACES, n_nudge, p=[0.48, 0.32, 0.20])

    nd = pd.DataFrame({
        "customer_id": cust[ni], "_ci": ni, "shown_ts": nts,
        "nudge_type": ntype, "surface": surface,
    }).sort_values("shown_ts").reset_index(drop=True)
    nd["exposure_no"] = nd.groupby(["customer_id", "nudge_type"]).cumcount() + 1
    prev = nd.groupby("customer_id")["shown_ts"].diff().dt.total_seconds() / 3600.0
    nd["hours_since_last_nudge"] = prev.round(2)

    # momento certo: houve sinal de intencao nas ultimas 24h na tela do nudge?
    want_screen = pd.Series({k: SCREEN_OF[v] for k, v in NUDGE_INTENT.items()}).reindex(nd["nudge_type"]).to_numpy()
    key_ev = ae.assign(k=ae["customer_id"].astype(str) + "|" + ae["screen"])
    key_ev["event_ts"] = key_ev["event_ts"].astype("datetime64[ns]")
    key_ev = key_ev.sort_values("event_ts")
    nk = pd.DataFrame({"k": nd["customer_id"].astype(str) + "|" + want_screen,
                       "t": nd["shown_ts"].astype("datetime64[ns]")})
    merged = pd.merge_asof(nk.sort_values("t"), key_ev[["k", "event_ts"]].rename(columns={"event_ts": "last_ev"}).sort_values("last_ev"),
                           left_on="t", right_on="last_ev", by="k", direction="backward")
    merged = merged.sort_index()
    gap_h = (nk["t"].to_numpy() - merged["last_ev"].to_numpy()) / np.timedelta64(1, "h")
    on_time = np.nan_to_num(gap_h, nan=1e6) <= 24
    warm = (np.nan_to_num(gap_h, nan=1e6) > 24) & (np.nan_to_num(gap_h, nan=1e6) <= 168)

    nci = nd["_ci"].to_numpy()
    exp_no = nd["exposure_no"].to_numpy()
    z = -2.30
    z += np.where(on_time, 1.55, np.where(warm, 0.45, -0.35))       # o momento
    z -= np.clip(exp_no - 1, 0, 6) * 0.92                            # fadiga
    z += 0.014 * (engagement[nci] - 50)
    z += np.where(nd["surface"] == "in_app_modal", 0.28, np.where(nd["surface"] == "home_card", 0.05, -0.22))
    fit = np.zeros(len(nd))
    fit += 1.05 * ((nd["nudge_type"] == "savings_goal") & saver[nci])
    fit += 1.35 * ((nd["nudge_type"] == "loan_offer") & borrower[nci])
    fit += 1.10 * ((nd["nudge_type"] == "bill_reminder") & biller[nci])
    fit += 1.20 * ((nd["nudge_type"] == "invest_start") & investor[nci])
    fit += 0.95 * ((nd["nudge_type"] == "payroll_portability") & (~customers["has_payroll_portability"].to_numpy()[nci]))
    # o nudge mais atraente do catalogo, independente de perfil
    fit += 1.30 * (nd["nudge_type"] == "limit_increase")
    fit += 0.55 * ((nd["nudge_type"] == "limit_increase") & fragile[nci])
    z += fit + rng.normal(0, 0.35, len(nd))
    engaged = rng.random(len(nd)) < 1 / (1 + np.exp(-z))

    dismissed = (~engaged) & (rng.random(len(nd)) < 0.42)
    p_out = np.clip(0.003 + 0.011 * np.clip(exp_no - 1, 0, 8), 0, 0.12)
    opted_out = (~engaged) & (rng.random(len(nd)) < p_out)

    nudges = nd.drop(columns=["_ci"]).copy()
    nudges.insert(0, "nudge_id", np.arange(1, len(nudges) + 1))
    nudges["engaged"] = engaged
    nudges["dismissed"] = dismissed
    nudges["opted_out_after"] = opted_out

    # ---------------- consequencia em 90 dias ----------------
    e = engaged.astype(float)
    d_util = np.where(nd["nudge_type"] == "limit_increase", e * (8.5 + 9.0 * fragile[nci]) + rng.normal(0, 1.2, len(nd)),
              np.where(nd["nudge_type"] == "loan_offer", e * (4.0 + 4.5 * fragile[nci]) + rng.normal(0, 1.0, len(nd)),
              np.where(nd["nudge_type"] == "savings_goal", -e * 2.6 + rng.normal(0, 0.9, len(nd)),
                       rng.normal(0, 0.8, len(nd)))))
    d_sav = np.where(nd["nudge_type"] == "savings_goal", e * 6.4 + rng.normal(0, 1.1, len(nd)),
             np.where(nd["nudge_type"] == "payroll_portability", e * 3.1 + rng.normal(0, 1.0, len(nd)),
             np.where(nd["nudge_type"].isin(["limit_increase", "loan_offer"]), -e * 2.2 + rng.normal(0, 0.9, len(nd)),
                      rng.normal(0, 0.8, len(nd)))))
    d_neg = np.where(nd["nudge_type"] == "limit_increase", e * (0.55 + 1.5 * fragile[nci]),
             np.where(nd["nudge_type"] == "bill_reminder", -e * 0.85,
             np.where(nd["nudge_type"] == "savings_goal", -e * 0.45, 0.0))) + rng.normal(0, 0.25, len(nd))
    d_rev = np.where(nd["nudge_type"] == "limit_increase", e * (215 + 120 * fragile[nci]),
             np.where(nd["nudge_type"] == "loan_offer", e * 260,
             np.where(nd["nudge_type"] == "bill_reminder", -e * 74,
             np.where(nd["nudge_type"] == "savings_goal", e * 12,
             np.where(nd["nudge_type"] == "invest_start", e * 95, e * 40))))) + rng.normal(0, 25, len(nd))

    outcomes = pd.DataFrame({
        "nudge_id": nudges["nudge_id"],
        "delta_card_utilization_pct_90d": np.round(d_util, 2),
        "delta_savings_rate_pct_90d": np.round(d_sav, 2),
        "delta_days_negative_90d": np.round(d_neg, 2),
        "delta_revenue_mxn_90d": np.round(d_rev, 2),
    })

    ae = ae.drop(columns=["_ci"])
    fa = fa.drop(columns=["_ci"])
    for df_, cols in [(ae, ["event_id", "customer_id"]), (fa, ["action_id", "customer_id"]),
                      (nudges, ["nudge_id", "customer_id"])]:
        for cc in cols:
            df_[cc] = df_[cc].astype("int32")
    fa["amount_mxn"] = fa["amount_mxn"].astype("float32")
    nudges["hours_since_last_nudge"] = nudges["hours_since_last_nudge"].astype("float32")
    nudges["exposure_no"] = nudges["exposure_no"].astype("int16")
    for cc in outcomes.columns[1:]:
        outcomes[cc] = outcomes[cc].astype("float32")
    for cc in ["monthly_income_est_mxn", "avg_balance_mxn", "card_utilization_pct",
               "savings_rate_90d_pct", "revenue_ltm_mxn", "nps_last_score"]:
        customers[cc] = customers[cc].astype("float32")
    for cc in ["event_ts"]:
        ae[cc] = ae[cc].astype("datetime64[s]")
    fa["action_ts"] = fa["action_ts"].astype("datetime64[s]")
    nudges["shown_ts"] = nudges["shown_ts"].astype("datetime64[s]")
    return customers, ae, fa, nudges, outcomes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", type=int, default=38_000)
    ap.add_argument("--out", default="./data")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(SEED)
    c, ae, fa, nd, oc = build(a.customers, rng)
    for name, d in [("customers", c), ("app_events", ae), ("financial_actions", fa),
                    ("nudges", nd), ("nudge_outcomes", oc)]:
        p = os.path.join(a.out, f"{name}.parquet")
        d.to_parquet(p, index=False, compression="snappy")
        print(f"{name:20s} {len(d):>9,} linhas  {os.path.getsize(p)/1e6:6.1f} MB")


if __name__ == "__main__":
    main()
