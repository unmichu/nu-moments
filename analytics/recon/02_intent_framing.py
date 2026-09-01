"""A. Framing del label de intencion: clase mayoritaria, acciones por cliente,
   ventanas candidatas (1/3/7/14d) tras varios cortes, multiclase vs multi-label."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
common = import_module("00_common"); globals().update({k: v for k, v in vars(common).items() if not k.startswith("__")})
import pandas as pd, numpy as np

c = con()
N_CUST = 38000

# ---------- efecto de borde ----------
edge = c.execute("""
SELECT CAST(action_ts AS DATE) d, count(*) n FROM financial_actions
GROUP BY d ORDER BY d LIMIT 8
""").df()
med = c.execute("SELECT median(n) FROM (SELECT CAST(action_ts AS DATE) d, count(*) n FROM financial_actions GROUP BY d)").fetchone()[0]
edge["ratio_vs_mediana"] = (edge.n / med).round(2)
show(f"A0. Efecto de borde al inicio (mediana diaria = {med:.0f} acciones)", edge)
dump(edge, "02_edge_effect")

# ---------- distribucion de action_type ----------
dist = c.execute("""
SELECT action_type, count(*) n,
       count(DISTINCT customer_id) clientes,
       round(avg(amount_mxn)::DOUBLE,0) monto_medio,
       round(100.0*avg(CASE WHEN is_recurring THEN 1 ELSE 0 END),1) pct_recurrente
FROM financial_actions GROUP BY action_type ORDER BY n DESC
""").df()
dist["pct_filas"] = (100 * dist.n / dist.n.sum()).round(2)
dist["pct_clientes_con_1+"] = (100 * dist.clientes / N_CUST).round(1)
dist = dist[["action_type","n","pct_filas","clientes","pct_clientes_con_1+","monto_medio","pct_recurrente"]]
show("A2. Distribucion de action_type (BASELINE de clase mayoritaria)", dist)
dump(dist, "02_action_type_dist")

# ---------- acciones por cliente ----------
per = c.execute("""
SELECT customer_id, count(*) n, count(DISTINCT action_type) tipos
FROM financial_actions GROUP BY customer_id
""").df()
per = per.set_index("customer_id").reindex(
    c.execute("SELECT customer_id FROM customers").df().customer_id).fillna(0)
q = per.n.describe(percentiles=[.01,.05,.25,.5,.75,.95,.99]).round(2)
qt = per.tipos.describe(percentiles=[.01,.05,.25,.5,.75,.95,.99]).round(2)
percust = pd.DataFrame({"acciones_por_cliente": q, "tipos_distintos_por_cliente": qt})
show("A3. Acciones por cliente (120 dias)", percust.reset_index().rename(columns={"index":"stat"}))
dump(percust, "02_actions_per_customer", index=True)
print(f"\n  clientes con 0 acciones: {(per.n==0).sum()}  ({100*(per.n==0).mean():.3f}%)")
print(f"  clientes con >=1 accion: {(per.n>0).sum()}")
print(f"  media tipos distintos: {per.tipos.mean():.2f} de 8")

# ---------- ventanas candidatas ----------
fa = c.execute("SELECT customer_id, action_ts, action_type FROM financial_actions").df()
fa["action_ts"] = pd.to_datetime(fa.action_ts)
cust_ids = c.execute("SELECT customer_id FROM customers").df().customer_id.to_numpy()
ACTIONS = sorted(fa.action_type.unique())

rows, mlrows = [], []
for cut_day in [90, 100, 105]:
    cut = START + pd.Timedelta(days=cut_day)
    for W in [1, 3, 7, 14]:
        end = cut + pd.Timedelta(days=W)
        if end > START + pd.Timedelta(days=DAYS): 
            pass
        w = fa[(fa.action_ts > cut) & (fa.action_ts <= end)]
        cov = w.customer_id.nunique()
        first = w.sort_values("action_ts").groupby("customer_id").action_type.first()
        vc = first.value_counts(normalize=True)
        rows.append(dict(corte_dia=cut_day, corte=cut.date(), ventana_d=W,
                         clientes_con_accion=cov, pct_cobertura=round(100*cov/N_CUST,1),
                         acciones=len(w), acciones_por_cliente_activo=round(len(w)/max(cov,1),2),
                         clase_mayoritaria=vc.index[0], pct_mayoritaria=round(100*vc.iloc[0],1),
                         entropia_bits=round(-(vc*np.log2(vc)).sum(),3)))
        if cut_day == 100:
            for a in ACTIONS:
                pos = w[w.action_type == a].customer_id.nunique()
                mlrows.append(dict(ventana_d=W, action_type=a, clientes_positivos=pos,
                                   prevalencia_pct=round(100*pos/N_CUST,2)))
win = pd.DataFrame(rows)
show("A4. Ventanas candidatas: cobertura + clase mayoritaria (label = PRIMERA accion tras el corte)", win)
dump(win, "02_windows")

ml = pd.DataFrame(mlrows).pivot(index="action_type", columns="ventana_d", values="prevalencia_pct")
ml.columns = [f"prev_%_{c}d" for c in ml.columns]
show("A5. Multi-label: prevalencia por accion (% de los 38k clientes con >=1, corte dia 100)", ml.reset_index())
dump(ml, "02_multilabel_prevalence", index=True)

# ---------- distribucion de clases dentro de los activos, ventana 7d, corte 100 ----------
cut = START + pd.Timedelta(days=100)
w7 = fa[(fa.action_ts > cut) & (fa.action_ts <= cut + pd.Timedelta(days=7))]
first7 = w7.sort_values("action_ts").groupby("customer_id").action_type.first().value_counts()
cls = (first7 / first7.sum() * 100).round(2).rename("pct_de_activos").reset_index()
cls.columns = ["action_type", "pct_de_activos"]
cls["n"] = first7.values
# comparar contra distribucion global de filas
cls = cls.merge(dist[["action_type","pct_filas"]], on="action_type")
cls["ratio_vs_global"] = (cls.pct_de_activos / cls.pct_filas).round(2)
show("A6. Clase de 'primera accion en 7d' (corte d100) vs distribucion global de filas", cls)
dump(cls, "02_first_action_7d")

# ---------- persistencia: el mejor baseline no trivial ----------
# baseline 'ultima accion del cliente antes del corte' -> acierta la primera de la ventana?
hist = fa[fa.action_ts <= cut].sort_values("action_ts").groupby("customer_id").action_type.last()
mode = fa[fa.action_ts <= cut].groupby(["customer_id","action_type"]).size().reset_index(name="n")
mode = mode.sort_values(["customer_id","n"]).groupby("customer_id").action_type.last()
truth = w7.sort_values("action_ts").groupby("customer_id").action_type.first()
base = pd.DataFrame({"truth": truth}).join(hist.rename("last")).join(mode.rename("mode"))
bl = pd.DataFrame([
    dict(baseline="clase mayoritaria global (spei_out)", accuracy=round(100*(base.truth=="spei_out").mean(),2)),
    dict(baseline="ultima accion del cliente",           accuracy=round(100*(base.truth==base["last"]).mean(),2)),
    dict(baseline="accion mas frecuente del cliente",    accuracy=round(100*(base.truth==base["mode"]).mean(),2)),
])
show("A7. Baselines a batir (ventana 7d, corte d100, sobre clientes activos)", bl)
dump(bl, "02_baselines")
