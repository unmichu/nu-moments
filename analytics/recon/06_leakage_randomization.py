"""E. Trampas: leakage de las columnas de customers, y verificacion de que
   nudge_type/surface estan asignados al azar (y que la SELECCION de quien recibe no lo esta)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
common = import_module("00_common"); globals().update({k: v for k, v in vars(common).items() if not k.startswith("__")})
import pandas as pd, numpy as np
from scipy.stats import chi2_contingency, f_oneway

c = con(); c.execute("PRAGMA threads=8")
cu = load("customers")
MID = START + pd.Timedelta(days=60)

# ---------- E2. Las columnas de customers: snapshot estatico o estado final? ----------
# Test: si son ESTADO FINAL, deben correlacionar mas con la 2a mitad que con la 1a.
half = c.execute(f"""
SELECT customer_id,
  sum(CASE WHEN action_ts <  TIMESTAMP '{MID}' AND action_type='savings_move' THEN 1 ELSE 0 END) sm_h1,
  sum(CASE WHEN action_ts >= TIMESTAMP '{MID}' AND action_type='savings_move' THEN 1 ELSE 0 END) sm_h2,
  sum(CASE WHEN action_ts <  TIMESTAMP '{MID}' AND action_type='loan_request' THEN 1 ELSE 0 END) lr_h1,
  sum(CASE WHEN action_ts >= TIMESTAMP '{MID}' AND action_type='loan_request' THEN 1 ELSE 0 END) lr_h2,
  sum(CASE WHEN action_ts <  TIMESTAMP '{MID}' THEN 1 ELSE 0 END) all_h1,
  sum(CASE WHEN action_ts >= TIMESTAMP '{MID}' THEN 1 ELSE 0 END) all_h2
FROM financial_actions GROUP BY 1""").df()
d = cu.merge(half, on="customer_id", how="left").fillna(0)
tests = []
for col, (a, b), lab in [("savings_rate_90d_pct", ("sm_h1","sm_h2"), "savings_move"),
                         ("card_utilization_pct", ("lr_h1","lr_h2"), "loan_request"),
                         ("engagement_score",     ("all_h1","all_h2"), "todas las acciones"),
                         ("revenue_ltm_mxn",      ("all_h1","all_h2"), "todas las acciones"),
                         ("days_negative_90d",    ("lr_h1","lr_h2"), "loan_request")]:
    r1, r2 = d[col].corr(d[a]), d[col].corr(d[b])
    tests.append(dict(columna_customers=col, target=lab, corr_1a_mitad=round(r1,4),
                      corr_2a_mitad=round(r2,4), diff=round(r2-r1,4)))
t = pd.DataFrame(tests)
show("E2. Test de vintage: las columnas de customers, correlacionan igual con la 1a y la 2a mitad?\n"
     "    (si son ESTADO FINAL -> corr_2a >> corr_1a. Si son latente ESTATICO -> iguales)", t)
dump(t, "06_vintage_test")

# ---------- E2b. Poder predictivo bruto de las columnas de customers (magnitud del riesgo) ----------
cut = START + pd.Timedelta(days=100)
post = c.execute(f"""
SELECT customer_id,
 max(CASE WHEN action_type='savings_move'          THEN 1 ELSE 0 END) y_savings,
 max(CASE WHEN action_type='loan_request'          THEN 1 ELSE 0 END) y_loan,
 max(CASE WHEN action_type='limit_increase_request'THEN 1 ELSE 0 END) y_limit,
 max(CASE WHEN action_type='investment_buy'        THEN 1 ELSE 0 END) y_invest
FROM financial_actions
WHERE action_ts > TIMESTAMP '{cut}' AND action_ts <= TIMESTAMP '{cut + pd.Timedelta(days=7)}'
GROUP BY 1""").df()
p = cu.merge(post, on="customer_id", how="left").fillna(0)
pw = []
for y, cols in [("y_savings", ["savings_rate_90d_pct","has_cajita_turbo","avg_balance_mxn"]),
                ("y_loan",    ["card_utilization_pct","has_personal_loan","days_negative_90d","revenue_ltm_mxn"]),
                ("y_limit",   ["card_utilization_pct","has_personal_loan","days_negative_90d"]),
                ("y_invest",  ["has_investments","monthly_income_est_mxn","avg_balance_mxn"])]:
    for col in cols:
        x = p[col].astype(float)
        g1, g0 = x[p[y]==1], x[p[y]==0]
        lift = g1.mean()/g0.mean() if g0.mean() != 0 else np.nan
        pw.append(dict(target_7d=y, feature=col, media_pos=round(g1.mean(),2),
                       media_neg=round(g0.mean(),2), ratio=round(lift,3),
                       corr=round(x.corr(p[y]),4)))
pw = pd.DataFrame(pw)
show("E2b. Poder predictivo de columnas 'de estado' de customers sobre el label de 7d (corte d100)", pw)
dump(pw, "06_customer_feature_power")

# ---------- E3. Aleatoriedad de nudge_type y surface ----------
nd = c.execute("SELECT customer_id, nudge_type, surface, exposure_no, engaged FROM nudges").df()
nd = nd.merge(cu, on="customer_id")
nd["fragil"] = (nd.card_utilization_pct > 70) | (nd.days_negative_90d >= 3)
nd["eng_q"] = pd.qcut(nd.engagement_score, 5, labels=[f"Q{i}" for i in range(1,6)])
nd["ahorrador"] = nd.has_cajita_turbo

res = []
for treat in ["nudge_type", "surface"]:
    for cov in ["income_band", "eng_q", "fragil", "ahorrador", "has_personal_loan",
                "has_investments", "has_payroll_portability", "payday_day_of_month", "state"]:
        ct = pd.crosstab(nd[treat], nd[cov])
        chi2, pval, dof, _ = chi2_contingency(ct)
        cram = np.sqrt(chi2 / (ct.values.sum() * (min(ct.shape) - 1)))
        res.append(dict(tratamiento=treat, covariable=cov, chi2=round(chi2,1), dof=dof,
                        p_value=round(pval,4), cramers_v=round(cram,5),
                        veredicto="ALEATORIO" if pval > 0.01 else "sesgo detectado"))
res = pd.DataFrame(res)
show("E3. Test chi2: nudge_type / surface vs atributos del cliente (H0 = asignacion aleatoria)", res)
dump(res, "06_randomization_tests")

# ---------- E3b. Pero la SELECCION de a quien se le envia NO es aleatoria ----------
cnt = nd.groupby("customer_id").size().rename("n_nudges")
sel = cu.set_index("customer_id").join(cnt).fillna(0)
sel["eng_q"] = pd.qcut(sel.engagement_score, 5, labels=[f"Q{i}" for i in range(1,6)])
selt = sel.groupby("eng_q", observed=True).agg(
    clientes=("n_nudges","size"), engagement_medio=("engagement_score","mean"),
    nudges_por_cliente=("n_nudges","mean"), sin_ningun_nudge=("n_nudges", lambda s:(s==0).sum())).round(2)
show("E3b. *** SESGO DE SELECCION ***: cuantos nudges recibe cada quintil de engagement_score",
     selt.reset_index())
dump(selt, "06_selection_bias", index=True)
print(f"  ratio Q5/Q1 de nudges por cliente: {selt.nudges_por_cliente.iloc[-1]/selt.nudges_por_cliente.iloc[0]:.2f}x")

# ---------- E4. Columnas prohibidas ----------
banned = pd.DataFrame([
 dict(tabla="nudge_outcomes", columna="delta_card_utilization_pct_90d", uso="TARGET / NUNCA feature", motivo="posterior al nudge, +90d"),
 dict(tabla="nudge_outcomes", columna="delta_savings_rate_pct_90d",     uso="TARGET / NUNCA feature", motivo="posterior al nudge, +90d"),
 dict(tabla="nudge_outcomes", columna="delta_days_negative_90d",        uso="TARGET / NUNCA feature", motivo="posterior al nudge, +90d"),
 dict(tabla="nudge_outcomes", columna="delta_revenue_mxn_90d",          uso="TARGET / NUNCA feature", motivo="posterior al nudge, +90d"),
 dict(tabla="nudges", columna="engaged",         uso="TARGET del modelo de momento", motivo="resultado del nudge"),
 dict(tabla="nudges", columna="dismissed",       uso="TARGET / NUNCA feature",       motivo="resultado del nudge"),
 dict(tabla="nudges", columna="opted_out_after", uso="TARGET (coste) / NUNCA feature", motivo="posterior al nudge"),
 dict(tabla="nudges", columna="exposure_no",     uso="FEATURE VALIDA",  motivo="conocida antes de enviar"),
 dict(tabla="nudges", columna="hours_since_last_nudge", uso="FEATURE VALIDA", motivo="conocida antes de enviar"),
 dict(tabla="customers", columna="savings_rate_90d_pct", uso="RIESGO: recalcular as-of corte", motivo="ventana 90d sin fecha, solapa el label"),
 dict(tabla="customers", columna="days_negative_90d",    uso="RIESGO: recalcular as-of corte", motivo="ventana 90d sin fecha, solapa el label"),
 dict(tabla="customers", columna="card_utilization_pct", uso="RIESGO: sin timestamp",          motivo="snapshot sin vintage declarado"),
 dict(tabla="customers", columna="revenue_ltm_mxn",      uso="RIESGO: sin timestamp",          motivo="LTM sin vintage; correlaciona con util"),
 dict(tabla="customers", columna="engagement_score",     uso="RIESGO ALTO",  motivo="determina volumen de eventos Y de nudges: casi el label"),
 dict(tabla="customers", columna="avg_balance_mxn",      uso="RIESGO: sin timestamp",          motivo="snapshot sin vintage"),
 dict(tabla="customers", columna="nps_last_score",       uso="FEATURE DEBIL", motivo="69% nulo; correlaciona con fragilidad -> imputar es informativo"),
 dict(tabla="customers", columna="has_* / demograficos / payday_day_of_month", uso="FEATURE VALIDA", motivo="estables, no posteriores"),
])
show("E4. Semaforo de leakage por columna", banned)
dump(banned, "06_leakage_table")

# nps vs fragilidad
nps = c.execute("""SELECT (card_utilization_pct>70 OR days_negative_90d>=3) fragil, count(*) n,
  round(100*avg(CASE WHEN nps_last_score IS NULL THEN 1 ELSE 0 END),2) "pct_nulo",
  round(avg(nps_last_score)::DOUBLE,2) nps_medio FROM customers GROUP BY 1""").df()
show("E5. nps_last_score: el patron de nulos es MCAR? y el valor informa fragilidad?", nps)
dump(nps, "06_nps_pattern")
