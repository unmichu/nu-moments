"""A/E. Rangos temporales, volumetria, nulos por columna, integridad de joins."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
common = import_module("00_common"); globals().update({k: v for k, v in vars(common).items() if not k.startswith("__")})
import pandas as pd, numpy as np

c = con()

# ---------- volumetria + rango temporal ----------
rows = []
for t, tscol in [("customers", None), ("app_events", "event_ts"),
                 ("financial_actions", "action_ts"), ("nudges", "shown_ts"),
                 ("nudge_outcomes", None)]:
    n = c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    nc = c.execute(f"SELECT count(DISTINCT customer_id) FROM {t}").fetchone()[0] if t != "nudge_outcomes" else None
    if tscol:
        mn, mx = c.execute(f"SELECT min({tscol}), max({tscol}) FROM {t}").fetchone()
        span = (mx - mn).days
    else:
        mn = mx = span = None
    rows.append(dict(tabla=t, filas=n, clientes=nc, ts_col=tscol, ts_min=mn, ts_max=mx, dias=span))
rng = pd.DataFrame(rows)
show("A1. Volumetria y rango temporal por tabla", rng)
dump(rng, "01_ranges")

# ---------- histograma diario por tabla (solape) ----------
daily = c.execute("""
SELECT d, sum(ev) ev, sum(ac) ac, sum(nu) nu FROM (
  SELECT CAST(event_ts AS DATE) d, 1 ev, 0 ac, 0 nu FROM app_events
  UNION ALL SELECT CAST(action_ts AS DATE), 0,1,0 FROM financial_actions
  UNION ALL SELECT CAST(shown_ts AS DATE), 0,0,1 FROM nudges
) GROUP BY d ORDER BY d
""").df()
print("\nA1b. Primeros/ultimos 5 dias (volumen diario, comprueba efectos de borde):")
print(pd.concat([daily.head(5), daily.tail(5)]).to_string(index=False))
dump(daily, "01_daily_volume")

# ---------- nulos por columna ----------
nul = []
for t in ["customers", "app_events", "financial_actions", "nudges", "nudge_outcomes"]:
    df = c.execute(f"SELECT * FROM {t} LIMIT 0").df()
    n = c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    for col in df.columns:
        k = c.execute(f'SELECT count(*) FROM {t} WHERE "{col}" IS NULL').fetchone()[0]
        nul.append(dict(tabla=t, columna=col, nulos=k, pct_nulos=round(100 * k / n, 2)))
nul = pd.DataFrame(nul)
show("E1. Nulos por columna (solo columnas con nulos)", nul[nul.nulos > 0])
dump(nul, "01_nulls")

# ---------- integridad de joins ----------
q = lambda s: c.execute(s).fetchone()[0]
integ = pd.DataFrame([
  dict(chequeo="app_events.customer_id huerfanos",       n=q("SELECT count(*) FROM app_events e LEFT JOIN customers c USING(customer_id) WHERE c.customer_id IS NULL")),
  dict(chequeo="financial_actions.customer_id huerfanos", n=q("SELECT count(*) FROM financial_actions f LEFT JOIN customers c USING(customer_id) WHERE c.customer_id IS NULL")),
  dict(chequeo="nudges.customer_id huerfanos",            n=q("SELECT count(*) FROM nudges x LEFT JOIN customers c USING(customer_id) WHERE c.customer_id IS NULL")),
  dict(chequeo="nudge_outcomes sin nudge",                n=q("SELECT count(*) FROM nudge_outcomes o LEFT JOIN nudges x USING(nudge_id) WHERE x.nudge_id IS NULL")),
  dict(chequeo="nudges sin outcome",                      n=q("SELECT count(*) FROM nudges x LEFT JOIN nudge_outcomes o USING(nudge_id) WHERE o.nudge_id IS NULL")),
  dict(chequeo="clientes sin ningun app_event",           n=q("SELECT count(*) FROM customers c LEFT JOIN (SELECT DISTINCT customer_id ci FROM app_events) e ON c.customer_id=e.ci WHERE e.ci IS NULL")),
  dict(chequeo="clientes sin ninguna financial_action",   n=q("SELECT count(*) FROM customers c LEFT JOIN (SELECT DISTINCT customer_id ci FROM financial_actions) f ON c.customer_id=f.ci WHERE f.ci IS NULL")),
  dict(chequeo="clientes sin ningun nudge",               n=q("SELECT count(*) FROM customers c LEFT JOIN (SELECT DISTINCT customer_id ci FROM nudges) x ON c.customer_id=x.ci WHERE x.ci IS NULL")),
  dict(chequeo="engaged & dismissed a la vez",            n=q("SELECT count(*) FROM nudges WHERE engaged AND dismissed")),
  dict(chequeo="engaged & opted_out_after a la vez",      n=q("SELECT count(*) FROM nudges WHERE engaged AND opted_out_after")),
])
show("E1b. Integridad referencial y consistencia de flags", integ)
dump(integ, "01_integrity")
