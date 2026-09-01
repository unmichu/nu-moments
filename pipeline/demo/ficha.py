"""
ficha.py — Construye la FICHA COMPLETA de un cliente a una fecha de corte (as-of).

Es el contrato de datos que el backend devuelve en `GET /customer/{id}?asof=...`.
Todo se calcula con `ts < asof` ESTRICTO (sin mirar el futuro).

Uso:
    from ficha import Store
    st = Store()                      # carga los 5 parquets en memoria (~1s)
    f  = st.ficha(6012345, "2026-06-09")

CLI:
    /tmp/hackenv/bin/python ficha.py 6012345 2026-06-09
"""
import json
import sys

import numpy as np
import pandas as pd

BASE = "/Users/miguel.soto/Downloads/hackathon/d3_intent/data"

# ---- acoplamientos verificados en gen_d3_intent.py -------------------------
SCREEN_OF_ACTION = {
    "spei_out": "transfer_spei", "bill_payment": "bill_payment", "deposit_in": "home",
    "savings_move": "savings_cajita", "loan_request": "loan_simulation",
    "limit_increase_request": "limit_increase", "card_payment": "card_statement",
    "investment_buy": "investments",
}
NUDGE_INTENT = {
    "savings_goal": "savings_move", "limit_increase": "limit_increase_request",
    "bill_reminder": "bill_payment", "loan_offer": "loan_request",
    "invest_start": "investment_buy", "payroll_portability": "deposit_in",
}
NUDGE_SCREEN = {k: SCREEN_OF_ACTION[v] for k, v in NUDGE_INTENT.items()}
SCREENS = ["home", "transfer_spei", "bill_payment", "card_statement", "savings_cajita",
           "loan_simulation", "limit_increase", "investments", "support", "card_settings"]
ACTIONS = list(SCREEN_OF_ACTION)
NUDGES = list(NUDGE_INTENT)

CAP_EXPOSICION = 2          # derivado en CONTEXTO.md 3.2
ON_TIME_H = 24
WARM_H = 168


def _j(v):
    """numpy -> json-safe."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else round(float(v), 4)
    if isinstance(v, pd.Timestamp):
        return v.isoformat(sep=" ")
    return v


class Store:
    """Las 5 tablas en memoria + índices por customer_id."""

    def __init__(self, base=BASE):
        self.cust = pd.read_parquet(f"{base}/customers.parquet").set_index("customer_id")
        self.ev = pd.read_parquet(f"{base}/app_events.parquet").sort_values(
            ["customer_id", "event_ts"]).set_index("customer_id")
        self.fa = pd.read_parquet(f"{base}/financial_actions.parquet").sort_values(
            ["customer_id", "action_ts"]).set_index("customer_id")
        self.nu = pd.read_parquet(f"{base}/nudges.parquet").sort_values(
            ["customer_id", "shown_ts"]).set_index("customer_id")
        self.oc = pd.read_parquet(f"{base}/nudge_outcomes.parquet").set_index("nudge_id")

    # -- accesos rápidos (index lookup, O(log n)) ---------------------------
    def _ev(self, cid, asof):
        try:
            d = self.ev.loc[[cid]]
        except KeyError:
            return self.ev.iloc[0:0]
        return d[d.event_ts < asof]

    def _fa(self, cid, asof):
        try:
            d = self.fa.loc[[cid]]
        except KeyError:
            return self.fa.iloc[0:0]
        return d[d.action_ts < asof]

    def _nu(self, cid, asof):
        try:
            d = self.nu.loc[[cid]]
        except KeyError:
            return self.nu.iloc[0:0]
        return d[d.shown_ts < asof]

    # -----------------------------------------------------------------------
    def ficha(self, cid, asof, n_ev=15, n_fa=10):
        asof = pd.Timestamp(asof)
        c = self.cust.loc[cid]
        ev, fa, nu = self._ev(cid, asof), self._fa(cid, asof), self._nu(cid, asof)

        # ---------- 1. perfil ----------
        fragil = bool(c.card_utilization_pct > 70 or c.days_negative_90d >= 3)
        perfil = {
            "customer_id": int(cid),
            "edad": _j(c.age), "estado": c.state,
            "antiguedad_meses": _j(c.tenure_months),
            "banda_ingreso": c.income_band,
            "ingreso_mensual_est_mxn": _j(c.monthly_income_est_mxn),
            "dia_de_pago": _j(c.payday_day_of_month),
            "productos": {
                "cuenta_nu": _j(c.has_cuenta_nu), "cajita_turbo": _j(c.has_cajita_turbo),
                "prestamo_personal": _j(c.has_personal_loan), "inversiones": _j(c.has_investments),
                "nomina_portada": _j(c.has_payroll_portability),
            },
            "situacion_financiera": {
                "saldo_promedio_mxn": _j(c.avg_balance_mxn),
                "utilizacion_tarjeta_pct": _j(c.card_utilization_pct),
                "dias_en_negativo_90d": _j(c.days_negative_90d),
                "tasa_ahorro_90d_pct": _j(c.savings_rate_90d_pct),
                "nps_ultimo": _j(c.nps_last_score),
            },
            "solo_modelo": {   # NO mostrar al usuario final
                "engagement_score": _j(c.engagement_score),
                "revenue_ltm_mxn": _j(c.revenue_ltm_mxn),
                "es_fragil": fragil,
            },
        }

        # ---------- 2. movimientos ----------
        def agg(win_d):
            w = fa[fa.action_ts >= asof - pd.Timedelta(days=win_d)]
            out = {}
            for a in ACTIONS:
                s = w[w.action_type == a]
                if len(s):
                    out[a] = {"n": int(len(s)), "monto_total_mxn": round(float(s.amount_mxn.sum()), 2),
                              "monto_prom_mxn": round(float(s.amount_mxn.mean()), 2),
                              "n_recurrentes": int(s.is_recurring.sum())}
            return out

        ult = fa.tail(n_fa).sort_values("action_ts", ascending=False)
        movimientos = {
            "n_total_historico": int(len(fa)),
            "agregado_30d": agg(30),
            "agregado_90d": agg(90),
            "ultimos": [{"ts": _j(r.action_ts), "tipo": r.action_type,
                         "monto_mxn": _j(r.amount_mxn), "recurrente": _j(r.is_recurring)}
                        for r in ult.itertuples()],
        }

        # ---------- 3. navegación ----------
        recencia = {}
        for s in SCREENS:
            sub = ev[ev.screen == s]
            if len(sub):
                last = sub.event_ts.max()
                recencia[s] = {"ultima_vista": _j(last),
                               "horas_desde": round((asof - last).total_seconds() / 3600, 2),
                               "n_24h": int((sub.event_ts >= asof - pd.Timedelta(hours=24)).sum()),
                               "n_72h": int((sub.event_ts >= asof - pd.Timedelta(hours=72)).sum()),
                               "n_7d": int((sub.event_ts >= asof - pd.Timedelta(days=7)).sum()),
                               "hubo_start_24h": bool(((sub.event_ts >= asof - pd.Timedelta(hours=24)) &
                                                       (sub.action == "start")).any())}
        navegacion = {
            "n_eventos_24h": int((ev.event_ts >= asof - pd.Timedelta(hours=24)).sum()),
            "n_eventos_72h": int((ev.event_ts >= asof - pd.Timedelta(hours=72)).sum()),
            "n_eventos_7d": int((ev.event_ts >= asof - pd.Timedelta(days=7)).sum()),
            "recencia_por_pantalla": recencia,
            "ultimas_pantallas": [{"ts": _j(r.event_ts), "pantalla": r.screen, "accion": r.action}
                                  for r in ev.tail(n_ev).sort_values("event_ts", ascending=False).itertuples()],
        }

        # ---------- 4. historial de nudges ----------
        hist = {}
        for t in NUDGES:
            sub = nu[nu.nudge_type == t]
            hist[t] = {
                "exposiciones": int(len(sub)),
                "exposure_no_max": int(sub.exposure_no.max()) if len(sub) else 0,
                "n_enganchados": int(sub.engaged.sum()) if len(sub) else 0,
                "n_descartados": int(sub.dismissed.sum()) if len(sub) else 0,
                "ultimo_ts": _j(sub.shown_ts.max()) if len(sub) else None,
                "cupo_restante": max(0, CAP_EXPOSICION - int(len(sub))),
            }
        nudges = {
            "n_total": int(len(nu)),
            "opt_out": bool(nu.opted_out_after.any()) if len(nu) else False,
            "horas_desde_ultimo": round((asof - nu.shown_ts.max()).total_seconds() / 3600, 2) if len(nu) else None,
            "por_tipo": hist,
            "ultimos": [{"ts": _j(r.shown_ts), "tipo": r.nudge_type, "superficie": r.surface,
                         "exposure_no": int(r.exposure_no), "enganchado": _j(r.engaged),
                         "descartado": _j(r.dismissed)}
                        for r in nu.tail(8).sort_values("shown_ts", ascending=False).itertuples()],
        }

        # ---------- 5. señales de decisión (derivadas, para el modelo) ------
        dom = asof.day
        pd_day = int(c.payday_day_of_month)
        dias_a_payday = min((pd_day - dom) % 30, (dom - pd_day) % 30)
        senales = {}
        for t in NUDGES:
            scr = NUDGE_SCREEN[t]
            r = recencia.get(scr)
            h = r["horas_desde"] if r else None
            momento = "never" if h is None else ("on_time" if h <= ON_TIME_H
                                                 else "warm" if h <= WARM_H else "cold")
            senales[t] = {
                "pantalla_acoplada": scr, "horas_desde_senal": h, "momento": momento,
                "hubo_start_24h": bool(r["hubo_start_24h"]) if r else False,
                "exposure_no_siguiente": hist[t]["exposiciones"] + 1,
                "cupo_agotado": hist[t]["exposiciones"] >= CAP_EXPOSICION,
            }
        decision = {
            "asof": _j(asof),
            "es_fragil": fragil,
            "motivo_fragilidad": ([] if not fragil else
                                  ([f"utilizacion {c.card_utilization_pct:.1f}% > 70"] if c.card_utilization_pct > 70 else []) +
                                  ([f"{int(c.days_negative_90d)} dias en negativo >= 3"] if c.days_negative_90d >= 3 else [])),
            "dias_a_payday": int(dias_a_payday),
            "ventana_payday": bool(dias_a_payday <= 2),
            "senales_por_nudge": senales,
        }

        return {"perfil": perfil, "movimientos": movimientos, "navegacion": navegacion,
                "nudges": nudges, "decision": decision}


if __name__ == "__main__":
    cid = int(sys.argv[1]) if len(sys.argv) > 1 else 6000000
    asof = sys.argv[2] if len(sys.argv) > 2 else "2026-06-09"
    print(json.dumps(Store().ficha(cid, asof), indent=2, ensure_ascii=False))
