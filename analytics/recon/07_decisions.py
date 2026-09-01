"""Sintesis accionable: (1) techo realista del modelo de intencion con una regla simple,
   (2) simulacion de politicas de envio sobre los nudges realmente observados."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
common = import_module("00_common"); globals().update({k: v for k, v in vars(common).items() if not k.startswith("__")})
import pandas as pd, numpy as np

c = con(); c.execute("PRAGMA threads=8")
CUT = START + pd.Timedelta(days=100)
END = CUT + pd.Timedelta(days=7)
SCREEN_OF = {"transfer_spei":"spei_out","bill_payment":"bill_payment","home":"deposit_in",
             "savings_cajita":"savings_move","loan_simulation":"loan_request",
             "limit_increase":"limit_increase_request","card_statement":"card_payment",
             "investments":"investment_buy"}
mapsql = " UNION ALL ".join(f"SELECT '{k}' screen, '{v}' pred" for k,v in SCREEN_OF.items())
c.execute(f"CREATE TEMP TABLE smap AS {mapsql}")

# ---------- 1. Techo con regla simple: ultima pantalla accionable antes del corte ----------
rows = []
for LB in (24, 48, 72, 168):
    df = c.execute(f"""
    WITH truth AS (
      SELECT customer_id, arg_min(action_type, action_ts) y FROM financial_actions
      WHERE action_ts > TIMESTAMP '{CUT}' AND action_ts <= TIMESTAMP '{END}' GROUP BY 1),
    sig AS (
      SELECT e.customer_id, arg_max(s.pred, e.event_ts) yhat, count(*) n_ev
      FROM app_events e JOIN smap s USING(screen)
      WHERE e.event_ts <= TIMESTAMP '{CUT}'
        AND e.event_ts >  TIMESTAMP '{CUT}' - INTERVAL {LB} HOUR
      GROUP BY 1)
    SELECT t.customer_id, t.y, s.yhat FROM truth t LEFT JOIN sig s USING(customer_id)""").df()
    cov = df.yhat.notna().mean()
    acc_cov = (df.y == df.yhat)[df.yhat.notna()].mean()
    hybrid = df.yhat.fillna("spei_out")
    rows.append(dict(lookback_h=LB, clientes_activos=len(df),
                     pct_con_senal=round(100*cov,1),
                     acc_donde_hay_senal=round(100*acc_cov,2),
                     acc_hibrida_vs_mayoritaria=round(100*(df.y==hybrid).mean(),2)))
r = pd.DataFrame(rows)
r["baseline_mayoritaria"] = 41.62
r["lift_pp"] = (r.acc_hibrida_vs_mayoritaria - 41.62).round(2)
show("F1. Techo realista del modelo de intencion: regla 'ultima pantalla accionable' \n"
     "    (label = primera accion en 7d tras corte d100; baseline mayoritaria = 41.62%)", r)
dump(r, "07_intent_ceiling")

# ---------- 2. Simulacion de politicas de envio ----------
c.execute("""CREATE TEMP TABLE nmap AS SELECT * FROM (VALUES
 ('savings_goal','savings_cajita'),('limit_increase','limit_increase'),('bill_reminder','bill_payment'),
 ('loan_offer','loan_simulation'),('invest_start','investments'),('payroll_portability','home')
) t(nudge_type, want_screen)""")
c.execute("""CREATE TEMP TABLE ek AS SELECT customer_id::VARCHAR||'|'||screen k, event_ts FROM app_events""")
c.execute("""CREATE TEMP TABLE nn AS
SELECT n.nudge_id, n.customer_id, n.nudge_type, n.surface, n.exposure_no, n.engaged, n.opted_out_after,
       o.delta_savings_rate_pct_90d ds, o.delta_days_negative_90d dn,
       o.delta_card_utilization_pct_90d du, o.delta_revenue_mxn_90d dr,
       (cu.card_utilization_pct>70 OR cu.days_negative_90d>=3) fragil,
       n.customer_id::VARCHAR||'|'||m.want_screen k, n.shown_ts
FROM nudges n JOIN nudge_outcomes o USING(nudge_id) JOIN customers cu USING(customer_id)
JOIN nmap m USING(nudge_type)""")
c.execute("""CREATE TEMP TABLE pol AS
SELECT nn.*, coalesce(date_diff('second', ek.event_ts, nn.shown_ts)/3600.0, 1e6) gap_h
FROM nn ASOF LEFT JOIN ek ON nn.k=ek.k AND ek.event_ts <= nn.shown_ts""")

POLICIES = {
 "P0 baseline: enviar todo":                        "TRUE",
 "P1 cap de frecuencia: exposure_no<=2":            "exposure_no<=2",
 "P2 solo on_time (senal <=24h)":                   "gap_h<=24",
 "P3 on_time o warm (<=7d)":                        "gap_h<=168",
 "P4 sin limit_increase a fragiles":                "NOT (nudge_type='limit_increase' AND fragil)",
 "P5 on_time + exposure<=2":                        "gap_h<=24 AND exposure_no<=2",
 "P6 SALUD: (on_time o warm) + exp<=2 + veto limit_increase a fragiles":
     "gap_h<=168 AND exposure_no<=2 AND NOT (nudge_type='limit_increase' AND fragil)",
 "P7 REVENUE: (on_time o warm) + exp<=2 (sin veto)":"gap_h<=168 AND exposure_no<=2",
}
tot_n = c.execute("SELECT count(*) FROM pol").fetchone()[0]
out = []
for name, w in POLICIES.items():
    q = c.execute(f"""SELECT count(*) enviados, sum(CASE WHEN engaged THEN 1 ELSE 0 END) enganches,
      sum(CASE WHEN opted_out_after THEN 1 ELSE 0 END) optouts,
      sum(dr)::DOUBLE rev, sum(dn)::DOUBLE dias_neg, sum(ds)::DOUBLE ahorro, sum(du)::DOUBLE util
      FROM pol WHERE {w}""").fetchone()
    e, k, oo, rev, dneg, sav, ut = q
    out.append(dict(politica=name, enviados=e, pct_volumen=round(100*e/tot_n,1),
                    enganches=int(k), tasa_enganche=round(100*k/e,2),
                    optouts=int(oo), optouts_evitados=None,
                    revenue_mxn=round(rev), dias_negativos=round(dneg),
                    puntos_ahorro=round(sav), util_pp=round(ut),
                    revenue_por_envio=round(rev/e,2)))
o = pd.DataFrame(out)
b = o.iloc[0]
o["optouts_evitados"] = (b.optouts - o.optouts).astype(int)
o["pct_revenue_retenido"] = (100*o.revenue_mxn/b.revenue_mxn).round(1)
o["pct_enganches_retenidos"] = (100*o.enganches/b.enganches).round(1)
show("F2. SIMULACION DE POLITICAS DE ENVIO (sobre los 285k nudges observados; no enviar = efecto 0)", o)
dump(o, "07_policy_simulation")

print("\nLectura: P6 vs P0 ->",
      f"{o.loc[6,'pct_volumen']}% del volumen, {o.loc[6,'pct_enganches_retenidos']}% de los enganches,",
      f"{o.loc[6,'pct_revenue_retenido']}% del revenue, dias negativos {b.dias_negativos:.0f} -> {o.loc[6,'dias_negativos']:.0f},",
      f"{o.loc[6,'optouts_evitados']} opt-outs evitados.")

# ---------- 3. El efecto payday sobre engagement, es directo o esta MEDIADO por la senal? ----------
med = c.execute("""
WITH x AS (
  SELECT p.*, cu.payday_day_of_month pay,
    CASE WHEN ((CAST(extract(day FROM p.shown_ts) AS INT) - cu.payday_day_of_month) % 30) IN (0,1,2)
         THEN 'ventana_payday_d0_d2' ELSE 'resto_del_mes' END win,
    CASE WHEN p.gap_h<=24 THEN 'on_time' WHEN p.gap_h<=168 THEN 'warm' ELSE 'cold' END mom
  FROM pol p JOIN customers cu USING(customer_id))
SELECT win, mom, count(*) n, round(100.0*count(*)/sum(count(*)) OVER (PARTITION BY win),1) "pct_dentro_de_win",
       round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) "engaged_%"
FROM x GROUP BY 1,2 ORDER BY 1,2""").df()
show("F3. Payday: efecto directo o mediado por la senal de intencion?", med)
dump(med, "07_payday_mediation")
tot = c.execute("""
WITH x AS (SELECT p.engaged, CASE WHEN ((CAST(extract(day FROM p.shown_ts) AS INT) - cu.payday_day_of_month)%30) IN (0,1,2)
  THEN 'ventana_payday_d0_d2' ELSE 'resto_del_mes' END win FROM pol p JOIN customers cu USING(customer_id))
SELECT win, count(*) n, round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) "engaged_%" FROM x GROUP BY 1""").df()
show("F3b. Efecto TOTAL (sin controlar)", tot); dump(tot, "07_payday_total")
