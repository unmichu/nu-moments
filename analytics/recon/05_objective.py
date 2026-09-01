"""D. La funcion objetivo: outcomes 90d por nudge_type, contraste engagement vs salud
   financiera vs revenue, y dos rankings enfrentados."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
common = import_module("00_common"); globals().update({k: v for k, v in vars(common).items() if not k.startswith("__")})
import pandas as pd, numpy as np

c = con(); c.execute("PRAGMA threads=8")

c.execute("""CREATE TEMP TABLE j AS
SELECT n.nudge_id, n.customer_id, n.nudge_type, n.surface, n.exposure_no, n.engaged,
       n.dismissed, n.opted_out_after,
       o.delta_card_utilization_pct_90d du, o.delta_savings_rate_pct_90d ds,
       o.delta_days_negative_90d dn, o.delta_revenue_mxn_90d dr,
       c.card_utilization_pct util, c.days_negative_90d dneg, c.savings_rate_90d_pct sav,
       c.revenue_ltm_mxn rev, c.engagement_score eng, c.monthly_income_est_mxn inc,
       (c.card_utilization_pct > 70 OR c.days_negative_90d >= 3) AS fragil
FROM nudges n JOIN nudge_outcomes o USING(nudge_id) JOIN customers c USING(customer_id)""")

SEL = """count(*) n,
  round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) "engaged_%",
  round(100*avg(CASE WHEN opted_out_after THEN 1 ELSE 0 END),3) "optout_%",
  round(avg(ds)::DOUBLE,3) d_savings_rate_pp,
  round(avg(dn)::DOUBLE,3) d_days_negative,
  round(avg(du)::DOUBLE,3) d_card_util_pp,
  round(avg(dr)::DOUBLE,1) d_revenue_mxn"""

# ---------- D1. Tabla maestra por nudge_type (TODOS los nudges enviados) ----------
m = c.execute(f'SELECT nudge_type, {SEL} FROM j GROUP BY 1 ORDER BY "engaged_%" DESC').df()
show("D1. Efecto MEDIO POR NUDGE ENVIADO (intention-to-treat), por nudge_type", m)
dump(m, "05_master_by_type")

# ---------- D2. Solo entre los que engancharon (efecto del tratamiento realizado) ----------
me = c.execute(f'SELECT nudge_type, {SEL} FROM j WHERE engaged GROUP BY 1 ORDER BY d_revenue_mxn DESC').df()
show("D2. Efecto entre los que SI engancharon (treated-on-treated)", me)
dump(me, "05_by_type_engaged")

mn = c.execute(f'SELECT nudge_type, {SEL} FROM j WHERE NOT engaged GROUP BY 1').df()
show("D2b. Contrafactual: los que NO engancharon (debe ser ~0 en todo = valida causalidad)", mn)
dump(mn, "05_by_type_not_engaged")

# ---------- D3. Los dos rankings enfrentados ----------
base = m.set_index("nudge_type")
# indice de salud financiera: normalizado, mayor = mejor para el cliente
h = (base.d_savings_rate_pp - base.d_days_negative*3.0 - base.d_card_util_pp*0.5)
rank = pd.DataFrame({
    "engaged_%": base["engaged_%"],
    "salud_idx": h.round(3),
    "d_revenue_mxn": base.d_revenue_mxn,
})
rank["rk_engagement"] = rank["engaged_%"].rank(ascending=False).astype(int)
rank["rk_salud"]      = rank["salud_idx"].rank(ascending=False).astype(int)
rank["rk_revenue"]    = rank["d_revenue_mxn"].rank(ascending=False).astype(int)
rank["gap_salud_vs_rev"] = rank.rk_salud - rank.rk_revenue
show("D3. TRES RANKINGS ENFRENTADOS (salud_idx = d_savings - 3*d_dias_negativos - 0.5*d_util)",
     rank.sort_values("rk_engagement").reset_index())
dump(rank, "05_rankings", index=True)

print("\n  ORDEN si optimizas ENGAGEMENT :", " > ".join(rank.sort_values("rk_engagement").index))
print("  ORDEN si optimizas SALUD      :", " > ".join(rank.sort_values("rk_salud").index))
print("  ORDEN si optimizas REVENUE    :", " > ".join(rank.sort_values("rk_revenue").index))
sp = lambda a, b: round(a.rank().corr(b.rank()), 3)
print("  Correlacion de rangos salud vs revenue :", sp(rank.salud_idx, rank.d_revenue_mxn))
print("  Correlacion de rangos engagement vs salud:", sp(rank["engaged_%"], rank.salud_idx))
print("  Correlacion de rangos engagement vs revenue:", sp(rank["engaged_%"], rank.d_revenue_mxn))

# ---------- D4. El agravante: fragiles ----------
fr = c.execute(f"""SELECT nudge_type, fragil, {SEL} FROM j GROUP BY 1,2 ORDER BY 1,2""").df()
show("D4. Mismo analisis segmentado por cliente FRAGIL (util>70 o dias_neg>=3)", fr)
dump(fr, "05_by_type_fragile")

frag_pct = c.execute("SELECT round(100*avg(CASE WHEN card_utilization_pct>70 OR days_negative_90d>=3 THEN 1.0 ELSE 0 END),2) FROM customers").fetchone()[0]
print(f"\n  % de clientes fragiles en la base: {frag_pct}%")

li = c.execute("""
SELECT fragil, count(*) n,
  round(100*avg(CASE WHEN engaged THEN 1 ELSE 0 END),2) "engaged_%",
  round(avg(CASE WHEN engaged THEN du END)::DOUBLE,2) d_util_si_engancha,
  round(avg(CASE WHEN engaged THEN dn END)::DOUBLE,2) d_dias_neg_si_engancha,
  round(avg(CASE WHEN engaged THEN dr END)::DOUBLE,1) d_revenue_si_engancha
FROM j WHERE nudge_type='limit_increase' GROUP BY 1""").df()
show("D4b. *** limit_increase sobre clientes FRAGILES: el caso extremo ***", li)
dump(li, "05_limit_increase_fragile")

# ---------- D5. Valor total generado/destruido por tipo (escala de la decision) ----------
tot = c.execute("""
SELECT nudge_type, count(*) enviados,
  sum(CASE WHEN engaged THEN 1 ELSE 0 END) enganchados,
  round(sum(dr)::DOUBLE,0) revenue_total_mxn,
  round(sum(dn)::DOUBLE,0) dias_negativos_totales,
  round(sum(ds)::DOUBLE,0) puntos_ahorro_totales,
  round(sum(dr)::DOUBLE/nullif(sum(CASE WHEN engaged THEN 1 ELSE 0 END),0),1) revenue_por_enganche,
  round(sum(dn)::DOUBLE/nullif(sum(CASE WHEN engaged THEN 1 ELSE 0 END),0),3) dias_neg_por_enganche
FROM j GROUP BY 1 ORDER BY revenue_total_mxn DESC""").df()
show("D5. Escala agregada: que crea y que destruye cada tipo en los 120 dias", tot)
dump(tot, "05_totals")

# ---------- D6. El trade-off cuantificado: MXN de revenue por dia-en-negativo causado ----------
tr = tot.copy()
tr["mxn_revenue_por_dia_negativo_causado"] = (tr.revenue_total_mxn / tr.dias_negativos_totales).round(0)
show("D6. Precio implicito del dano: MXN de revenue por cada dia-en-negativo causado",
     tr[["nudge_type","revenue_total_mxn","dias_negativos_totales","mxn_revenue_por_dia_negativo_causado"]])
dump(tr, "05_tradeoff_price")
