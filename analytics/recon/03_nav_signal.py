"""B. Senal navegacion -> accion: matriz screen x action_type con lift a 24/72h,
   abandon vs view vs start, y distribucion de gaps entre eventos (definicion de sesion)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
common = import_module("00_common"); globals().update({k: v for k, v in vars(common).items() if not k.startswith("__")})
import pandas as pd, numpy as np

c = con()
c.execute("PRAGMA threads=8")

# ---------- composicion de app_events ----------
comp = c.execute("""
SELECT screen, action, count(*) n FROM app_events GROUP BY 1,2
""").df().pivot(index="screen", columns="action", values="n").fillna(0).astype(int)
comp["total"] = comp.sum(axis=1)
comp["pct_abandon"] = (100*comp["abandon"]/comp["total"]).round(2)
comp["pct_start"]   = (100*comp["start"]/comp["total"]).round(2)
comp = comp.sort_values("total", ascending=False)
show("B0. Composicion de app_events: screen x action", comp.reset_index())
dump(comp, "03_event_composition", index=True)

# ---------- matriz screen -> P(action_type en 24/72h) ----------
c.execute("""
CREATE TEMP TABLE pairs AS
SELECT e.event_id, e.screen, e.action AS ev_action, f.action_type,
       date_diff('second', e.event_ts, f.action_ts)/3600.0 AS gap_h
FROM app_events e JOIN financial_actions f
  ON e.customer_id = f.customer_id
 AND f.action_ts >  e.event_ts
 AND f.action_ts <= e.event_ts + INTERVAL 72 HOUR
""")
tot_ev = c.execute("SELECT count(*) FROM app_events").fetchone()[0]

for H in (24, 72):
    m = c.execute(f"""
    WITH ev AS (SELECT screen, count(*) n FROM app_events GROUP BY 1),
         hit AS (SELECT screen, action_type, count(DISTINCT event_id) k
                 FROM pairs WHERE gap_h <= {H} GROUP BY 1,2)
    SELECT h.screen, h.action_type, h.k, ev.n, 100.0*h.k/ev.n AS p
    FROM hit h JOIN ev USING(screen)
    """).df()
    base = c.execute(f"""
    SELECT action_type, 100.0*count(DISTINCT event_id)/{tot_ev} p0
    FROM pairs WHERE gap_h <= {H} GROUP BY 1
    """).df().set_index("action_type").p0
    m["base_rate_%"] = m.action_type.map(base)
    m["lift"] = (m.p / m["base_rate_%"])
    piv_p = m.pivot(index="screen", columns="action_type", values="p").round(2)
    piv_l = m.pivot(index="screen", columns="action_type", values="lift").round(2)
    show(f"B1. P(accion en {H}h | pantalla vista) %  — base rate al pie", piv_p.reset_index())
    print("BASE RATE %:", base.round(2).to_dict())
    show(f"B1b. LIFT sobre base rate ({H}h)", piv_l.reset_index())
    dump(piv_p, f"03_screen_action_p{H}h", index=True)
    dump(piv_l, f"03_screen_action_lift{H}h", index=True)

# ---------- abandon vs view vs start, en la pantalla ACOPLADA a la accion ----------
SCREEN_OF = {"spei_out":"transfer_spei","bill_payment":"bill_payment","deposit_in":"home",
             "savings_move":"savings_cajita","loan_request":"loan_simulation",
             "limit_increase_request":"limit_increase","card_payment":"card_statement",
             "investment_buy":"investments"}
pairs_map = " UNION ALL ".join([f"SELECT '{s}' scr, '{a}' act" for a,s in SCREEN_OF.items()])
c.execute(f"CREATE TEMP TABLE mapsa AS {pairs_map}")

for H in (24, 72):
    av = c.execute(f"""
    WITH ev AS (SELECT e.screen, e.action, count(*) n FROM app_events e GROUP BY 1,2),
         hit AS (SELECT p.screen, p.ev_action AS action, count(DISTINCT p.event_id) k
                 FROM pairs p JOIN mapsa m ON m.scr=p.screen AND m.act=p.action_type
                 WHERE p.gap_h <= {H} GROUP BY 1,2)
    SELECT ev.screen, ev.action, ev.n eventos, coalesce(hit.k,0) con_accion,
           round(100.0*coalesce(hit.k,0)/ev.n,2) AS "p_accion_acoplada_%"
    FROM ev LEFT JOIN hit USING(screen, action)
    ORDER BY ev.screen, ev.action
    """).df()
    p = av.pivot(index="screen", columns="action", values="p_accion_acoplada_%")
    p["lift_start_vs_view"]   = (p["start"]/p["view"]).round(2)
    p["lift_abandon_vs_view"] = (p["abandon"]/p["view"]).round(2)
    show(f"B2. P(accion ACOPLADA a la pantalla en {H}h) por tipo de interaccion — %", p.reset_index())
    dump(p, f"03_abandon_vs_view_{H}h", index=True)
    if H == 24:
        dump(av, "03_abandon_vs_view_raw_24h")

# ---------- lead time real de los precursores ----------
lt = c.execute("""
SELECT p.ev_action AS interaccion, count(*) n,
       quantile_cont(gap_h, 0.10) p10, quantile_cont(gap_h, 0.25) p25,
       quantile_cont(gap_h, 0.50) p50, quantile_cont(gap_h, 0.75) p75,
       quantile_cont(gap_h, 0.90) p90, avg(gap_h) media
FROM pairs p JOIN mapsa m ON m.scr=p.screen AND m.act=p.action_type
GROUP BY 1 ORDER BY 1
""").df().round(2)
show("B2b. Lead time evento -> accion ACOPLADA (horas), por tipo de interaccion", lt)
dump(lt, "03_lead_time")

# ---------- gaps entre eventos consecutivos ----------
g = c.execute("""
SELECT date_diff('second', lag(event_ts) OVER w, event_ts)/60.0 gap_min
FROM app_events WINDOW w AS (PARTITION BY customer_id ORDER BY event_ts)
""").df().dropna()
qs = [.05,.1,.25,.5,.6,.7,.75,.8,.9,.95,.99]
gq = g.gap_min.quantile(qs).round(2).rename("gap_min").reset_index().rename(columns={"index":"pctil"})
show("B3. Gap entre eventos consecutivos del mismo cliente (minutos)", gq)
dump(gq, "03_event_gaps_quantiles")

bins = [0,5,10,15,30,60,120,360,720,1440,4320,10**9]
lab = ["0-5m","5-10m","10-15m","15-30m","30-60m","1-2h","2-6h","6-12h","12-24h","1-3d",">3d"]
h = pd.cut(g.gap_min, bins=bins, labels=lab, right=True).value_counts().reindex(lab)
hist = pd.DataFrame({"bucket": lab, "n": h.values,
                     "pct": (100*h.values/h.sum()).round(2),
                     "pct_acum": (100*h.values.cumsum()/h.sum()).round(2)})
show("B3b. Histograma de gaps (para elegir el umbral de sesion)", hist)
dump(hist, "03_event_gap_histogram")

for thr in [15, 30, 60, 120]:
    ns = int((g.gap_min > thr).sum()) + 38000
    print(f"  umbral {thr:>4}min -> {ns:,} sesiones, {len(g)+38000:,} eventos, {(len(g)+38000)/ns:.2f} eventos/sesion")
