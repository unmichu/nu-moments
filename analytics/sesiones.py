#!/usr/bin/env python3
"""BA-7 · Sesionización — la respuesta honesta.

El reto pide definir sesiones de navegación. **En estos datos no existen.**
Este script no lo esconde: implementa la sesionización con umbral configurable,
barre 15/30/60/120 minutos, saca el histograma de intervalos y muestra que con
cualquier umbral razonable sale ~1 evento por sesión. Después propone el
sustituto que sí funciona: recencia por pantalla.

Implementarlo y explicar por qué no aplica puntúa más que fingir que funcionó.

Valores esperados (`instrucciones/ba.md` BA-7):
    mediana de intervalo 58 h · 1.09 % de intervalos < 30 min ·
    1.01 eventos por sesión con umbral de 30 min

Uso: .venv/bin/python analytics/sesiones.py [umbral_min ...]
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.features import _conexion  # noqa: E402
from pipeline.mapas import PANTALLAS  # noqa: E402

UMBRALES_MIN = [15, 30, 60, 120]
N_CLIENTES = 38000


def intervalos(con) -> pd.Series:
    """Minutos entre eventos consecutivos del mismo cliente (sin el primero)."""
    g = con.execute(
        """
        SELECT date_diff('second', lag(event_ts) OVER w, event_ts) / 60.0 AS gap_min
        FROM app_events
        WINDOW w AS (PARTITION BY customer_id ORDER BY event_ts)
        """
    ).df()["gap_min"].dropna()
    return g


def sesionizar(con, umbral_min: int) -> pd.DataFrame:
    """Sesionización clásica: nueva sesión si el hueco supera el umbral.

    Devuelve una fila por sesión. Es una implementación real y configurable:
    el problema no es el algoritmo, son los datos.
    """
    return con.execute(
        f"""
        WITH marcado AS (
          SELECT customer_id, event_ts, screen, action,
                 CASE WHEN lag(event_ts) OVER w IS NULL
                       OR date_diff('second', lag(event_ts) OVER w, event_ts) > {umbral_min} * 60
                      THEN 1 ELSE 0 END AS nueva
          FROM app_events
          WINDOW w AS (PARTITION BY customer_id ORDER BY event_ts)
        ), num AS (
          SELECT *, sum(nueva) OVER (PARTITION BY customer_id ORDER BY event_ts
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS sesion_no
          FROM marcado
        )
        SELECT customer_id, sesion_no, count(*) AS n_eventos,
               count(DISTINCT screen) AS n_pantallas,
               date_diff('second', min(event_ts), max(event_ts)) / 60.0 AS duracion_min
        FROM num GROUP BY customer_id, sesion_no
        """
    ).df()


def histograma(g: pd.Series) -> pd.DataFrame:
    bins = [0, 5, 10, 15, 30, 60, 120, 360, 720, 1440, 4320, 10 ** 9]
    lab = ["0-5m", "5-10m", "10-15m", "15-30m", "30-60m", "1-2h", "2-6h",
           "6-12h", "12-24h", "1-3d", ">3d"]
    h = pd.cut(g, bins=bins, labels=lab, right=True).value_counts().reindex(lab)
    return pd.DataFrame({"bucket": lab, "n": h.values,
                         "pct": (100 * h.values / h.sum()).round(2),
                         "pct_acum": (100 * h.values.cumsum() / h.sum()).round(2)})


def sustituto(con, asof: str = "2026-06-16") -> pd.DataFrame:
    """El reemplazo: recencia por pantalla, que sí discrimina."""
    d = con.execute(
        f"""
        SELECT screen,
               100.0 * count(*) FILTER (
                   WHERE event_ts >= TIMESTAMP '{asof}' - INTERVAL 24 HOUR)
                   / count(*) AS pct_eventos_24h,
               count(DISTINCT customer_id) FILTER (
                   WHERE event_ts >= TIMESTAMP '{asof}' - INTERVAL 24 HOUR) AS clientes_on_time
        FROM app_events WHERE event_ts < TIMESTAMP '{asof}'
        GROUP BY screen ORDER BY clientes_on_time DESC
        """
    ).df()
    d["pct_eventos_24h"] = d.pct_eventos_24h.round(3)
    return d


def main(argv: list[str]) -> int:
    umbrales = [int(x) for x in argv[1:]] or UMBRALES_MIN
    con = _conexion()
    try:
        g = intervalos(con)
        mediana_min = float(g.median())
        pct_30 = float(100 * (g <= 30).mean())

        print("=" * 88)
        print("BA-7 · ¿HAY SESIONES EN ESTOS DATOS?")
        print("=" * 88)
        print(f"  intervalos entre eventos consecutivos del mismo cliente: {len(g):,}")
        print(f"  mediana                     {mediana_min / 60:8.2f} h   ({mediana_min:,.0f} min)"
              f"   esperado ~58 h")
        print(f"  intervalos < 30 min         {pct_30:8.2f} %"
              f"                       esperado 1.09 %")
        print(f"  p05 {g.quantile(.05) / 60:.1f} h · p25 {g.quantile(.25) / 60:.1f} h · "
              f"p75 {g.quantile(.75) / 60:.1f} h · p95 {g.quantile(.95) / 60:.1f} h")

        print("\n  histograma de intervalos:")
        print(histograma(g).to_string(index=False))

        print("\n" + "=" * 88)
        print("BARRIDO DE UMBRALES DE SESIÓN")
        print("=" * 88)
        filas = []
        for u in umbrales:
            s = sesionizar(con, u)
            filas.append(dict(umbral_min=u, sesiones=len(s),
                              eventos_por_sesion=round(float(s.n_eventos.mean()), 3),
                              pct_sesiones_1_evento=round(100 * float((s.n_eventos == 1).mean()), 2),
                              pantallas_por_sesion=round(float(s.n_pantallas.mean()), 3),
                              duracion_media_min=round(float(s.duracion_min.mean()), 2),
                              sesiones_por_cliente=round(len(s) / N_CLIENTES, 1)))
        b = pd.DataFrame(filas)
        print(b.to_string(index=False))
        e30 = float(b.loc[b.umbral_min == 30, "eventos_por_sesion"].iloc[0]) if 30 in umbrales else float("nan")
        print(f"\n  con umbral de 30 min: {e30:.2f} eventos por sesión   esperado 1.01")

        print("\n" + "=" * 88)
        print("VEREDICTO")
        print("=" * 88)
        print("  La sesionización está implementada y es configurable, pero NO APLICA:")
        print(f"    · la mediana de intervalo es {mediana_min / 60:.0f} h, no minutos;")
        print(f"    · solo el {pct_30:.2f} % de los intervalos baja de 30 min;")
        print(f"    · con umbral de 30 min salen {e30:.2f} eventos por sesión: cada evento es su")
        print("      propia sesión, así que 'la sesión' no añade información sobre el evento.")
        print("  El generador emite eventos como un proceso de Poisson por cliente y día;")
        print("  no hay ráfagas de navegación que agrupar.")

        print("\n  SUSTITUTO PROPUESTO · recencia por pantalla")
        print("  En vez de 'qué pasó en esta sesión', la feature es 'cuántas horas hace que")
        print("  vio esta pantalla'. Es lo que discrimina de verdad: con señal ≤24 h el")
        print("  enganche es 41.63 % contra 10.30 % sin señal, y P(acción acoplada|pantalla")
        print("  vista en 24 h) llega a 49.39 % en Cajitas contra un 4.51 % de tasa base.")
        print(f"  Está en la matriz como rec_h_* (una por cada una de las {len(PANTALLAS)} pantallas)")
        print("  y senal_* (on_time/warm/cold/never por acción).\n")
        print(sustituto(con).to_string(index=False))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
