"""C. Timing y fatiga: engaged global/por tipo/superficie/hora/dia, curva de fatiga por
   exposure_no, efecto de hours_since_last_nudge, payday, y la feature 'momento' real
   (recencia de senal de intencion en la pantalla acoplada al nudge)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
common = import_module("00_common"); globals().update({k: v for k, v in vars(common).items() if not k.startswith("__")})
import pandas as pd, numpy as np

c = con(); c.execute("PRAGMA threads=8")

G = c.execute("""SELECT round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) engaged,
                        round(100*avg(CASE WHEN dismissed THEN 1 ELSE 0 END),2) dismissed,
                        round(100*avg(CASE WHEN opted_out_after THEN 1 ELSE 0 END),3) opt_out,
                        count(*) n FROM nudges""").df()
show("C0. Tasas globales de nudges (%)", G)
dump(G, "04_global_rates")

def rate(dim, extra=""):
    return c.execute(f"""
    SELECT {dim}, count(*) n,
           round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) "engaged_%",
           round(100*avg(CASE WHEN dismissed THEN 1 ELSE 0 END),2) "dismissed_%",
           round(100*avg(CASE WHEN opted_out_after THEN 1 ELSE 0 END),3) "optout_%"
    FROM nudges {extra} GROUP BY {dim} ORDER BY "engaged_%" DESC""").df()

t = rate("nudge_type");  show("C1. Engagement por nudge_type", t);       dump(t, "04_by_nudge_type")
s = rate("surface");     show("C2. Engagement por surface", s);          dump(s, "04_by_surface")

ts = c.execute("""
SELECT nudge_type, surface, count(*) n, round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) e
FROM nudges GROUP BY 1,2""").df().pivot(index="nudge_type", columns="surface", values="e")
show("C2b. Engagement % — nudge_type x surface", ts.reset_index()); dump(ts, "04_type_x_surface", index=True)

h = c.execute("""SELECT extract(hour FROM shown_ts) hora, count(*) n,
   round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) "engaged_%" FROM nudges GROUP BY 1 ORDER BY 1""").df()
show("C3. Engagement por hora del dia (nudges solo se envian 8-21h)", h); dump(h, "04_by_hour")
print(f"  rango hora: {h['engaged_%'].min()}% - {h['engaged_%'].max()}%  |  spread = {h['engaged_%'].max()-h['engaged_%'].min():.2f}pp")
# test chi2 de homogeneidad

dw = c.execute("""SELECT dayname(shown_ts) dia, extract(dow FROM shown_ts) dow, count(*) n,
   round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) "engaged_%" FROM nudges GROUP BY 1,2 ORDER BY dow""").df()
show("C3b. Engagement por dia de la semana", dw); dump(dw, "04_by_dow")
print(f"  spread dia de semana = {dw['engaged_%'].max()-dw['engaged_%'].min():.2f}pp")

# ---------- CURVA DE FATIGA ----------
fat = c.execute("""
SELECT CASE WHEN exposure_no >= 6 THEN '6+' ELSE CAST(exposure_no AS VARCHAR) END exposure_no,
       min(exposure_no) ord, count(*) n,
       round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) "engaged_%",
       round(100*avg(CASE WHEN dismissed THEN 1 ELSE 0 END),2) "dismissed_%",
       round(100*avg(CASE WHEN opted_out_after THEN 1 ELSE 0 END),3) "optout_%",
       round(100*avg(CASE WHEN opted_out_after THEN 1 ELSE 0 END)
             / nullif(avg(CASE WHEN engaged THEN 0 ELSE 1 END),0),3) "optout_%_entre_no_engaged"
FROM nudges GROUP BY 1 ORDER BY ord""").df().drop(columns="ord")
fat["engaged_rel_vs_exp1"] = (fat["engaged_%"]/fat["engaged_%"].iloc[0]).round(3)
show("C4. CURVA DE FATIGA por exposure_no (n-esima vez que ve ESE nudge_type)", fat)
dump(fat, "04_fatigue_curve")
print("  BRIEF dice: 15.7% en 1a exposicion, 3.5% en la 3a, opt-out 2.5% en la 3a.")

fat_t = c.execute("""
SELECT nudge_type, CASE WHEN exposure_no>=4 THEN 4 ELSE exposure_no END e, count(*) n,
       round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) r
FROM nudges GROUP BY 1,2""").df().pivot(index="nudge_type", columns="e", values="r")
fat_t.columns=[f"exp_{x}" if x<4 else "exp_4+" for x in fat_t.columns]
fat_t["caida_1_a_3_pp"]=(fat_t.exp_1-fat_t.exp_3).round(2)
fat_t["retencion_3/1"]=(fat_t.exp_3/fat_t.exp_1).round(3)
show("C4b. Fatiga por nudge_type (engaged %)", fat_t.reset_index()); dump(fat_t,"04_fatigue_by_type",index=True)

# ---------- hours_since_last_nudge ----------
hs = c.execute("""
SELECT CASE WHEN hours_since_last_nudge IS NULL THEN '0_primer_nudge'
            WHEN hours_since_last_nudge < 6   THEN '1_<6h'
            WHEN hours_since_last_nudge < 24  THEN '2_6-24h'
            WHEN hours_since_last_nudge < 72  THEN '3_1-3d'
            WHEN hours_since_last_nudge < 168 THEN '4_3-7d'
            WHEN hours_since_last_nudge < 336 THEN '5_7-14d'
            ELSE '6_>14d' END b, count(*) n,
       round(avg(exposure_no),2) exposure_no_medio,
       round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) "engaged_%",
       round(100*avg(CASE WHEN opted_out_after THEN 1 ELSE 0 END),3) "optout_%"
FROM nudges GROUP BY 1 ORDER BY 1""").df()
show("C5. Efecto de hours_since_last_nudge (OJO: confundido con exposure_no)", hs); dump(hs,"04_by_hours_since")

hs_ctrl = c.execute("""
SELECT exposure_no, CASE WHEN hours_since_last_nudge IS NULL THEN 'primero'
            WHEN hours_since_last_nudge < 24 THEN '<24h'
            WHEN hours_since_last_nudge < 168 THEN '1-7d' ELSE '>7d' END b,
       count(*) n, round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) r
FROM nudges WHERE exposure_no<=4 GROUP BY 1,2""").df().pivot(index="exposure_no",columns="b",values="r")
show("C5b. engaged % por hours_since_last_nudge CONTROLANDO exposure_no", hs_ctrl.reset_index())
dump(hs_ctrl,"04_hours_since_controlled",index=True)

# ---------- payday ----------
pd_nudge = c.execute("""
SELECT c.payday_day_of_month payday,
       CAST(extract(day FROM n.shown_ts) AS INT) dom, count(*) k,
       avg(CASE WHEN n.engaged THEN 1.0 ELSE 0 END) e
FROM nudges n JOIN customers c USING(customer_id) GROUP BY 1,2""").df()
pd_nudge["dist"] = ((pd_nudge.dom - pd_nudge.payday) % 30)
pd_nudge["dist"] = np.where(pd_nudge.dist > 15, pd_nudge.dist - 30, pd_nudge.dist)
agg = pd_nudge.groupby("dist").apply(lambda g: pd.Series({
    "n": g.k.sum(), "engaged_%": round(100*(g.e*g.k).sum()/g.k.sum(),2)}), include_groups=False).reset_index()
show("C6. Engagement de nudges vs dias respecto al payday del cliente", agg)
dump(agg, "04_payday_nudges")
print(f"  spread engagement alrededor del payday = {agg['engaged_%'].max()-agg['engaged_%'].min():.2f}pp")

pd_act = c.execute("""
SELECT f.action_type, ((CAST(extract(day FROM f.action_ts) AS INT) - c.payday_day_of_month) % 30) d0, count(*) k
FROM financial_actions f JOIN customers c USING(customer_id) GROUP BY 1,2""").df()
pd_act["dist"] = np.where(pd_act.d0 > 15, pd_act.d0 - 30, pd_act.d0)
tot = pd_act.groupby("action_type").k.sum()
pv = pd_act.groupby(["action_type","dist"]).k.sum().reset_index()
pv["idx"] = (pv.k / pv.action_type.map(tot) * 30).round(2)   # 1.0 = uniforme
pvt = pv.pivot(index="action_type", columns="dist", values="idx")
cols = [x for x in range(-6,8) if x in pvt.columns]
show("C6b. INDICE de acciones por dia relativo al payday (1.00 = uniforme). d0 = dia de pago",
     pvt[cols].reset_index())
dump(pvt, "04_payday_actions", index=True)

# ---------- LA FEATURE DE MOMENTO: recencia de intencion en la pantalla acoplada ----------
c.execute("""CREATE TEMP TABLE nmap AS
SELECT * FROM (VALUES ('savings_goal','savings_cajita'),('limit_increase','limit_increase'),
 ('bill_reminder','bill_payment'),('loan_offer','loan_simulation'),
 ('invest_start','investments'),('payroll_portability','home')) t(nudge_type, want_screen)""")
c.execute("""CREATE TEMP TABLE nw AS
SELECT n.nudge_id, n.customer_id, n.shown_ts, n.nudge_type, n.surface, n.exposure_no,
       n.engaged, n.opted_out_after, m.want_screen,
       n.customer_id::VARCHAR || '|' || m.want_screen AS k
FROM nudges n JOIN nmap m USING(nudge_type)""")
c.execute("""CREATE TEMP TABLE ek AS
SELECT customer_id::VARCHAR || '|' || screen AS k, event_ts FROM app_events""")
mom = c.execute("""
WITH j AS (
  SELECT nw.*, date_diff('second', ek.event_ts, nw.shown_ts)/3600.0 AS gap_h
  FROM nw ASOF LEFT JOIN ek ON nw.k = ek.k AND ek.event_ts <= nw.shown_ts
)
SELECT CASE WHEN gap_h IS NULL THEN '3_nunca'
            WHEN gap_h <= 24  THEN '0_on_time (<=24h)'
            WHEN gap_h <= 168 THEN '1_warm (24h-7d)'
            ELSE '2_cold (>7d)' END momento,
       count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),1) "pct_nudges",
       round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) "engaged_%",
       round(100*avg(CASE WHEN opted_out_after THEN 1 ELSE 0 END),3) "optout_%"
FROM j GROUP BY 1 ORDER BY 1""").df()
base = c.execute("SELECT 100*avg(CASE WHEN engaged THEN 1 ELSE 0 END) FROM nudges").fetchone()[0]
mom["lift_vs_global"] = (mom["engaged_%"]/base).round(2)
show("C7. *** EL MOMENTO ***: engagement segun recencia de senal de intencion en la pantalla del nudge", mom)
dump(mom, "04_moment_recency")

mom2 = c.execute("""
WITH j AS (
  SELECT nw.*, date_diff('second', ek.event_ts, nw.shown_ts)/3600.0 AS gap_h
  FROM nw ASOF LEFT JOIN ek ON nw.k = ek.k AND ek.event_ts <= nw.shown_ts
)
SELECT CASE WHEN gap_h IS NOT NULL AND gap_h<=24 THEN 'on_time' ELSE 'resto' END mom,
       CASE WHEN exposure_no>=4 THEN 4 ELSE exposure_no END exp_no,
       count(*) n, round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) r
FROM j GROUP BY 1,2""").df().pivot(index="exp_no", columns="mom", values="r")
mom2["lift_on_time"] = (mom2.on_time/mom2.resto).round(2)
show("C7b. Momento x fatiga: engaged % (exp_no 4 = 4+)", mom2.reset_index())
dump(mom2, "04_moment_x_fatigue", index=True)
