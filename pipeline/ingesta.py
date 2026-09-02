"""ING-1 · Ingesta y normalización a grano de evento.

Carga las 5 tablas de `data/*.parquet`, las normaliza a un único flujo con
grano de evento (`customer_id, ts, fuente, tipo, ...`) y deja constancia de
cada etapa en `pipeline/evidencias/ejecucion.jsonl` (ING-8).

Todo lo que expone este módulo respeta el corte temporal **estricto**
`ts < asof`. Ninguna función mira hacia adelante: es la garantía sobre la que
se apoyan las pruebas anti-fuga de ING-7.

Uso como librería:
    from pipeline.ingesta import Store
    st = Store.cargar("data")
    f  = st.ficha(6024615, "2026-06-16")

Uso como script (regenera evidencias):
    .venv/bin/python pipeline/ingesta.py
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# Permite `python pipeline/ingesta.py` además de `from pipeline.ingesta import Store`.
if __package__ in (None, ""):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.mapas import (
    ACCIONES,
    CAP_EXPOSICIONES,
    FRAGIL_DIAS_NEGATIVOS,
    FRAGIL_UTILIZACION_PCT,
    LAMBDA_DEFECTO,
    PANTALLAS,
    PESO_AHORRO,
    PRODUCTO_A_PANTALLA,
    TODOS_LOS_PRODUCTOS,
    UMBRAL_ON_TIME_H,
    UMBRAL_WARM_H,
)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_DATOS = os.path.join(RAIZ, "data")
RUTA_EVIDENCIAS = os.path.join(RAIZ, "pipeline", "evidencias")
ARCHIVO_EVIDENCIAS = os.path.join(RUTA_EVIDENCIAS, "ejecucion.jsonl")

TABLAS = ["customers", "app_events", "financial_actions", "nudges", "nudge_outcomes"]

# Ventana real del generador. Se usa para la puerta S6.
INICIO_DATOS = pd.Timestamp("2026-03-01")
FIN_DATOS = pd.Timestamp("2026-06-29")
DIAS_CONTAMINADOS_INICIO = 3   # BA-3: el primer día tiene 7.36x la mediana de acciones
DIAS_CONTAMINADOS_FIN = 3      # BA-3: el final está censurado (label de 7 días)

# Pantalla acoplada a cada acción financiera, para el timeline unificado.
PANTALLA_DE_ACCION = {
    "spei_out": "transfer_spei",
    "bill_payment": "bill_payment",
    "deposit_in": "home",
    "savings_move": "savings_cajita",
    "loan_request": "loan_simulation",
    "limit_increase_request": "limit_increase",
    "card_payment": "card_statement",
    "investment_buy": "investments",
}


# --------------------------------------------------------------------------
# ING-8 · Evidencias de ejecución
# --------------------------------------------------------------------------
def registrar_evidencia(etapa, filas_entrada, filas_salida, t0, **extra):
    """Una línea por etapa: filas dentro, filas fuera, duración y marca de tiempo."""
    fila = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "etapa": etapa,
        "filas_entrada": int(filas_entrada),
        "filas_salida": int(filas_salida),
        "duracion_s": round(time.perf_counter() - t0, 4),
    }
    fila.update(extra)
    os.makedirs(RUTA_EVIDENCIAS, exist_ok=True)
    with open(ARCHIVO_EVIDENCIAS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
    return fila


# --------------------------------------------------------------------------
def json_seguro(v):
    """numpy/pandas -> tipos JSON. `None` explícito para los nulos."""
    if v is None:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if np.isnan(f) else round(f, 4)
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.isoformat(sep=" ")
    if v is pd.NaT:
        return None
    return v


def zona_contaminada(asof):
    """S6 · ¿la fecha cae fuera de la ventana usable de los datos?

    Devuelve (bool, motivo). Los 3 primeros días son un artefacto del generador
    y los 3 últimos están censurados por la ventana de label de 7 días.
    """
    asof = pd.Timestamp(asof)
    if asof < INICIO_DATOS or asof > FIN_DATOS:
        return True, "la fecha está fuera de la ventana de datos (2026-03-01 a 2026-06-28)"
    if asof < INICIO_DATOS + pd.Timedelta(days=DIAS_CONTAMINADOS_INICIO):
        return True, "los primeros 3 días del panel son un artefacto del generador"
    if asof > FIN_DATOS - pd.Timedelta(days=DIAS_CONTAMINADOS_FIN):
        return True, "los últimos 3 días están censurados por la ventana de 7 días"
    return False, None


class Store:
    """Las 5 tablas en memoria, más el flujo unificado a grano de evento."""

    def __init__(self, cust, ev, fa, nu, oc, eventos, base):
        self.cust = cust
        self.ev = ev
        self.fa = fa
        self.nu = nu
        self.oc = oc
        self.eventos = eventos
        self.base = base
        self._tabla_valor = {}

    # ---------------------------------------------------------------- carga
    @classmethod
    def cargar(cls, base=RUTA_DATOS, evidencias=True):
        base = os.path.abspath(base)
        faltan = [t for t in TABLAS if not os.path.exists(os.path.join(base, f"{t}.parquet"))]
        if faltan:
            # Nada de valores por defecto silenciosos: si falta una tabla, revienta.
            raise FileNotFoundError(f"faltan tablas en {base}: {', '.join(faltan)}")

        t0 = time.perf_counter()
        crudas = {t: pd.read_parquet(os.path.join(base, f"{t}.parquet")) for t in TABLAS}
        n_in = sum(len(d) for d in crudas.values())
        if evidencias:
            registrar_evidencia("ingesta.lectura", n_in, n_in, t0, base=os.path.relpath(base),
                                por_tabla={t: len(d) for t, d in crudas.items()})

        t1 = time.perf_counter()
        cust = crudas["customers"].set_index("customer_id").sort_index()
        ev = (crudas["app_events"].sort_values(["customer_id", "event_ts"])
              .set_index("customer_id"))
        fa = (crudas["financial_actions"].sort_values(["customer_id", "action_ts"])
              .set_index("customer_id"))
        nu = (crudas["nudges"].sort_values(["customer_id", "shown_ts"])
              .set_index("customer_id"))
        oc = crudas["nudge_outcomes"].set_index("nudge_id")
        if evidencias:
            registrar_evidencia("ingesta.indexado", n_in, n_in, t1,
                                clientes=int(len(cust)))

        t2 = time.perf_counter()
        eventos = cls._normalizar_a_evento(crudas)
        if evidencias:
            registrar_evidencia(
                "ingesta.grano_evento",
                len(crudas["app_events"]) + len(crudas["financial_actions"]) + len(crudas["nudges"]),
                len(eventos), t2,
                fuentes=eventos["fuente"].value_counts().to_dict())

        st = cls(cust, ev, fa, nu, oc, eventos, base)

        t3 = time.perf_counter()
        huerf = st.huerfanos()
        if evidencias:
            registrar_evidencia("ingesta.integridad", n_in, n_in, t3, huerfanos=huerf)
        return st

    @staticmethod
    def _normalizar_a_evento(crudas):
        """Las 3 tablas con marca de tiempo, unificadas a un solo grano de evento.

        Columnas: customer_id, ts, fuente, tipo, pantalla, detalle, monto_mxn.
        Es la vista que alimenta la línea de tiempo de la ficha y la que hace
        comprobable el corte `ts < asof` sobre una sola estructura.
        """
        e = crudas["app_events"]
        a = pd.DataFrame({
            "customer_id": e["customer_id"].astype("int32"),
            "ts": e["event_ts"],
            "fuente": "app",
            "tipo": e["screen"],
            "pantalla": e["screen"],
            "detalle": e["action"],
            "monto_mxn": np.nan,
        })
        f = crudas["financial_actions"]
        b = pd.DataFrame({
            "customer_id": f["customer_id"].astype("int32"),
            "ts": f["action_ts"],
            "fuente": "financiera",
            "tipo": f["action_type"],
            "pantalla": f["action_type"].map(PANTALLA_DE_ACCION),
            "detalle": np.where(f["is_recurring"], "recurrente", "puntual"),
            "monto_mxn": f["amount_mxn"].astype("float32"),
        })
        n = crudas["nudges"]
        c = pd.DataFrame({
            "customer_id": n["customer_id"].astype("int32"),
            "ts": n["shown_ts"],
            "fuente": "aviso",
            "tipo": n["nudge_type"],
            "pantalla": n["nudge_type"].map(PRODUCTO_A_PANTALLA),
            "detalle": n["surface"],
            "monto_mxn": np.nan,
        })
        out = pd.concat([a, b, c], ignore_index=True)
        for col in ("fuente", "tipo", "pantalla", "detalle"):
            out[col] = out[col].astype("category")
        return out.sort_values(["customer_id", "ts"]).set_index("customer_id")

    # ------------------------------------------------------------ integridad
    def huerfanos(self):
        """BA-9 · 0 huérfanos en las tres tablas que apuntan a customers."""
        cids = set(self.cust.index)
        return {
            "app_events": int(len(set(self.ev.index) - cids)),
            "financial_actions": int(len(set(self.fa.index) - cids)),
            "nudges": int(len(set(self.nu.index) - cids)),
            "nudge_outcomes": int(len(set(self.oc.index) - set(self.nu["nudge_id"]))),
        }

    # ------------------------------------------------------- cortes estrictos
    def _sub(self, tabla, cid, col, asof):
        try:
            d = tabla.loc[[cid]]
        except KeyError:
            return tabla.iloc[0:0]
        return d[d[col] < asof]          # ESTRICTO. Sin esto, fuga.

    def eventos_de(self, cid, asof):
        return self._sub(self.eventos, cid, "ts", pd.Timestamp(asof))

    def existe(self, cid):
        return int(cid) in self.cust.index

    # ------------------------------------------------------------- la ficha
    def ficha(self, cid, asof, n_ev=15, n_fa=10):
        """Ficha as-of del cliente. Todo con `ts < asof` estricto."""
        cid = int(cid)
        asof = pd.Timestamp(asof)
        if cid not in self.cust.index:
            raise KeyError(f"cliente {cid} no existe")
        c = self.cust.loc[cid]
        ev = self._sub(self.ev, cid, "event_ts", asof)
        fa = self._sub(self.fa, cid, "action_ts", asof)
        nu = self._sub(self.nu, cid, "shown_ts", asof)

        # 1 · perfil -------------------------------------------------------
        fragil = bool(c.card_utilization_pct > FRAGIL_UTILIZACION_PCT
                      or c.days_negative_90d >= FRAGIL_DIAS_NEGATIVOS)
        motivo_fragilidad = []
        if c.card_utilization_pct > FRAGIL_UTILIZACION_PCT:
            motivo_fragilidad.append(
                f"utilización {c.card_utilization_pct:.2f} % (arriba de {FRAGIL_UTILIZACION_PCT:.2f} %)")
        if c.days_negative_90d >= FRAGIL_DIAS_NEGATIVOS:
            motivo_fragilidad.append(
                f"{int(c.days_negative_90d)} días en negativo en los últimos 90")

        perfil = {
            "customer_id": cid,
            "edad": json_seguro(c.age),
            "estado": c.state,
            "antiguedad_meses": json_seguro(c.tenure_months),
            "banda_ingreso": c.income_band,
            "ingreso_mensual_est_mxn": json_seguro(c.monthly_income_est_mxn),
            "dia_de_pago": json_seguro(c.payday_day_of_month),
            "productos": {
                "cuenta_nu": json_seguro(c.has_cuenta_nu),
                "cajita_turbo": json_seguro(c.has_cajita_turbo),
                "prestamo_personal": json_seguro(c.has_personal_loan),
                "inversiones": json_seguro(c.has_investments),
                "nomina_portada": json_seguro(c.has_payroll_portability),
            },
            "situacion_financiera": {
                "saldo_promedio_mxn": json_seguro(c.avg_balance_mxn),
                "utilizacion_tarjeta_pct": json_seguro(c.card_utilization_pct),
                "dias_en_negativo_90d": json_seguro(c.days_negative_90d),
                "tasa_ahorro_90d_pct": json_seguro(c.savings_rate_90d_pct),
                "nps_ultimo": json_seguro(c.nps_last_score),
            },
            "solo_modelo": {   # no se muestra al cliente final
                "engagement_score": json_seguro(c.engagement_score),
                "revenue_ltm_mxn": json_seguro(c.revenue_ltm_mxn),
                "es_fragil": fragil,
            },
        }

        # 2 · movimientos --------------------------------------------------
        def agregado(dias):
            w = fa[fa.action_ts >= asof - pd.Timedelta(days=dias)]
            out = {}
            for a in ACCIONES:
                s = w[w.action_type == a]
                if len(s):
                    out[a] = {"n": int(len(s)),
                              "monto_total_mxn": round(float(s.amount_mxn.sum()), 2),
                              "monto_prom_mxn": round(float(s.amount_mxn.mean()), 2),
                              "n_recurrentes": int(s.is_recurring.sum())}
            return out

        ultimos_fa = fa.tail(n_fa).sort_values("action_ts", ascending=False)
        movimientos = {
            "n_total_historico": int(len(fa)),
            "agregado_30d": agregado(30),
            "agregado_90d": agregado(90),
            "ultimos": [{"ts": json_seguro(r.action_ts), "tipo": r.action_type,
                         "monto_mxn": json_seguro(r.amount_mxn),
                         "recurrente": json_seguro(r.is_recurring)}
                        for r in ultimos_fa.itertuples()],
        }

        # 3 · navegación ---------------------------------------------------
        recencia = {}
        for s in PANTALLAS:
            sub = ev[ev.screen == s]
            if not len(sub):
                continue
            ultima = sub.event_ts.max()
            recencia[s] = {
                "ultima_vista": json_seguro(ultima),
                "horas_desde": round((asof - ultima).total_seconds() / 3600, 2),
                "n_24h": int((sub.event_ts >= asof - pd.Timedelta(hours=24)).sum()),
                "n_72h": int((sub.event_ts >= asof - pd.Timedelta(hours=72)).sum()),
                "n_7d": int((sub.event_ts >= asof - pd.Timedelta(days=7)).sum()),
                "hubo_start_24h": bool(((sub.event_ts >= asof - pd.Timedelta(hours=24))
                                        & (sub.action == "start")).any()),
            }
        navegacion = {
            "n_eventos_24h": int((ev.event_ts >= asof - pd.Timedelta(hours=24)).sum()),
            "n_eventos_72h": int((ev.event_ts >= asof - pd.Timedelta(hours=72)).sum()),
            "n_eventos_7d": int((ev.event_ts >= asof - pd.Timedelta(days=7)).sum()),
            "recencia_por_pantalla": recencia,
            "ultimas_pantallas": [
                {"ts": json_seguro(r.event_ts), "pantalla": r.screen, "accion": r.action}
                for r in ev.tail(n_ev).sort_values("event_ts", ascending=False).itertuples()],
        }

        # 4 · historial de avisos -------------------------------------------
        por_tipo = {}
        for t in TODOS_LOS_PRODUCTOS:
            sub = nu[nu.nudge_type == t]
            por_tipo[t] = {
                "exposiciones": int(len(sub)),
                "exposure_no_max": int(sub.exposure_no.max()) if len(sub) else 0,
                "n_enganchados": int(sub.engaged.sum()) if len(sub) else 0,
                "n_descartados": int(sub.dismissed.sum()) if len(sub) else 0,
                "ultimo_ts": json_seguro(sub.shown_ts.max()) if len(sub) else None,
                "cupo_restante": max(0, CAP_EXPOSICIONES - int(len(sub))),
            }
        avisos = {
            "n_total": int(len(nu)),
            "opt_out": bool(nu.opted_out_after.any()) if len(nu) else False,
            "horas_desde_ultimo": (round((asof - nu.shown_ts.max()).total_seconds() / 3600, 2)
                                   if len(nu) else None),
            "por_tipo": por_tipo,
            "ultimos": [{"ts": json_seguro(r.shown_ts), "tipo": r.nudge_type,
                         "superficie": r.surface, "exposure_no": int(r.exposure_no),
                         "enganchado": json_seguro(r.engaged),
                         "descartado": json_seguro(r.dismissed)}
                        for r in nu.tail(8).sort_values("shown_ts", ascending=False).itertuples()],
        }

        # 5 · señales derivadas para la política ----------------------------
        dia = asof.day
        pago = int(c.payday_day_of_month)
        dias_a_payday = min((pago - dia) % 30, (dia - pago) % 30)
        senales = {}
        for t in TODOS_LOS_PRODUCTOS:
            pantalla = PRODUCTO_A_PANTALLA.get(t)
            r = recencia.get(pantalla) if pantalla else None
            h = r["horas_desde"] if r else None
            if h is None:
                momento = "never"
            elif h <= UMBRAL_ON_TIME_H:
                momento = "on_time"
            elif h <= UMBRAL_WARM_H:
                momento = "warm"
            else:
                momento = "cold"
            senales[t] = {
                "pantalla_acoplada": pantalla,
                "horas_desde_senal": h,
                "momento": momento,
                "hubo_start_24h": bool(r["hubo_start_24h"]) if r else False,
                "exposure_no_siguiente": por_tipo[t]["exposiciones"] + 1,
                "cupo_agotado": por_tipo[t]["exposiciones"] >= CAP_EXPOSICIONES,
                "n_descartados": por_tipo[t]["n_descartados"],
            }
        contaminada, motivo_fecha = zona_contaminada(asof)
        decision = {
            "asof": json_seguro(asof),
            "es_fragil": fragil,
            "motivo_fragilidad": motivo_fragilidad,
            "dias_a_payday": int(dias_a_payday),
            "ventana_payday": bool(dias_a_payday <= 2),
            "fecha_contaminada": contaminada,
            "motivo_fecha": motivo_fecha,
            "senales_por_nudge": senales,
        }

        # 6 · línea de tiempo unificada (grano de evento) --------------------
        tl = self.eventos_de(cid, asof).tail(25).sort_values("ts", ascending=False)
        linea_tiempo = [{"ts": json_seguro(r.ts), "fuente": str(r.fuente),
                         "tipo": str(r.tipo), "detalle": str(r.detalle),
                         "monto_mxn": json_seguro(r.monto_mxn)}
                        for r in tl.itertuples()]

        return {"perfil": perfil, "movimientos": movimientos, "navegacion": navegacion,
                "nudges": avisos, "decision": decision, "linea_tiempo": linea_tiempo}

    # ------------------------------------------------------- tabla de valor
    def tabla_valor(self, lmbda=LAMBDA_DEFECTO, peso_ahorro=PESO_AHORRO):
        """MODELO Z · aritmética determinista sobre los resultados a 90 días.

            V = (−Δdías_negativos) + (Δingreso / λ) + w_a · (Δahorro_pp / 10)

        Se mide sobre los avisos que el cliente **enganchó** (efecto del
        tratamiento realizado); los no enganchados son el contrafactual y dan
        ~0 en todo. Reproduce V(ahorro,266)=+0.700 y V(línea,266)=−0.077.
        """
        clave = (round(float(lmbda), 6), round(float(peso_ahorro), 6))
        if clave in self._tabla_valor:
            return self._tabla_valor[clave]
        t0 = time.perf_counter()
        n = self.nu.reset_index()[["nudge_id", "nudge_type", "engaged"]]
        j = n.merge(self.oc, left_on="nudge_id", right_index=True, how="inner")
        j = j[j["engaged"]]
        g = j.groupby("nudge_type", observed=True).agg(
            d_dias_negativos=("delta_days_negative_90d", "mean"),
            d_ahorro_pp=("delta_savings_rate_pct_90d", "mean"),
            d_ingreso_mxn=("delta_revenue_mxn_90d", "mean"),
            n=("nudge_id", "size"))
        tabla = {}
        for producto, r in g.iterrows():
            v = (-r.d_dias_negativos) + (r.d_ingreso_mxn / lmbda) + peso_ahorro * (r.d_ahorro_pp / 10.0)
            tabla[str(producto)] = {
                "V": round(float(v), 4),
                "d_dias_negativos": round(float(r.d_dias_negativos), 4),
                "d_ahorro_pp": round(float(r.d_ahorro_pp), 4),
                "d_ingreso_mxn": round(float(r.d_ingreso_mxn), 2),
                "n_enganchados": int(r.n),
            }
        self._tabla_valor[clave] = tabla
        registrar_evidencia("valor.tabla_determinista", len(j), len(tabla), t0,
                            lmbda=float(lmbda), peso_ahorro=float(peso_ahorro))
        return tabla


# --------------------------------------------------------------------------
def main():
    t0 = time.perf_counter()
    st = Store.cargar()
    print(f"tablas cargadas en {time.perf_counter() - t0:.2f} s")
    print(f"  clientes            {len(st.cust):,}")
    print(f"  eventos de app      {len(st.ev):,}")
    print(f"  acciones            {len(st.fa):,}")
    print(f"  avisos              {len(st.nu):,}")
    print(f"  resultados          {len(st.oc):,}")
    print(f"  grano de evento     {len(st.eventos):,} filas")
    print(f"  RAM aprox           {st.eventos.memory_usage(deep=True).sum() / 1e6:.2f} MB (timeline)")
    print(f"  huérfanos           {st.huerfanos()}")
    print("\ntabla de valor (λ=266):")
    for p, v in sorted(st.tabla_valor().items(), key=lambda kv: -kv[1]["V"]):
        print(f"  {p:22s} V={v['V']:+.4f}   n={v['n_enganchados']:,}")
    print(f"\nevidencias en {ARCHIVO_EVIDENCIAS}")


if __name__ == "__main__":
    main()
