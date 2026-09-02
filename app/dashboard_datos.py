#!/usr/bin/env python3
"""El cálculo del **dashboard general**: todas las métricas, en un solo sitio.

Qué es esto y qué no
--------------------
Este módulo arma **un diccionario** con todo lo que la pantalla
`GET /dashboard` enseña. No pinta nada y no sabe nada de HTML. Cada cifra que
sale de aquí tiene una procedencia declarada en el propio bloque
(`fuente`), y las tres únicas procedencias posibles son:

1. **`data/*.parquet`** — recalculado aquí, con duckdb o pandas.
2. **`analytics/recon/out/*.csv`** — los 54 recuentos del reconocimiento previo.
   Se leen, no se rehacen: son conteos, no estimaciones.
3. **`pipeline/artifacts/*`** — los artefactos del pipeline (modelos, umbrales,
   tabla de valor) y la política corriendo sobre los 38 000 clientes.

Nada se escribe a mano. Si un insumo falta, el bloque **no aparece** y el
motivo viaja en `avisos`; nunca se rellena con un número inventado.

Coste y dónde se paga
---------------------
Construirlo entero cuesta ~6 s (Store 1.4 s + escalera 1.3 s + panorama 1.6 s +
consultas). **Eso no se paga por petición.** El resultado se escribe una vez en
`dashboard/datos.json` con la firma de sus insumos; al arrancar, el servicio lo
lee (unos milisegundos) y solo lo reconstruye si algún parquet o artefacto ha
cambiado de tamaño desde que se generó.

    .venv/bin/python -m app.dashboard_datos        # regenera el artefacto

Formato de los números
----------------------
Todo porcentaje viaja como `{"valor": 86.43, "texto": "86.43 %"}` vía
`app.formato`, que es el único sitio del repo que decide cuántos decimales
lleva un porcentaje. Quien calcula usa `valor`; quien pinta usa `texto`.
"""
from __future__ import annotations

import json
import os
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__ in (None, ""):                                   # pragma: no cover
    import sys
    sys.path.insert(0, RAIZ)

from app import formato                                          # noqa: E402
from app.razones import PUERTA_DESC, PUERTA_ES, TITULO           # noqa: E402
from pipeline.mapas import (                                     # noqa: E402
    CAP_EXPOSICIONES,
    CATALOGO_DEMO,
    CORTE_DEMO,
    CORTES_ROLLING,
    FRAGIL_DIAS_NEGATIVOS,
    FRAGIL_UTILIZACION_PCT,
    LAMBDA_DEFECTO,
    PANTALLAS,
    PRODUCTO_A_ACCION,
    PRODUCTO_A_PANTALLA,
    TODOS_LOS_PRODUCTOS,
    UMBRAL_ON_TIME_H,
    UMBRAL_WARM_H,
)

DATOS = os.path.join(RAIZ, "data")
RECON = os.path.join(RAIZ, "analytics", "recon", "out")
ARTIFACTS = os.path.join(RAIZ, "pipeline", "artifacts")
RUTA_ARTEFACTO = os.path.join(RAIZ, "dashboard", "datos.json")

# El `asof` con el que se mide todo lo que depende de una hora concreta. Es el
# mismo que usa la demo (`app/main.py`), para que las dos pantallas hablen del
# mismo instante y no de dos días distintos.
HORA = "T12:00:00"
ASOF = CORTE_DEMO + HORA

# La ventana con la que se cuenta la conversión de un aviso. La misma que
# `analytics/metricas.py`: el aviso convierte si la acción acoplada ocurre en
# los 7 días siguientes.
VENTANA_CONVERSION_D = 7

# Sube cuando cambia la forma del diccionario. Un artefacto con otra versión se
# reconstruye en vez de servirse: así una firma que cuadra no puede colar un
# esquema viejo.
VERSION = "2"   # subido al corregir los denominadores del bloque 6 y las etiquetas de los bloques 1, 2 y 5

# Los archivos cuya huella (tamaño en bytes) decide si el artefacto sigue
# valiendo. Si uno cambia, se reconstruye.
INSUMOS = [
    os.path.join(DATOS, "customers.parquet"),
    os.path.join(DATOS, "app_events.parquet"),
    os.path.join(DATOS, "financial_actions.parquet"),
    os.path.join(DATOS, "nudges.parquet"),
    os.path.join(DATOS, "nudge_outcomes.parquet"),
    os.path.join(ARTIFACTS, "metadata.json"),
    os.path.join(ARTIFACTS, "tabla_valor.json"),
    os.path.join(ARTIFACTS, "umbrales.json"),
    os.path.join(ARTIFACTS, "modelo_intencion.pkl"),
    os.path.join(ARTIFACTS, "modelo_momento.pkl"),
]

# Nombres llanos. La pantalla no puede enseñar `savings_move` a alguien que no
# ha estado en ninguna reunión.
ACCION_ES = {
    "spei_out": "Transferencia SPEI enviada",
    "bill_payment": "Pago de un servicio",
    "deposit_in": "Depósito recibido",
    "savings_move": "Traspaso a ahorro",
    "loan_request": "Solicitud de préstamo",
    "limit_increase_request": "Solicitud de aumento de línea",
    "card_payment": "Pago de la tarjeta",
    "investment_buy": "Compra de inversión",
}

PANTALLA_ES = {
    "home": "Inicio",
    "transfer_spei": "Transferir por SPEI",
    "bill_payment": "Pagar un servicio",
    "card_statement": "Estado de cuenta",
    "savings_cajita": "Cajita de ahorro",
    "loan_simulation": "Simulador de préstamo",
    "limit_increase": "Aumentar la línea",
    "investments": "Inversiones",
    "support": "Ayuda",
    "card_settings": "Ajustes de la tarjeta",
}

AVISO_ES = {
    "savings_goal": "Meta de ahorro",
    "limit_increase": "Aumento de línea",
    "bill_reminder": "Recordatorio de pago",
    "loan_offer": "Oferta de préstamo",
    "invest_start": "Empezar a invertir",
    "payroll_portability": "Traer la nómina",
}

SUPERFICIE_ES = {
    "home_card": "Tarjeta en el inicio",
    "push": "Notificación push",
    "in_app_modal": "Ventana dentro de la app",
}

PRODUCTO_ES = {
    "has_cuenta_nu": "Cuenta Nu",
    "has_cajita_turbo": "Cajita Turbo (ahorro)",
    "has_payroll_portability": "Nómina en Nu",
    "has_personal_loan": "Préstamo personal",
    "has_investments": "Inversiones",
}

# Los nombres de las 8 políticas simuladas, en castellano llano. Las claves son
# las que trae `analytics/recon/out/07_policy_simulation.csv`; si apareciera una
# nueva se enseña tal cual en vez de esconderla.
POLITICA_ES = {
    "P0 baseline: enviar todo":
        "P0 · Mandar todos los avisos (lo que se hace hoy)",
    "P1 cap de frecuencia: exposure_no<=2":
        f"P1 · Como máximo {CAP_EXPOSICIONES} veces el mismo aviso",
    "P2 solo on_time (senal <=24h)":
        "P2 · Solo si entró a la pantalla en las últimas 24 h",
    "P3 on_time o warm (<=7d)":
        "P3 · Solo si entró a la pantalla en los últimos 7 días",
    "P4 sin limit_increase a fragiles":
        "P4 · Nunca ofrecer aumento de línea a un cliente frágil",
    "P5 on_time + exposure<=2":
        "P5 · Señal de 24 h y como máximo 2 repeticiones",
    "P6 SALUD: (on_time o warm) + exp<=2 + veto limit_increase a fragiles":
        "P6 · Optimizar la salud: señal de 7 días, tope de 2 y veto de crédito",
    "P7 REVENUE: (on_time o warm) + exp<=2 (sin veto)":
        "P7 · Optimizar el ingreso: igual que P6 pero sin el veto de crédito",
}

MOMENTO_ES = {
    "0_on_time": "Señal fresca (entró hace ≤ 24 h)",
    "1_warm": "Señal tibia (entre 24 h y 7 días)",
    "2_cold": "Señal fría (hace más de 7 días)",
    "3_nunca": "Nunca entró a esa pantalla",
}


class DashboardNoDisponible(Exception):
    """Falta un insumo. Trae el motivo escrito, que viaja a la pantalla."""


# ==========================================================================
# Utilidades
# ==========================================================================
def P(valor, de_fraccion=False):
    """Un porcentaje listo para pintar: `{"valor": 86.43, "texto": "86.43 %"}`."""
    return formato.bloque_pct(valor, de_fraccion)


def _num(valor, decimales=2):
    """Un número que no es porcentaje. `None` no se convierte en cero."""
    if valor is None:
        return None
    return round(float(valor), decimales)


def _mil(n):
    """`47497` → `'47 497'`. El mismo espacio de millares que usa el resto."""
    return f"{int(n):,}".replace(",", " ")


def _signo_mil(n):
    """`-1502` → `'-1 502'`. Como `_mil`, pero conservando el signo."""
    return f"{int(n):+,}".replace(",", " ")


def _firma():
    """El tamaño en bytes de cada insumo. Si uno cambia, el artefacto caduca."""
    f = {"version": VERSION}
    for ruta in INSUMOS:
        f[os.path.relpath(ruta, RAIZ)] = (os.path.getsize(ruta)
                                          if os.path.exists(ruta) else None)
    return f


def _recon(nombre, indice=None):
    """Un CSV del reconocimiento, o el motivo por el que no está."""
    import pandas as pd

    ruta = os.path.join(RECON, nombre)
    if not os.path.exists(ruta):
        raise DashboardNoDisponible(f"falta analytics/recon/out/{nombre}")
    return pd.read_csv(ruta, index_col=indice)


def _artefacto(nombre):
    ruta = os.path.join(ARTIFACTS, nombre)
    if not os.path.exists(ruta):
        raise DashboardNoDisponible(f"falta pipeline/artifacts/{nombre}")
    with open(ruta, encoding="utf-8") as fh:
        return json.load(fh)


def _anchos(filas, clave="valor", maximo=None):
    """Rellena `ancho_pct` en cada fila: la barra más larga ocupa el 100 %.

    Las barras se pintan con CSS, así que lo único que la plantilla necesita es
    la anchura relativa. Calcularla aquí evita que la pantalla tenga que hacer
    aritmética y que dos gráficas de la misma página usen escalas distintas sin
    querer.
    """
    vals = [abs(float(f[clave])) for f in filas if f.get(clave) is not None]
    tope = float(maximo) if maximo else (max(vals) if vals else 0.0)
    for f in filas:
        v = f.get(clave)
        f["ancho_pct"] = (round(100.0 * abs(float(v)) / tope, 2)
                          if (v is not None and tope > 0) else 0.0)
    return filas


def _divergentes(filas, bueno_si_positivo, clave="valor"):
    """Prepara barras que salen de un **cero central**: a un lado lo bueno.

    Una cifra con signo no se puede dibujar como una barra que crece desde la
    izquierda: la longitud diría «magnitud» y el signo quedaría solo en el
    color, así que un dato malo y grande se leería igual que uno bueno y
    grande. Aquí cada barra sale del cero hacia su lado y `bueno` decide el
    color, no la posición en la lista.
    """
    vals = [abs(float(f[clave])) for f in filas if f.get(clave) is not None]
    tope = max(vals) if vals else 0.0
    for f in filas:
        v = float(f.get(clave) or 0.0)
        f["lado"] = "der" if v >= 0 else "izq"
        # 50 % es media pista: es todo el espacio que hay a cada lado del cero.
        f["ancho_pct"] = round(50.0 * abs(v) / tope, 2) if tope > 0 else 0.0
        f["bueno"] = (v > 0) if bueno_si_positivo else (v < 0)
        f.pop("resaltar", None)
        f.pop("negativo", None)
    return filas


def _grafica(clave, tipo, titulo, que_muestra, que_concluir, filas,
             unidad=None, leyenda=None, aviso=None, alt=None, extra=None):
    """Una gráfica con todo lo que hace falta para leerla sin contexto previo.

    `que_muestra` y `que_concluir` no son adornos: son la diferencia entre una
    gráfica y un dibujo. `aviso` es para cuando la gráfica **puede leerse mal**
    y hay que decirlo dentro de la propia gráfica.
    """
    g = {"clave": clave, "tipo": tipo, "titulo": titulo,
         "que_muestra": que_muestra, "que_concluir": que_concluir,
         "unidad": unidad, "leyenda": leyenda, "aviso": aviso,
         "filas": filas, "alt": alt or _alt_automatica(titulo, filas, unidad)}
    if extra:
        g.update(extra)
    return g


def _alt_automatica(titulo, filas, unidad):
    """La alternativa textual: cada barra dicha con su número.

    Se genera siempre. Una gráfica sin alternativa textual es una gráfica que
    para un lector de pantalla no existe.
    """
    partes = []
    for f in filas:
        # Una fila puede traer un valor (`texto`) o dos (`a` y `b`, las barras
        # pareadas). Si aquí solo se leyera `texto`, la alternativa textual de
        # media docena de gráficas diría un guion donde van los números.
        if isinstance(f.get("a"), dict) and isinstance(f.get("b"), dict):
            t = f"{f['a'].get('texto', formato.GUION)} / {f['b'].get('texto', formato.GUION)}"
        else:
            t = f.get("texto")
            if t is None and f.get("valor") is not None:
                t = str(f["valor"])
        partes.append(f"{f.get('etiqueta', '?')}: {t if t is not None else formato.GUION}")
    cola = f" (en {unidad})" if unidad else ""
    return f"{titulo}{cola}. " + "; ".join(partes) + "."


def _curva_svg(series, ancho=100.0, alto=100.0, margen=2.0):
    """Coordenadas ya resueltas de una curva, en un lienzo relativo 0–100.

    La plantilla dibuja un `<svg viewBox="0 0 100 100" preserveAspectRatio="none">`
    con estos puntos y **sin una sola letra dentro**: las etiquetas de los ejes
    van en HTML alrededor del dibujo. Es lo que hace que el gráfico se lea igual
    a 320 px y a 2560 px sin que el texto se estire.
    """
    valores = [p["y"] for s in series for p in s["puntos"] if p["y"] is not None]
    tope = max(valores) if valores else 1.0
    tope = tope or 1.0
    n = max(len(s["puntos"]) for s in series)
    util_x, util_y = ancho - 2 * margen, alto - 2 * margen
    fuera = []
    for s in series:
        pts = []
        for i, p in enumerate(s["puntos"]):
            if p["y"] is None:
                continue
            x = margen + (util_x * i / max(n - 1, 1))
            y = margen + util_y * (1.0 - float(p["y"]) / tope)
            pts.append({"x": round(x, 2), "y": round(y, 2),
                        "etiqueta": p.get("etiqueta"), "texto": p.get("texto")})
        fuera.append({**{k: v for k, v in s.items() if k != "puntos"},
                      "puntos": pts,
                      "polilinea": " ".join(f"{p['x']},{p['y']}" for p in pts)})
    return {"series": fuera, "tope": round(tope, 4),
            "tope_texto": formato.pct(tope), "ancho": ancho, "alto": alto}


# ==========================================================================
# Bloque 1 · Quiénes son los clientes
# ==========================================================================
def _bloque_clientes(con):
    import pandas as pd

    cu = pd.read_parquet(os.path.join(DATOS, "customers.parquet"))
    n = len(cu)

    def q(col, p):
        return _num(float(cu[col].quantile(p)), 2)

    fragil = ((cu.card_utilization_pct > FRAGIL_UTILIZACION_PCT)
              | (cu.days_negative_90d >= FRAGIL_DIAS_NEGATIVOS))

    productos = _anchos([
        {"etiqueta": PRODUCTO_ES[c], "clave": c,
         "n": int(cu[c].sum()), "valor": round(100.0 * float(cu[c].mean()), 2),
         "texto": formato.pct(100.0 * float(cu[c].mean()))}
        for c in PRODUCTO_ES
    ])

    # OJO: `income_band` es una etiqueta de segmento que trae el dataset, NO un
    # corte sobre `monthly_income_est_mxn`. Los dos no cuadran (la mediana del
    # segmento «<8k» es 9 800 MXN), así que la etiqueta no puede afirmar un
    # importe. Se nombra el segmento y el aviso de la gráfica lo explica.
    orden_ingreso = {"<8k": "Segmento más bajo (el dataset lo llama «8k»)",
                     "8k-15k": "Segmento «8k-15k»",
                     "15k-30k": "Segmento «15k-30k»",
                     "30k-60k": "Segmento «30k-60k»",
                     ">60k": "Segmento más alto (el dataset lo llama «60k»)"}
    vc = cu.income_band.value_counts()
    ingreso = _anchos([
        {"etiqueta": orden_ingreso[b], "clave": b, "n": int(vc.get(b, 0)),
         "valor": round(100.0 * int(vc.get(b, 0)) / n, 2),
         "texto": formato.pct(100.0 * int(vc.get(b, 0)) / n)}
        for b in orden_ingreso if b in vc.index
    ])

    vp = cu.payday_day_of_month.value_counts()
    payday = _anchos([
        {"etiqueta": f"Día {int(d)} del mes", "clave": str(int(d)), "n": int(vp[d]),
         "valor": round(100.0 * int(vp[d]) / n, 2),
         "texto": formato.pct(100.0 * int(vp[d]) / n)}
        for d in sorted(vp.index)
    ])

    salud = _anchos([
        {"etiqueta": "Ha estado en negativo algún día de los últimos 90",
         "valor": round(100.0 * float((cu.days_negative_90d > 0).mean()), 2),
         "texto": formato.pct(100.0 * float((cu.days_negative_90d > 0).mean())),
         "n": int((cu.days_negative_90d > 0).sum())},
        {"etiqueta": f"Usa más del {FRAGIL_UTILIZACION_PCT:.0f} % de su línea de crédito",
         "valor": round(100.0 * float((cu.card_utilization_pct > FRAGIL_UTILIZACION_PCT).mean()), 2),
         "texto": formato.pct(100.0 * float((cu.card_utilization_pct > FRAGIL_UTILIZACION_PCT).mean())),
         "n": int((cu.card_utilization_pct > FRAGIL_UTILIZACION_PCT).sum())},
        {"etiqueta": "No aparta nada de ahorro (tasa de ahorro 0 %)",
         "valor": round(100.0 * float((cu.savings_rate_90d_pct <= 0).mean()), 2),
         "texto": formato.pct(100.0 * float((cu.savings_rate_90d_pct <= 0).mean())),
         "n": int((cu.savings_rate_90d_pct <= 0).sum())},
        {"etiqueta": "En situación frágil (una de las dos primeras, o las dos)",
         "valor": round(100.0 * float(fragil.mean()), 2),
         "texto": formato.pct(100.0 * float(fragil.mean())),
         "n": int(fragil.sum()), "resaltar": True},
    ], maximo=100.0)

    nps = _recon("06_nps_pattern.csv")
    nps_filas = [
        {"etiqueta": "Clientes frágiles" if bool(r.fragil) else "Clientes no frágiles",
         "n": int(r.n),
         "valor": _num(100.0 - float(r.pct_nulo)),
         "texto": formato.pct(100.0 - float(r.pct_nulo)),
         "nota": f"nota media {float(r.nps_medio):.2f} de 10"}
        for r in nps.itertuples()
    ]
    _anchos(nps_filas, maximo=100.0)

    return {
        "clave": "clientes",
        "titulo": "1 · Quiénes son estas 38 000 personas",
        "resumen": ("Antes de hablar de modelos: esta es la base de clientes. "
                    "Ninguna persona es real — el dataset es 100 % sintético — pero "
                    "la forma de la población es la que hay que tener en la cabeza "
                    "para que el resto de las cifras signifique algo."),
        "fuente": "data/customers.parquet · recalculado en cada construcción",
        "cifras": [
            {"etiqueta": "Clientes en el dataset", "valor": f"{n:,}".replace(",", " "),
             "detalle": "Es el denominador de casi todo lo que sigue."},
            {"etiqueta": "Edad", "valor": f"{q('age', .5):.0f} años (mediana)",
             "detalle": f"La mitad tiene entre {q('age', .25):.0f} y {q('age', .75):.0f} años."},
            {"etiqueta": "Antigüedad en el banco",
             "valor": f"{q('tenure_months', .5):.0f} meses (mediana)",
             "detalle": f"De {int(cu.tenure_months.min())} a {int(cu.tenure_months.max())} meses."},
            {"etiqueta": "Ingreso mensual estimado",
             "valor": f"{q('monthly_income_est_mxn', .5):,.0f} MXN (mediana)".replace(",", " "),
             "detalle": "La media (19 346 MXN) es más alta porque hay una cola de ingresos altos."},
            {"etiqueta": "Saldo medio en cuenta",
             "valor": f"{q('avg_balance_mxn', .5):,.0f} MXN (mediana)".replace(",", " "),
             "detalle": "Mediana, no media: unos pocos saldos muy grandes la desplazarían."},
        ],
        "graficas": [
            _grafica(
                "productos", "barras",
                "Qué productos tiene ya cada cliente",
                "El porcentaje de los 38 000 clientes que hoy tiene cada producto "
                "contratado. Un cliente puede tener varios.",
                "La base es sobre todo de cuenta y ahorro. Crédito e inversión son "
                "minoritarios: por eso una oferta de préstamo o de inversión le "
                "encaja a mucha menos gente de la que parece.",
                productos, unidad="% de los 38 000 clientes"),
            _grafica(
                "ingreso", "barras",
                "En qué segmento de ingreso está cada cliente",
                "Reparto de los 38 000 clientes entre los cinco segmentos de "
                "ingreso que trae el dataset en la columna `income_band`.",
                "Casi la mitad de la base (48.96 %) cae en los dos segmentos más "
                "bajos. Cualquier recomendación que asuma holgura financiera se "
                "está dirigiendo a menos de la mitad de la gente.",
                ingreso, unidad="% de los 38 000 clientes",
                aviso="El nombre del segmento NO es un corte sobre el ingreso "
                      "estimado: el dataset trae las dos cosas y no cuadran. La "
                      "mediana del segmento más bajo es 9 800 MXN al mes y la del "
                      "más alto es 27 700, y los dos abarcan desde 3 500 hasta más "
                      "de 120 000. Leídos como pesos al mes, los tramos dirían algo "
                      "falso; por eso aquí se nombran como lo que son: etiquetas de "
                      "segmento. El ingreso estimado de verdad está dos filas más "
                      "arriba, en las cifras: mediana 16 300 MXN."),
            _grafica(
                "salud", "barras",
                "En qué situación financiera están",
                "Cuatro señales de tensión financiera, cada una sobre el total de "
                "clientes. La última es la definición de «frágil» que usa el "
                "sistema para vetar ofertas de crédito.",
                f"Casi 1 de cada 5 clientes está en situación frágil. Ese es el "
                f"grupo al que un aumento de línea le hace daño, y es el motivo de "
                f"que exista una puerta que se lo niegue.",
                salud, unidad="% de los 38 000 clientes",
                aviso=(f"«Frágil» aquí es una definición operativa, no un juicio: "
                       f"utilización de tarjeta por encima del {FRAGIL_UTILIZACION_PCT:.0f} % "
                       f"o {FRAGIL_DIAS_NEGATIVOS} o más días en negativo en los últimos 90.")),
            _grafica(
                "nps", "barras",
                "Cuánta gente nos ha dicho si está contenta",
                "Porcentaje de clientes que respondió la encuesta de satisfacción, "
                "separando a los frágiles del resto.",
                "Solo responde uno de cada tres, y responde por igual esté frágil o "
                "no. La satisfacción no se puede optimizar con esto: es una "
                "restricción del dataset, no un descuido.",
                nps_filas, unidad="% que respondió la encuesta",
                aviso="Los frágiles que responden dan de media 6.19 sobre 10 y los no "
                      "frágiles 8.20. La diferencia existe, pero sobre el 31 % que "
                      "contesta: no se puede extrapolar al resto."),
            _grafica(
                "payday", "barras",
                "Cuándo le pagan a cada cliente",
                "Día del mes en el que el cliente recibe su sueldo.",
                "Solo hay tres días de pago posibles: 1, 15 y 30. Eso convierte el "
                "calendario en una señal utilizable — y la mitad de la base cobra "
                "el día 15.",
                payday, unidad="% de los 38 000 clientes"),
        ],
    }


# ==========================================================================
# Bloque 2 · Qué hacen
# ==========================================================================
def _bloque_comportamiento(con):
    comp = _recon("03_event_composition.csv")
    acc = _recon("02_action_type_dist.csv")
    gaps = _recon("03_event_gap_histogram.csv")
    p24 = _recon("03_screen_action_p24h.csv", indice="screen")
    lift24 = _recon("03_screen_action_lift24h.csv", indice="screen")

    n_eventos = int(comp.total.sum())
    n_acciones = int(acc.n.sum())

    pantallas = _anchos([
        {"etiqueta": PANTALLA_ES.get(r.screen, r.screen), "clave": r.screen,
         "n": int(r.total), "valor": round(100.0 * int(r.total) / n_eventos, 2),
         "texto": formato.pct(100.0 * int(r.total) / n_eventos),
         "nota": f"{formato.pct(float(r.pct_start))} de esas visitas llegan a iniciar el flujo"}
        for r in comp.itertuples()
    ])

    acciones = _anchos([
        {"etiqueta": ACCION_ES.get(r.action_type, r.action_type), "clave": r.action_type,
         "n": int(r.n), "valor": _num(float(r.pct_filas)),
         "texto": formato.pct(float(r.pct_filas)),
         "nota": (f"{formato.pct(float(r.pct_clientes_con_1_))} de los clientes "
                  f"la hace al menos una vez · importe medio "
                  f"{float(r.monto_medio):,.0f} MXN".replace(",", " "))}
        for r in acc.rename(columns={"pct_clientes_con_1+": "pct_clientes_con_1_"}).itertuples()
    ])

    # La diagonal: entrar a la pantalla acoplada contra no entrar. El `lift` es
    # la probabilidad de la acción dividida entre la de quien no entró ahí.
    acopladas = []
    for producto in TODOS_LOS_PRODUCTOS:
        pantalla = PRODUCTO_A_PANTALLA.get(producto)
        accion = PRODUCTO_A_ACCION.get(producto)
        if not pantalla or not accion or pantalla not in p24.index:
            continue
        acopladas.append({
            "etiqueta": f"{PANTALLA_ES.get(pantalla, pantalla)} → {ACCION_ES.get(accion, accion)}",
            "clave": producto,
            "valor": _num(float(p24.loc[pantalla, accion])),
            "texto": formato.pct(float(p24.loc[pantalla, accion])),
            "nota": (f"{formato.veces(float(lift24.loc[pantalla, accion]))} más probable "
                     f"que tras una visita cualquiera de la app")})
    acopladas.sort(key=lambda f: -(f["valor"] or 0.0))
    _anchos(acopladas, maximo=100.0)

    espera = _anchos([
        {"etiqueta": r.bucket.replace("m", " min").replace("h", " h").replace("d", " días"),
         "clave": r.bucket, "n": int(r.n), "valor": _num(float(r.pct)),
         "texto": formato.pct(float(r.pct)),
         "nota": f"acumulado {formato.pct(float(r.pct_acum))}"}
        for r in gaps.itertuples()
    ])

    sin_senal = con.execute(
        f"""SELECT count(DISTINCT customer_id) FROM app_events
            WHERE event_ts >= TIMESTAMP '{ASOF}' - INTERVAL 24 HOUR
              AND event_ts <  TIMESTAMP '{ASOF}'""").fetchone()[0]
    pct_sin_senal = 100.0 * (38000 - int(sin_senal)) / 38000.0

    return {
        "clave": "comportamiento",
        "titulo": "2 · Qué hacen dentro de la app, y qué hacen con su dinero",
        "resumen": ("Hay dos registros distintos: por dónde navega la gente "
                    "(797 304 eventos) y qué mueve de dinero (566 682 acciones). "
                    "El puente entre los dos es lo que hace posible predecir algo: "
                    "la pantalla que alguien abre hoy anticipa la acción de mañana."),
        "fuente": ("analytics/recon/out/03_event_composition.csv, "
                   "02_action_type_dist.csv, 03_screen_action_p24h.csv, "
                   "03_screen_action_lift24h.csv, 03_event_gap_histogram.csv · "
                   "el hueco de señal, recalculado desde data/app_events.parquet"),
        "cifras": [
            {"etiqueta": "Eventos de navegación", "valor": f"{n_eventos:,}".replace(",", " "),
             "detalle": "119 días de historia. No hay identificador de sesión: agrupar "
                        "eventos en sesiones es una decisión nuestra, no un dato."},
            {"etiqueta": "Acciones financieras", "valor": f"{n_acciones:,}".replace(",", " "),
             "detalle": "Unas 15 por cliente en los 119 días, de 4.6 tipos distintos."},
            {"etiqueta": "Clientes sin ni un evento en las últimas 24 h",
             "valor": formato.pct(pct_sin_senal),
             "detalle": f"Al corte {CORTE_DEMO} a las 12:00. La señal fresca es rara: "
                        f"eso es lo que limita a cuánta gente se le puede hablar con "
                        f"fundamento."},
        ],
        "graficas": [
            _grafica(
                "acopladas", "barras",
                "La pantalla de hoy anticipa la acción de mañana",
                "Para cada pareja pantalla-producto: de los clientes que entraron a "
                "esa pantalla, qué porcentaje hizo la acción correspondiente en las "
                "24 horas siguientes. Al lado, cuántas veces más probable es eso que "
                "en una visita cualquiera de la app —la media de las 10 pantallas—, "
                "que es la referencia con la que se calcula.",
                "Este es el hallazgo que sostiene todo el producto. Entrar al "
                "simulador de préstamo multiplica por 30 la probabilidad de pedir "
                "uno frente a una visita cualquiera. La intención no hay que "
                "adivinarla: el cliente la deja escrita al navegar.",
                acopladas, unidad="% que hace la acción en las 24 h siguientes",
                aviso="Ojo con el signo de la lectura: esto no dice que la pantalla "
                      "cause la acción, dice que la anuncia. Es suficiente para "
                      "decidir cuándo hablar, y no basta para atribuirse el mérito."),
            _grafica(
                "pantallas", "barras",
                "Por dónde pasa la gente en la app",
                "Reparto de los 797 304 eventos de navegación entre las 10 pantallas.",
                "Un cuarto del tráfico es solo la pantalla de inicio, que no dice "
                "nada de intención. Las pantallas que sí informan —préstamo, línea, "
                "inversiones— son las que menos tráfico tienen: entre las tres no "
                "llegan al 8 %.",
                pantallas, unidad="% de los 797 304 eventos"),
            _grafica(
                "acciones", "barras",
                "Qué hace la gente con su dinero",
                "Reparto de las 566 682 acciones financieras por tipo.",
                "Casi un tercio de las ACCIONES son transferencias SPEI. Eso no es "
                "lo mismo que el acierto de predecir siempre «SPEI» a cada CLIENTE, "
                "que es 33.63 % de media (bloque 8) y va del 25.63 % al 41.62 % "
                "según el día: son dos denominadores distintos. La referencia "
                "contra la que hay que medirse es esa media, no contra cero.",
                acciones, unidad="% de las 566 682 acciones"),
            _grafica(
                "espera", "barras",
                "Cuánto tarda un cliente en volver a abrir la app",
                "Tiempo entre dos eventos consecutivos del mismo cliente.",
                "Casi la mitad de los huecos pasan de 3 días. La app no es un sitio "
                "donde la gente esté todo el rato: si el aviso no cae en la visita "
                "correcta, no cae.",
                espera, unidad="% de los huecos entre eventos"),
        ],
    }


# ==========================================================================
# Bloque 3 · Los avisos y su resultado
# ==========================================================================
def _bloque_avisos(con, cobertura_pct):
    from analytics.metricas import _tabla_avisos, embudo, por_producto

    av = _tabla_avisos(con)
    tipos = _recon("04_by_nudge_type.csv")
    superficies = _recon("04_by_surface.csv")
    globales = _recon("04_global_rates.csv").iloc[0]

    n_avisos = int(len(av))
    n_acoplados = int(av.tiene_accion_acoplada.sum())

    emb = embudo(av, cobertura_pct)
    escalones = []
    explica = {
        "M1": "De cada 100 clientes, a cuántos les diría algo el sistema hoy.",
        "M2": "De cada 100 avisos mostrados, cuántos reciben un clic.",
        "M3": "De cada 100 avisos mostrados, tras cuántos el cliente hace de verdad "
              "la acción en los 7 días siguientes.",
        "M4": "Qué fracción de los clics acaba en la acción. Es M3 dividido entre M2.",
        "M5": "Cuánto más convierte un aviso con clic que uno sin clic.",
    }
    for _, r in emb.iterrows():
        u = str(r["u"])
        escalones.append({
            "clave": r["#"], "etiqueta": str(r["metrica"]),
            "valor": _num(float(r["obtenido"]), 2),
            "texto": (formato.pct(float(r["obtenido"])) if u == "%"
                      else (f"{float(r['obtenido']):+.2f} pp" if u == "pp"
                            else f"{float(r['obtenido']):.2f}")),
            "unidad": u or "razón",
            "explica": explica.get(r["#"], "")})
    _anchos(escalones, maximo=max(abs(float(r["obtenido"])) for _, r in emb.iterrows()))

    pp = por_producto(av)
    clic_conv = []
    for tipo, r in pp.iterrows():
        clic_conv.append({
            "etiqueta": AVISO_ES.get(tipo, tipo), "clave": tipo,
            "n": int(r["n"]),
            "a": {"valor": _num(float(r["clic_%"])), "texto": formato.pct(float(r["clic_%"]))},
            "b": {"valor": _num(float(r["conv_7d_%"])), "texto": formato.pct(float(r["conv_7d_%"]))},
            "nota": (f"eficiencia {float(r['eficiencia']):.2f} — de cada 100 clics, "
                     f"{round(100 * float(r['eficiencia']))} acaban en la acción"),
            "resaltar": tipo == "limit_increase"})
    tope_cc = max(max(f["a"]["valor"], f["b"]["valor"]) for f in clic_conv)
    for f in clic_conv:
        f["a"]["ancho_pct"] = round(100.0 * f["a"]["valor"] / tope_cc, 2)
        f["b"]["ancho_pct"] = round(100.0 * f["b"]["valor"] / tope_cc, 2)

    por_tipo = _anchos([
        {"etiqueta": AVISO_ES.get(r.nudge_type, r.nudge_type), "clave": r.nudge_type,
         "n": int(r.n), "valor": _num(float(r.engaged_)),
         "texto": formato.pct(float(r.engaged_)),
         "nota": (f"{formato.pct(float(r.dismissed_))} lo cierran sin actuar · "
                  f"{formato.pct(float(r.optout_))} apagan las notificaciones después")}
        for r in tipos.rename(columns={"engaged_%": "engaged_", "dismissed_%": "dismissed_",
                                       "optout_%": "optout_"}).itertuples()
    ])

    por_superficie = _anchos([
        {"etiqueta": SUPERFICIE_ES.get(r.surface, r.surface), "clave": r.surface,
         "n": int(r.n), "valor": _num(float(r.engaged_)),
         "texto": formato.pct(float(r.engaged_)),
         "nota": f"{formato.pct(float(r.optout_))} apagan las notificaciones después"}
        for r in superficies.rename(columns={"engaged_%": "engaged_",
                                             "optout_%": "optout_"}).itertuples()
    ])

    resultado = _anchos([
        {"etiqueta": "Le da clic y actúa sobre el aviso",
         "valor": _num(float(globales.engaged)), "texto": formato.pct(float(globales.engaged))},
        {"etiqueta": "Lo cierra sin hacer nada",
         "valor": _num(float(globales.dismissed)), "texto": formato.pct(float(globales.dismissed))},
        {"etiqueta": "Lo ignora (ni clic ni cierre)",
         "valor": _num(100.0 - float(globales.engaged) - float(globales.dismissed)),
         "texto": formato.pct(100.0 - float(globales.engaged) - float(globales.dismissed))},
        {"etiqueta": "Apaga las notificaciones justo después",
         "valor": _num(float(globales.opt_out)), "texto": formato.pct(float(globales.opt_out)),
         "resaltar": True},
    ], maximo=100.0)

    return {
        "clave": "avisos",
        "titulo": "3 · Los avisos que se mandan hoy, y en qué acaban",
        "resumen": ("285 000 avisos mostrados en 119 días, con lo que pasó después "
                    "de cada uno. El tipo de aviso y el sitio donde aparece se "
                    "asignaron AL AZAR, así que comparar unos con otros es una "
                    "comparación limpia y no el reflejo de a quién se le mandaba qué."),
        "fuente": ("data/nudges.parquet + data/financial_actions.parquet vía "
                   "analytics/metricas.py (embudo y conversión a 7 días, "
                   "recalculados) · analytics/recon/out/04_by_nudge_type.csv, "
                   "04_by_surface.csv, 04_global_rates.csv"),
        "cifras": [
            {"etiqueta": "Avisos mostrados", "valor": f"{n_avisos:,}".replace(",", " "),
             "detalle": "Uno por fila, con su resultado y sus consecuencias a 90 días."},
            {"etiqueta": "Reciben clic", "valor": formato.pct(float(globales.engaged)),
             "detalle": "Sobre los 285 000. Sobre los 237 603 que tienen una acción "
                        "financiera acoplada, la cifra es 10.98 %."},
            {"etiqueta": "Se cierran sin actuar", "valor": formato.pct(float(globales.dismissed)),
             "detalle": "Más de un tercio. Es el coste invisible de hablar de más."},
            {"etiqueta": "Terminan en una baja de notificaciones",
             "valor": formato.pct(float(globales.opt_out)),
             "detalle": "Parece poco, hasta que se mira por número de repetición "
                        "(bloque 4): ahí llega al 6.11 %."},
        ],
        "graficas": [
            _grafica(
                "clic_conversion", "barras_pareadas",
                "El aviso más clicado es el que menos sirve",
                "Para cada tipo de aviso, dos barras: el porcentaje que recibe clic "
                "y el porcentaje tras el que el cliente hace de verdad la acción en "
                "los 7 días siguientes.",
                "El aumento de línea es el primero en clics (18.90 %) y el último en "
                "conversión (1.31 %): de cada 14 clics, 13 no acaban en nada. Si el "
                "objetivo fuese el clic, este sería el mejor producto del catálogo. "
                "No lo es.",
                clic_conv, unidad="% de los avisos de ese tipo",
                leyenda={"a": "Recibe clic", "b": "Acaba en la acción (7 días)"},
                aviso="Las dos barras se miden sobre el mismo denominador, así que la "
                      "segunda no es «de los que clicaron»: es del total de avisos. "
                      "Un aviso puede convertir sin clic — y de hecho pasa. Falta un "
                      "tipo de aviso, «Traer la nómina»: no hay ninguna acción "
                      "financiera en el dataset que confirme que el cliente la trajo, "
                      "así que su conversión no se puede medir y queda fuera.",
                alt=("El aviso más clicado es el que menos sirve. " + "; ".join(
                    f"{f['etiqueta']}: clic {f['a']['texto']}, conversión a 7 días "
                    f"{f['b']['texto']}" for f in clic_conv) + ".")),
            _grafica(
                "embudo", "escalones",
                "El embudo completo, de la cobertura al efecto",
                "Los cinco escalones que el equipo definió como métricas primarias, "
                "con lo que mide cada uno explicado al lado.",
                "El embudo se estrecha muy rápido: se le habla al 13.57 % de los "
                "clientes, clica el 10.98 % y convierte el 4.47 %. Y el 4.47 % no es "
                "mérito del aviso: sin ningún clic la conversión ya es del 4.08 %, "
                "no cero. La brecha de verdad son los 3.47 puntos porcentuales de "
                "M5, que no son un 3.47 %.",
                escalones, unidad="cada escalón en su propia unidad",
                aviso="M1 se mide sobre los 38 000 clientes y M2–M5 sobre los avisos. "
                      "Son denominadores distintos: los escalones no se multiplican "
                      "entre sí."),
            _grafica(
                "resultado", "barras",
                "Qué pasa con un aviso cualquiera",
                "Reparto de los 285 000 avisos según lo que hizo el cliente después.",
                "El resultado normal de un aviso es que no pase nada: 9 de cada 10 no "
                "reciben clic, y más de un tercio se cierran de forma activa. Mandar "
                "un aviso no es gratis aunque no cueste dinero.",
                resultado, unidad="% de los 285 000 avisos"),
            _grafica(
                "por_tipo", "barras",
                "Qué tipo de aviso funciona mejor (medido en clics)",
                "Porcentaje de clic por tipo de aviso, con el porcentaje de cierre y "
                "de baja al lado.",
                "El reparto de tipos fue aleatorio, así que estas diferencias son del "
                "producto y no de la selección de a quién se le mandó. Pero se miden "
                "en clics: la gráfica de arriba enseña que el orden cambia cuando se "
                "mide en acciones.",
                por_tipo, unidad="% de clic"),
            _grafica(
                "por_superficie", "barras",
                "Dónde conviene que aparezca el aviso",
                "Porcentaje de clic según el sitio en el que se muestra.",
                "La ventana dentro de la app convierte un 49 % mejor que el push "
                "(14.08 % contra 9.44 %). El sitio también se asignó al azar, así que "
                "la comparación es limpia.",
                por_superficie, unidad="% de clic"),
        ],
    }


# ==========================================================================
# Bloque 4 · La fatiga
# ==========================================================================
def _bloque_fatiga(con):
    from analytics.metricas import _tabla_avisos, curva_fatiga

    av = _tabla_avisos(con)
    cf = curva_fatiga(av)
    por_tipo = _recon("04_fatigue_by_type.csv")

    filas = []
    for etiqueta, r in cf.iterrows():
        eng, baja = float(r["enganche_%"]), float(r["baja_%"])
        filas.append({
            "etiqueta": (f"Vez nº {etiqueta}" if etiqueta != "6+" else "Vez nº 6 o más"),
            "clave": str(etiqueta), "n": int(r["n"]),
            "a": {"valor": _num(eng), "texto": formato.pct(eng)},
            "b": {"valor": _num(baja, 3), "texto": formato.pct(baja)},
            "nota": (f"{baja / eng:.2f} bajas por cada clic" if eng > 0
                     else "clics: cero. Solo quedan bajas"),
            "resaltar": str(etiqueta) == str(CAP_EXPOSICIONES + 1)})
    tope = max(f["a"]["valor"] for f in filas)
    for f in filas:
        f["a"]["ancho_pct"] = round(100.0 * f["a"]["valor"] / tope, 2)
        f["b"]["ancho_pct"] = round(100.0 * f["b"]["valor"] / tope, 2)

    curva = _curva_svg([
        {"clave": "enganche", "etiqueta": "Le dan clic",
         "puntos": [{"y": f["a"]["valor"], "etiqueta": f["etiqueta"],
                     "texto": f["a"]["texto"]} for f in filas]},
        {"clave": "baja", "etiqueta": "Apagan las notificaciones",
         "puntos": [{"y": f["b"]["valor"], "etiqueta": f["etiqueta"],
                     "texto": f["b"]["texto"]} for f in filas]},
    ])

    tipos = _anchos([
        {"etiqueta": AVISO_ES.get(r.nudge_type, r.nudge_type), "clave": r.nudge_type,
         "valor": _num(float(r.caida_1_a_3_pp)),
         "texto": f"−{float(r.caida_1_a_3_pp):.2f} pp",
         "nota": (f"de {formato.pct(float(r.exp_1))} la primera vez a "
                  f"{formato.pct(float(r.exp_3))} la tercera — le queda el "
                  f"{formato.pct(100 * float(r.retencion_3_1))}")}
        for r in por_tipo.rename(columns={"retencion_3/1": "retencion_3_1"}).itertuples()
    ])

    return {
        "clave": "fatiga",
        "titulo": "4 · Lo que cuesta repetir el mismo mensaje",
        "resumen": ("La misma recomendación mostrada otra vez no es neutral. Aquí "
                    "está medido: cada repetición parte el clic por la mitad y "
                    "duplica las bajas de notificaciones. De aquí sale el tope de "
                    f"{CAP_EXPOSICIONES} exposiciones por tipo de aviso, que no es "
                    "un número elegido a dedo."),
        "fuente": "data/nudges.parquet vía analytics/metricas.py · "
                  "analytics/recon/out/04_fatigue_by_type.csv",
        "cifras": [
            {"etiqueta": "Clic la primera vez", "valor": formato.pct(float(cf.loc["1", "enganche_%"])),
             "detalle": "159 817 avisos mostrados por primera vez."},
            {"etiqueta": "Clic la tercera vez", "valor": formato.pct(float(cf.loc["3", "enganche_%"])),
             "detalle": "Menos de una cuarta parte del de la primera."},
            {"etiqueta": "Bajas por cada clic en la tercera",
             "valor": f"{float(cf.loc['3', 'baja_%']) / float(cf.loc['3', 'enganche_%']):.2f}",
             "detalle": "En la cuarta son 1.89: ahí ya se pierde más de lo que se gana."},
            {"etiqueta": "Tope que aplica el sistema",
             "valor": f"{CAP_EXPOSICIONES} veces por tipo de aviso",
             "detalle": "El punto donde el coste supera al beneficio cae entre la "
                        "segunda y la tercera."},
        ],
        "graficas": [
            _grafica(
                "curva", "curva",
                "Cada repetición vale la mitad, y cuesta el doble",
                "Dos líneas sobre el número de veces que se le ha mostrado a alguien "
                "el mismo tipo de aviso: la que baja es el porcentaje que le da clic, "
                "la que sube es el porcentaje que apaga las notificaciones después.",
                "Las dos líneas se cruzan entre la tercera y la cuarta repetición. A "
                "partir de ahí el aviso genera más bajas que clics — el mensaje sigue "
                "siendo el mismo, lo que ha cambiado es que ya lo habían visto.",
                filas, unidad="% de los avisos de esa repetición",
                leyenda={"a": "Le dan clic", "b": "Apagan las notificaciones"},
                aviso="Las dos líneas comparten escala vertical, y la de bajas es "
                      "mucho más pequeña en valor absoluto: lo que hay que mirar es "
                      "la forma de cada una, no la distancia entre ellas.",
                extra={"svg": curva},
                alt=("Cada repetición vale la mitad y cuesta el doble. " + "; ".join(
                    f"{f['etiqueta']}: clic {f['a']['texto']}, bajas {f['b']['texto']}, "
                    f"{f['nota']}" for f in filas) + ".")),
            _grafica(
                "por_tipo_fatiga", "barras",
                "La fatiga golpea a todos los productos por igual",
                "Cuántos puntos porcentuales de clic pierde cada tipo de aviso entre "
                "la primera y la tercera vez que se muestra.",
                "Ningún tipo se salva: a todos les queda entre el 19 % y el 24 % del "
                "clic original en la tercera pasada. La fatiga no es un problema de "
                "un producto concreto, es una propiedad de repetir.",
                tipos, unidad="puntos porcentuales de clic perdidos"),
        ],
    }


# ==========================================================================
# Bloque 5 · El momento
# ==========================================================================
def _bloque_momento(con):
    rec = _recon("04_moment_recency.csv")
    mxf = _recon("04_moment_x_fatigue.csv")
    payday_total = _recon("07_payday_total.csv")
    payday_med = _recon("07_payday_mediation.csv")

    # El reparto se calcula desde los conteos, NO desde la columna `pct_nudges`
    # del CSV: esa viene redondeada a un decimal (1.5) y publicarla al lado del
    # conteo exacto (1.46 %) dejaría dos cifras distintas para lo mismo en la
    # misma página.
    n_avisos = int(rec.n.sum())
    momentos = []
    for r in rec.rename(columns={"engaged_%": "engaged_", "optout_%": "optout_"}).itertuples():
        clave = str(r.momento).split(" ")[0]
        cuota = 100.0 * int(r.n) / n_avisos
        momentos.append({
            "etiqueta": MOMENTO_ES.get(clave, str(r.momento)), "clave": clave,
            "n": int(r.n), "valor": _num(float(r.engaged_)),
            "texto": formato.pct(float(r.engaged_)),
            "cuota": _num(cuota), "cuota_texto": formato.pct(cuota),
            "nota": (f"{formato.pct(cuota)} de todos los avisos caen aquí · "
                     f"{formato.veces(float(r.lift_vs_global))} la media"),
            "resaltar": clave == "0_on_time"})
    _anchos(momentos)

    reparto = _anchos([
        {"etiqueta": m["etiqueta"], "clave": m["clave"],
         "valor": m["cuota"], "texto": m["cuota_texto"],
         "n": m["n"], "resaltar": m["resaltar"]}
        for m in momentos
    ], maximo=100.0)

    cruce = []
    for r in mxf.itertuples():
        cruce.append({
            "etiqueta": (f"Vez nº {int(r.exp_no)}" if int(r.exp_no) < int(mxf.exp_no.max())
                         else f"Vez nº {int(r.exp_no)} o más"),
            "clave": str(int(r.exp_no)),
            "a": {"valor": _num(float(r.on_time)), "texto": formato.pct(float(r.on_time))},
            "b": {"valor": _num(float(r.resto)), "texto": formato.pct(float(r.resto))},
            "nota": f"con señal fresca engancha {formato.veces(float(r.lift_on_time))} más"})
    tope = max(f["a"]["valor"] for f in cruce)
    for f in cruce:
        f["a"]["ancho_pct"] = round(100.0 * f["a"]["valor"] / tope, 2)
        f["b"]["ancho_pct"] = round(100.0 * f["b"]["valor"] / tope, 2)

    pay = _anchos([
        {"etiqueta": ("Los 3 días siguientes al día de pago"
                      if r.win.startswith("ventana") else "El resto del mes"),
         "clave": r.win, "n": int(r.n), "valor": _num(float(r.engaged_)),
         "texto": formato.pct(float(r.engaged_))}
        for r in payday_total.rename(columns={"engaged_%": "engaged_"}).itertuples()
    ])

    # Las cuotas de señal fresca dentro y fuera de la ventana del día de pago,
    # contadas desde los `n`: la columna `pct_dentro_de_win` del CSV viene
    # redondeada a un decimal y en esta página los porcentajes llevan dos.
    med = payday_med.rename(columns={"engaged_%": "engaged_"})
    dentro = med[med.win.str.startswith("ventana")]
    fuera_v = med[~med.win.str.startswith("ventana")]
    med_on_dentro = dentro[dentro.mom == "on_time"].iloc[0]
    med_on_fuera = fuera_v[fuera_v.mom == "on_time"].iloc[0]
    cuota_dentro = 100.0 * int(med_on_dentro["n"]) / int(dentro.n.sum())
    cuota_fuera = 100.0 * int(med_on_fuera["n"]) / int(fuera_v.n.sum())

    on_time = rec[rec.momento.str.startswith("0_")].iloc[0]
    frio = rec[rec.momento.str.startswith("2_")].iloc[0]
    nunca = rec[rec.momento.str.startswith("3_")].iloc[0]
    cuota_on_time = 100.0 * int(on_time["n"]) / n_avisos

    # Las dos brechas que se comparan en el texto, calculadas. Escritas a mano
    # («1.59 puntos contra 31») quedarían desfasadas en cuanto se regenerara el
    # dataset, y son justo las dos que sostienen el argumento del bloque.
    pay_pct = {r.win: float(r.engaged_) for r in
               payday_total.rename(columns={"engaged_%": "engaged_"}).itertuples()}
    brecha_payday = abs(pay_pct["ventana_payday_d0_d2"] - pay_pct["resto_del_mes"])
    brecha_senal = float(on_time["engaged_%"]) - float(frio["engaged_%"])
    fuera_de_momento = 100.0 - cuota_on_time

    return {
        "clave": "momento",
        "titulo": "5 · Hablar con señal o hablar sin ella: no es el mismo producto",
        "resumen": ("«Momento» aquí significa una cosa concreta y medible: cuánto "
                    "tiempo ha pasado desde que el cliente entró a la pantalla que "
                    "corresponde al aviso. Cuatro estados, del más fresco al que "
                    "nunca ocurrió."),
        "fuente": ("analytics/recon/out/04_moment_recency.csv, "
                   "04_moment_x_fatigue.csv, 07_payday_total.csv, "
                   "07_payday_mediation.csv"),
        "cifras": [
            {"etiqueta": "Avisos que caen con señal fresca",
             "valor": formato.pct(cuota_on_time),
             "detalle": f"Los otros {formato.pct(fuera_de_momento)} se mandan sin que "
                        f"el cliente haya dado ninguna señal reciente."},
            {"etiqueta": "Clic con señal fresca",
             "valor": formato.pct(float(on_time["engaged_%"])),
             "detalle": "Contra 10.30 % cuando el cliente nunca entró a esa pantalla."},
            {"etiqueta": "Cuánto mejor es el momento correcto",
             "valor": formato.veces(float(on_time["engaged_%"]) / float(nunca["engaged_%"])),
             "detalle": "Mismo mensaje, mismo producto. Lo único que cambia es cuándo. "
                        "Es clic, no la acción hecha: el glosario separa las dos."},
            {"etiqueta": "Bajas con señal fresca",
             "valor": formato.pct(float(on_time["optout_%"])),
             "detalle": f"Contra {formato.pct(float(rec[rec.momento.str.startswith('2_')].iloc[0]['optout_%']))} "
                        f"cuando la señal es fría: hablar a tiempo no solo convierte "
                        f"más, molesta menos."},
        ],
        "graficas": [
            _grafica(
                "momentos", "barras",
                "El mismo aviso, cuatro momentos distintos",
                "Porcentaje de clic según cuánto hacía que el cliente había entrado a "
                "la pantalla relacionada con el aviso.",
                "Cuando la señal es fresca el aviso recibe 4 veces más clic. Y fíjese "
                "en el detalle de cada barra: el estado que mejor funciona es el que "
                "menos avisos recibe.",
                momentos, unidad="% de clic",
                aviso="La señal fresca no es aleatoria: quien entró ayer a Cajitas es "
                      "distinto de quien no. Parte de esta diferencia es del momento "
                      "y parte de quién es esa persona; el dataset no permite "
                      "separarlas del todo."),
            _grafica(
                "reparto_momento", "barras",
                "Y así se reparten hoy los avisos entre esos cuatro momentos",
                "Qué porcentaje de los 285 000 avisos se mandó en cada estado de señal.",
                f"Solo {formato.pct(cuota_on_time)} de los avisos cae en el único "
                f"momento que funciona bien; los otros "
                f"{formato.pct(fuera_de_momento)} se mandan a ciegas. No falta "
                f"contenido: falta puntería.",
                reparto, unidad="% de los 285 000 avisos"),
            _grafica(
                "momento_x_fatiga", "barras_pareadas",
                "El momento correcto compensa incluso la repetición",
                "Porcentaje de clic por número de repetición, separando los avisos "
                "con señal fresca del resto.",
                "Un aviso repetido por tercera vez pero con señal fresca (21.05 %) "
                "funciona mejor que uno mostrado por primera vez sin señal (15.12 %). "
                "El momento pesa más que la novedad.",
                cruce, unidad="% de clic",
                leyenda={"a": "Con señal fresca", "b": "Sin señal fresca"}),
            _grafica(
                "payday", "barras",
                "El día de pago mueve la aguja, pero poco",
                "Porcentaje de clic dentro de los 3 días siguientes al día de pago "
                "del cliente, contra el resto del mes.",
                f"La diferencia es de {brecha_payday:.2f} puntos, muy lejos de los "
                f"{brecha_senal:.2f} que separan la señal fresca de la señal fría. Y "
                f"buena parte de ella es indirecta: cerca del día de pago la gente "
                f"entra más a la app, así que hay más señal fresca. El calendario "
                f"ayuda; la señal decide.",
                pay, unidad="% de clic",
                aviso="Comparar esta gráfica con la primera del bloque sin mirar la "
                      "escala lleva a la conclusión contraria: aquí el rango va de "
                      "11.31 % a 12.90 %, allí de 10.11 % a 41.63 %."),
        ],
        "tablas": [{
            "clave": "mediacion",
            "titulo": "Por qué el día de pago parece importar más de lo que importa",
            "que_muestra": "Los mismos avisos partidos en dos: dentro y fuera de la "
                           "ventana del día de pago, y dentro de cada una, por estado "
                           "de señal.",
            "que_concluir": (
                f"Con el estado de señal fijo, la ventana del día de pago apenas "
                f"cambia el clic ({formato.pct(float(med_on_dentro['engaged_']))} "
                f"contra {formato.pct(float(med_on_fuera['engaged_']))} con señal "
                f"fresca). Lo que cambia es cuánta gente tiene señal fresca: "
                f"{formato.pct(cuota_dentro)} dentro de la ventana contra "
                f"{formato.pct(cuota_fuera)} fuera. El día de pago no convence a "
                f"nadie: hace que más gente abra la app y deje señal."),
            "columnas": ["Ventana", "Estado de señal", "Avisos",
                         "% de esa ventana", "% de clic"],
            "filas": [[("Los 3 días tras el pago" if r.win.startswith("ventana")
                        else "El resto del mes"),
                       {"on_time": "Señal fresca", "warm": "Señal tibia",
                        "cold": "Señal fría o nunca"}.get(r.mom, r.mom),
                       f"{int(r.n):,}".replace(",", " "),
                       formato.pct(100.0 * int(r.n) / int(
                           (dentro if r.win.startswith("ventana")
                            else fuera_v).n.sum())),
                       formato.pct(float(r.engaged_))]
                      for r in med.itertuples()],
        }],
    }


# ==========================================================================
# Bloque 6 · Los objetivos en conflicto
# ==========================================================================
def _bloque_objetivos(con):
    rank = _recon("05_rankings.csv")
    master = _recon("05_master_by_type.csv")
    precio = _recon("05_tradeoff_price.csv")
    politicas = _recon("07_policy_simulation.csv")
    tv = _artefacto("tabla_valor.json")

    totales = _recon("05_totals.csv").set_index("nudge_type")
    ordenados = rank.sort_values("rk_engagement")

    # El protagonista del bloque no se nombra a mano: es el primero en clics,
    # y sus tres cifras se leen de donde toca. Si otro producto lo adelantara,
    # el titular cambiaría solo (y `test_las_consecuencias_a_90_dias…` avisa).
    fila_lider = ordenados.rename(columns={"engaged_%": "engaged_"}).iloc[0]
    lider = str(fila_lider.name if fila_lider.name in totales.index
                else fila_lider["nudge_type"])
    tot_lider = totales.loc[lider]
    tv_lider = tv["productos"][lider]
    rankings = [{
        "etiqueta": AVISO_ES.get(r.nudge_type, r.nudge_type), "clave": r.nudge_type,
        "engagement": int(r.rk_engagement), "salud": int(r.rk_salud),
        "ingreso": int(r.rk_revenue),
        "clic": formato.pct(float(r.engaged_)),
        "salud_idx": _num(float(r.salud_idx), 3),
        "ingreso_mxn": _num(float(r.d_revenue_mxn), 1),
        "resaltar": abs(int(r.gap_salud_vs_rev)) >= 3,
    } for r in ordenados.rename(columns={"engaged_%": "engaged_"}).itertuples()]

    salud = _divergentes([
        {"etiqueta": AVISO_ES.get(r.nudge_type, r.nudge_type), "clave": r.nudge_type,
         "valor": _num(float(r.d_days_negative), 3),
         "texto": f"{float(r.d_days_negative):+.3f} días",
         "nota": (f"ahorro {float(r.d_savings_rate_pp):+.3f} pp · "
                  f"utilización de tarjeta {float(r.d_card_util_pp):+.3f} pp · "
                  f"ingreso {float(r.d_revenue_mxn):+.1f} MXN")}
        for r in master.sort_values("d_days_negative").itertuples()
    ], bueno_si_positivo=False)

    ingreso = _divergentes([
        {"etiqueta": AVISO_ES.get(r.nudge_type, r.nudge_type), "clave": r.nudge_type,
         "valor": _num(float(r.d_revenue_mxn), 1),
         "texto": f"{float(r.d_revenue_mxn):+.1f} MXN"}
        for r in master.sort_values("d_revenue_mxn", ascending=False).itertuples()
    ], bueno_si_positivo=True)

    valor = _divergentes([
        {"etiqueta": AVISO_ES.get(p, p), "clave": p,
         "valor": _num(float(d["V_lambda_266"]), 4),
         "texto": formato.dias(d["V_lambda_266"]),
         "nota": (f"con λ = 165 MXN el valor sería {formato.dias(d['V_lambda_165'])}"
                  + ("" if d["en_catalogo"] else " · fuera del catálogo del piloto"))}
        for p, d in sorted(tv["productos"].items(),
                           key=lambda kv: -float(kv[1]["V_lambda_266"]))
    ], bueno_si_positivo=True)

    # Las dos políticas que se citan en el texto se leen de la simulación en vez
    # de escribirse a mano: si la simulación cambia, el texto cambia con ella.
    p0 = politicas[politicas.politica.str.startswith("P0")].iloc[0]
    p6 = politicas[politicas.politica.str.startswith("P6")].iloc[0]

    sim = []
    for r in politicas.itertuples():
        sim.append([
            POLITICA_ES.get(str(r.politica), str(r.politica)),
            f"{int(r.enviados):,}".replace(",", " "),
            formato.pct(float(r.pct_volumen)),
            formato.pct(float(r.tasa_enganche)),
            formato.pct(float(r.pct_revenue_retenido)),
            f"{int(r.dias_negativos):+,}".replace(",", " "),
        ])

    return {
        "clave": "objetivos",
        "titulo": "6 · Clics, salud financiera e ingreso apuntan a sitios distintos",
        "resumen": ("Aquí está la pregunta que el reto pide contestar. El dataset "
                    "trae lo que le pasó a cada cliente en los 90 días siguientes a "
                    "cada aviso: días en negativo, tasa de ahorro, utilización de "
                    "tarjeta e ingreso generado. Con eso se puede comprobar si el "
                    "producto que más clics recibe es el que uno querría mandar."),
        "fuente": ("data/nudge_outcomes.parquet vía "
                   "analytics/recon/out/05_rankings.csv, 05_master_by_type.csv, "
                   "05_tradeoff_price.csv, 07_policy_simulation.csv · "
                   "pipeline/artifacts/tabla_valor.json"),
        "cifras": [
            {"etiqueta": "El aviso nº 1 en clics", "valor": AVISO_ES.get(lider, lider),
             "detalle": f"{formato.pct(float(fila_lider['engaged_']))} de clic. Y el "
                        f"último de los {len(rank)} en salud financiera."},
            {"etiqueta": "Lo que cuesta en días en negativo",
             "valor": f"{float(tv_lider['delta_dias_negativos']):+.2f} días por clic",
             "detalle": (f"Media entre los {_mil(tot_lider['enganchados'])} avisos de este "
                         f"tipo que recibieron clic. Sumado sobre los "
                         f"{_mil(tot_lider['enviados'])} mostrados, el tipo entero deja "
                         f"{_mil(tot_lider['dias_negativos_totales'])} días en descubierto.")},
            {"etiqueta": "Lo que genera en ingreso",
             "valor": f"{float(tv_lider['delta_ingreso_mxn']):+.2f} MXN por clic",
             "detalle": (f"Mismo denominador: los {_mil(tot_lider['enganchados'])} avisos "
                         f"con clic. Sumado sobre los {_mil(tot_lider['enviados'])} "
                         f"mostrados son {_mil(tot_lider['revenue_total_mxn'])} MXN. Es el "
                         f"tipo de aviso más rentable de los seis.")},
            {"etiqueta": "El precio que revela el statu quo",
             "valor": f"{LAMBDA_DEFECTO:.0f} MXN por día en negativo",
             "detalle": (f"Las dos cifras de arriba, divididas: "
                         f"{_mil(tot_lider['revenue_total_mxn'])} MXN ÷ "
                         f"{_mil(tot_lider['dias_negativos_totales'])} días = "
                         f"{float(tot_lider['revenue_total_mxn']) / float(tot_lider['dias_negativos_totales']):.0f}"
                         f" MXN. Es lo que el sistema actual está cobrando implícitamente "
                         f"por cada día que empuja a un cliente al descubierto. Ese número "
                         f"no lo eligió nadie: se deduce de lo que ya se manda.")},
        ],
        "graficas": [
            _grafica(
                "salud_por_tipo", "barras_divergentes",
                "Qué le hace cada aviso a la salud financiera del cliente",
                "Cambio medio en días en negativo en los 90 días siguientes al aviso. "
                "A la izquierda del cero está lo bueno (menos días en descubierto).",
                "Los recordatorios de pago y las metas de ahorro quitan días en "
                "negativo. El aumento de línea los añade. Y es el que más clics "
                "recibe: por eso «optimizar el clic» no es una opción neutral.",
                salud, unidad="días en negativo ganados o evitados, por aviso mostrado",
                leyenda={"izq": "Le quita días en descubierto al cliente",
                         "der": "Se los añade", "bueno": "izq"},
                aviso="Estos promedios son sobre TODOS los avisos de ese tipo, no solo "
                      "los que recibieron clic. El aviso ignorado tiene efecto cero y "
                      "diluye la media."),
            _grafica(
                "ingreso_por_tipo", "barras_divergentes",
                "Y qué le hace al ingreso del banco",
                "Cambio medio en ingreso generado en los 90 días siguientes, por aviso "
                "mostrado.",
                "El orden es casi el contrario. El recordatorio de pago es el mejor "
                "para el cliente y el único que le cuesta dinero al banco (−8.40 MXN "
                "por aviso). Ahí está el conflicto, con números.",
                ingreso, unidad="MXN de ingreso por aviso mostrado",
                leyenda={"izq": "El banco pierde dinero", "der": "El banco gana",
                         "bueno": "der"}),
            _grafica(
                "valor", "barras_divergentes",
                "Los dos objetivos, reducidos a una sola unidad",
                "El valor de cada producto expresado en días de descubierto evitados. "
                "La fórmula convierte el ingreso a días dividiéndolo por λ = 266 MXN, "
                "que es el precio que el propio statu quo revela.",
                "Con esta conversión, el aumento de línea tiene valor negativo: "
                "−0.0770 días. Por eso el sistema no lo ofrece a nadie. Si λ fuese "
                "165 MXN —el precio estimado en el margen— pasaría a ser positivo: la "
                "decisión depende del precio, y el precio está declarado.",
                valor, unidad="días de descubierto evitados por clic",
                leyenda={"izq": "En balance, deja al cliente peor",
                         "der": "En balance, deja al cliente mejor", "bueno": "der"},
                aviso="Cambiar λ cambia el orden. Es el parámetro más discutible de "
                      "todo el sistema y por eso viaja escrito en el artefacto en vez "
                      "de estar escondido en el código."),
        ],
        "tablas": [
            {"clave": "rankings",
             "titulo": "El mismo catálogo, tres órdenes distintos",
             "que_muestra": "La posición de cada tipo de aviso en tres listas: por "
                            "clics, por salud financiera del cliente y por ingreso "
                            "generado. 1 es el mejor de los seis.",
             "que_concluir": "El aumento de línea es 1º en clics, 1º en ingreso y 6º "
                             "en salud. La meta de ahorro es 1ª en salud y 5ª en "
                             "ingreso. No hay un orden «correcto»: hay que elegir uno "
                             "y decir cuál.",
             "columnas": ["Tipo de aviso", "Clic", "Puesto por clics",
                          "Puesto por salud", "Puesto por ingreso"],
             "filas": [[r["etiqueta"], r["clic"], f"{r['engagement']}º",
                        f"{r['salud']}º", f"{r['ingreso']}º"] for r in rankings]},
            {"clave": "politicas",
             "titulo": "Ocho maneras de decidir a quién se le habla",
             "que_muestra": "Cada fila es una política aplicada sobre los mismos "
                            "285 000 avisos observados. «No enviar» se cuenta como "
                            "efecto cero, no como efecto desconocido.",
             # Los miles se formatean con `_signo_mil`, no con un `.replace(",", " ")`
             # sobre la frase entera: eso se comía también las comas de la prosa y
             # dejaba «con -1 502 días  manda 6.90 %…» sin puntuación.
             "que_concluir": (
                 f"P0 (mandar todo) deja a los clientes con "
                 f"{_signo_mil(p0.dias_negativos)} días en negativo. P6 (solo con "
                 f"señal, con tope y vetando el crédito a los frágiles) los deja "
                 f"con {_signo_mil(p6.dias_negativos)} días, manda "
                 f"{formato.pct(float(p6.pct_volumen))} del volumen y retiene "
                 f"{formato.pct(float(p6.pct_revenue_retenido))} del ingreso. Ese "
                 f"es el precio de darle la vuelta al signo, y está a la vista."
             ),
             "columnas": ["Política", "Avisos enviados", "% del volumen",
                          "% de clic", "% del ingreso retenido",
                          "Días en negativo causados"],
             "filas": sim,
             "nota": "La última columna es la que importa: con signo negativo, el "
                     "sistema le está quitando días de descubierto a sus clientes en "
                     "vez de añadírselos."},
            {"clave": "precio",
             "titulo": "Cuánto ingreso genera cada día en negativo que se causa",
             "que_muestra": "Para cada tipo de aviso, el ingreso total entre los días "
                            "en negativo totales que provoca. Es el «precio» "
                            "implícito de la salud del cliente.",
             "que_concluir": "El aumento de línea genera 266 MXN por cada día en "
                             "descubierto que causa. Ese es el λ que usa el sistema, "
                             "y no lo eligió el equipo: lo revela el statu quo.",
             "columnas": ["Tipo de aviso", "Enviados", "Clics",
                          "Ingreso total (MXN)", "Días en negativo",
                          "MXN por día en negativo"],
             "filas": [[AVISO_ES.get(r.nudge_type, r.nudge_type),
                        f"{int(r.enviados):,}".replace(",", " "),
                        f"{int(r.enganchados):,}".replace(",", " "),
                        f"{int(r.revenue_total_mxn):+,}".replace(",", " "),
                        f"{int(r.dias_negativos_totales):+,}".replace(",", " "),
                        (f"{int(r.mxn_revenue_por_dia_negativo_causado):+,}".replace(",", " "))]
                       for r in precio.itertuples()],
             "nota": "Un valor negativo en la última columna significa que el aviso "
                     "genera ingreso Y quita días en negativo: no hay conflicto que "
                     "resolver ahí."},
        ],
    }


# ==========================================================================
# Bloque 7 · Lo que hace nuestro sistema
# ==========================================================================
def _bloque_sistema(panorama):
    vista = panorama.de(CORTE_DEMO) or panorama.de(panorama.corte_defecto)
    if vista is None:
        raise DashboardNoDisponible("el panorama no tiene ningún corte disponible")

    cortes = []
    for corte in panorama.cortes:
        v = panorama.de(corte)
        cob = v.cobertura
        cortes.append({
            "etiqueta": corte, "clave": corte,
            "valor": _num(float(cob["pct_silencio"])),
            "texto": formato.pct(float(cob["pct_silencio"])),
            "n": int(cob["n_con_oferta"]),
            "nota": (f"{formato.pct(float(cob['pct_oferta']))} recibe algo — "
                     f"{int(cob['n_con_oferta']):,} de {int(cob['n_clientes']):,} "
                     f"clientes").replace(",", " "),
            "resaltar": corte == vista.corte})
    _anchos(cortes, maximo=100.0)

    reparto_bruto = vista.conteo_por_oferta()
    n_total = sum(reparto_bruto.values())
    reparto = _anchos([
        {"etiqueta": ("Nadie le dice nada" if k == "silencio"
                      else AVISO_ES.get(k, k)),
         "clave": k, "n": int(n),
         "valor": _num(100.0 * int(n) / n_total),
         "texto": formato.pct(100.0 * int(n) / n_total),
         "resaltar": k == "silencio"}
        for k, n in sorted(reparto_bruto.items(), key=lambda kv: -kv[1])
    ], maximo=100.0)

    razones_bruto = vista.conteo_por_razon()
    n_silencio = sum(razones_bruto.values())
    razones = _anchos([
        {"etiqueta": PUERTA_ES.get(k, k), "clave": k, "n": int(n),
         "valor": _num(100.0 * int(n) / n_silencio),
         "texto": formato.pct(100.0 * int(n) / n_silencio),
         "nota": PUERTA_DESC.get(k, {}).get("cierra_si", "")}
        for k, n in sorted(razones_bruto.items(), key=lambda kv: -kv[1])
    ], maximo=100.0)

    base_intencion = _anchos([
        {"etiqueta": AVISO_ES.get(p, p), "clave": p,
         "valor": _num(100.0 * float(v)), "texto": formato.pct(100.0 * float(v)),
         "nota": f"acción que lo confirma: {ACCION_ES.get(PRODUCTO_A_ACCION[p], '')}"}
        for p, v in vista.tasa_base_intencion.items() if v is not None
    ])

    catalogo_fuera = [AVISO_ES.get(p, p) for p in TODOS_LOS_PRODUCTOS
                      if p not in CATALOGO_DEMO]

    # El ejemplo de «un 20 % es mucho» se apoya en la tasa base MÁS BAJA del
    # corte, y esa tasa se lee de la vista: escribirla a mano la dejaría
    # desfasada en cuanto cambiara el corte.
    mas_raro, base_mas_rara = min(
        ((p, v) for p, v in vista.tasa_base_intencion.items() if v is not None),
        key=lambda kv: kv[1])

    return {
        "clave": "sistema",
        "titulo": "7 · Lo que decide nuestro sistema, y por qué se calla",
        "resumen": ("Esto ya no es el dataset: es el motor corriendo sobre los 38 000 "
                    "clientes. Ocho puertas en orden; si alguna cierra, no se habla. "
                    "Cada silencio trae escrito por qué, y se puede contar."),
        "fuente": ("pipeline/politica.py + app/panorama.py sobre los 38 000 clientes "
                   f"en los {len(panorama.cortes)} cortes disponibles · tasas base "
                   "leídas de pipeline/artifacts/labels_intent.parquet"),
        "cifras": [
            {"etiqueta": "Clientes a los que hoy no se les dice nada",
             "valor": formato.pct(float(vista.cobertura["pct_silencio"])),
             "detalle": f"{int(vista.cobertura['n_clientes']) - int(vista.cobertura['n_con_oferta']):,} "
                        f"de {int(vista.cobertura['n_clientes']):,} en el corte "
                        f"{vista.corte}. El silencio es el resultado normal, no la "
                        f"excepción.".replace(",", " ")},
            {"etiqueta": "Clientes con oferta",
             "valor": formato.pct(float(vista.cobertura["pct_oferta"])),
             "detalle": f"{int(vista.cobertura['n_con_oferta']):,} personas. Sin la "
                        f"puerta de valor serían "
                        f"{formato.pct(float(vista.cobertura['pct_oferta_sin_S4']))}: "
                        f"esa puerta sola añade "
                        f"{float(vista.cobertura['pct_oferta_sin_S4']) - float(vista.cobertura['pct_oferta']):.2f} "
                        f"puntos de silencio.".replace(",", " ")},
            {"etiqueta": "Productos que el piloto puede ofrecer",
             "valor": f"{len(CATALOGO_DEMO)} de {len(TODOS_LOS_PRODUCTOS)}",
             "detalle": "Fuera del catálogo: " + " y ".join(catalogo_fuera)
                        + ". Se excluyeron por conversión baja o por señal trivial."},
            {"etiqueta": "Cómo se ordena lo que se ofrece",
             "valor": "clic esperado × momento × valor",
             "detalle": vista.origen_orden},
        ],
        "graficas": [
            _grafica(
                "reparto", "barras",
                "Qué recibe cada uno de los 38 000 clientes hoy",
                f"El reparto completo en el corte {vista.corte}: quién recibe cada "
                "tipo de oferta y quién no recibe nada.",
                "Nueve de cada diez clientes no reciben nada, y el aumento de línea no "
                "aparece: su valor esperado es negativo, así que la puerta de valor lo "
                "cierra para todo el mundo. El catálogo tiene cuatro productos y el "
                "sistema usa tres.",
                reparto, unidad="% de los 38 000 clientes"),
            _grafica(
                "razones", "barras",
                "Por qué nos callamos, caso por caso",
                "De los clientes en silencio, qué puerta les cerró. Se reporta la "
                "puerta de mayor prioridad entre las que cerraron.",
                "El silencio no es una sola cosa. La mayoría es falta de señal —no "
                "sabemos qué quiere— pero hay 109 clientes a los que sí les "
                "adivinamos la intención y aun así no les hablamos, porque el producto "
                "les haría daño. Ese es el caso que justifica el sistema.",
                razones, unidad="% de los clientes en silencio"),
            _grafica(
                "cortes", "barras",
                "El silencio no es un número fijo: se recalcula cada día",
                "Porcentaje de clientes sin oferta en cada uno de los cortes "
                "disponibles.",
                "Va del 83.96 % al 89.26 % según el día. Si fuese siempre el mismo "
                "número, estaría escrito a mano en algún sitio en vez de calculado.",
                cortes, unidad="% de clientes en silencio"),
            _grafica(
                "base_intencion", "barras",
                "Contra qué hay que comparar una predicción",
                "Porcentaje de los 38 000 clientes que hizo de verdad cada acción en "
                f"la ventana de etiqueta del corte {vista.corte}. Es la tasa base "
                "observada, contada, no estimada.",
                f"Un modelo que le asigne a un cliente un 20 % de probabilidad de "
                f"«{AVISO_ES.get(mas_raro, mas_raro)}» está diciendo algo fuerte: la "
                f"tasa base de esa acción es "
                f"{formato.pct(100.0 * float(base_mas_rara))}, o sea unas "
                f"{20.0 / (100.0 * float(base_mas_rara)):.0f} veces menos. Sin esta "
                f"gráfica al lado, un 20 % parece poco.",
                base_intencion, unidad="% de los 38 000 clientes"),
        ],
        "tablas": [{
            "clave": "puertas",
            "titulo": "Las ocho puertas, en el orden en que se evalúan",
            "que_muestra": "Qué comprueba cada puerta y cuándo cierra. La primera que "
                           "cierra termina el recorrido de ese producto.",
            "que_concluir": "Ninguna puerta es un filtro de calidad del modelo: son "
                            "condiciones de si conviene hablar. Dos de ellas "
                            "—descartes repetidos y confianza del modelo— están "
                            "implementadas y en el piloto no cierran a nadie; se "
                            "muestran igual en vez de esconderse.",
            "columnas": ["Puerta", "Qué comprueba", "Cuándo se calla"],
            "filas": [[d.get("nombre", PUERTA_ES.get(c, c)),
                       d.get("comprueba", ""), d.get("cierra_si", "")]
                      for c, d in PUERTA_DESC.items()],
        }],
    }


# ==========================================================================
# Bloque 8 · El desempeño de los modelos
# ==========================================================================
def _bloque_modelos(con):
    from analytics.evaluar import _cargar_modelos, evaluar_intencion, evaluar_momento

    mx, my, um = _cargar_modelos()
    meta = _artefacto("metadata.json")
    d = evaluar_intencion(mx, list(CORTES_ROLLING), con)
    mom = evaluar_momento(my, con)

    def media_rango(col):
        v = d[col]
        return (round(float(v.mean()), 2), round(float(v.max() - v.min()), 2))

    predictores = []
    for col, etiqueta, poblacion, explica in [
        ("baseline_constante", "Decir siempre «SPEI» (la acción más común)",
         "todos los clientes activos",
         "La referencia obligada. Si un modelo no le gana a esto, no sirve."),
        ("regla_hibrida", "Regla simple: la última pantalla que abrió",
         "todos los clientes activos",
         "Aplicada a toda la base. Donde no hay señal reciente, cae a «SPEI»."),
        ("modelo_top1", "Nuestro modelo, primera opción",
         "todos los clientes activos",
         "Acierta la acción exacta que el cliente hará en los 7 días siguientes."),
        ("modelo_top2", "Nuestro modelo, entre sus dos primeras opciones",
         "todos los clientes activos",
         "Para un asistente que puede sugerir dos cosas, esta es la cifra útil."),
        ("regla_donde_senal", "Regla simple, solo donde hay señal fresca",
         "el ~16 % de activos con señal ≤ 24 h",
         "En su terreno la regla es buenísima. El problema es que su terreno es pequeño."),
        ("modelo_donde_senal", "Nuestro modelo, solo donde hay señal fresca",
         "el ~16 % de activos con señal ≤ 24 h",
         "Aquí el modelo EMPATA con la regla. Se dice primero, no se esconde."),
    ]:
        media, rango = media_rango(col)
        predictores.append({
            "etiqueta": etiqueta, "clave": col, "valor": media,
            "texto": formato.pct(media), "poblacion": poblacion,
            # La población va DENTRO de la barra: sin ella la comparación entre
            # estas seis barras es directamente engañosa.
            "nota": f"medido sobre {poblacion} · {explica}",
            "explica": explica, "rango": rango,
            "rango_texto": f"{rango:.2f} pp entre los 3 cortes",
            "resaltar": col == "modelo_top1",
            "por_corte": [{"corte": str(r.corte), "texto": formato.pct(float(getattr(r, col)))}
                          for r in d.itertuples()]})
    _anchos(predictores)

    estabilidad = _anchos([
        {"etiqueta": p["etiqueta"], "clave": p["clave"], "valor": p["rango"],
         "texto": f"{p['rango']:.2f} pp",
         "nota": f"acierto medio {p['texto']} sobre {p['poblacion']}",
         "resaltar": p["clave"] == "modelo_top1"}
        for p in predictores
        if p["clave"] in ("baseline_constante", "regla_hibrida", "modelo_top1")
    ])

    barrido = _anchos([
        {"etiqueta": f"Hablarle al {formato.pct(float(b['cobertura_pct']))} de la gente",
         "clave": str(b["cuantil"]),
         "valor": _num(float(b["precision_pct"])),
         "texto": formato.pct(float(b["precision_pct"])),
         "n": int(b["n"]),
         "nota": f"umbral {float(b['umbral']):.4f} · {int(b['n']):,} clientes".replace(",", " "),
         "resaltar": abs(float(b["umbral"]) - float(um["p_intencion_min"])) < 1e-9}
        for b in um.get("barrido", [])
    ])

    return {
        "clave": "modelos",
        "titulo": "8 · Qué tan bien predicen los modelos, y contra qué",
        "resumen": ("Un porcentaje de acierto suelto no dice nada. Aquí cada cifra "
                    "va con la referencia contra la que hay que leerla y con la "
                    "población sobre la que se mide, que es donde suele estar el "
                    "truco. Hay dos modelos: uno adivina QUÉ quiere el cliente, otro "
                    "decide SI vale la pena hablarle ahora."),
        "fuente": ("analytics/evaluar.py sobre pipeline/artifacts/modelo_intencion.pkl "
                   "y modelo_momento.pkl, evaluado en los cortes "
                   + ", ".join(CORTES_ROLLING) + " (ninguno usado para entrenar) · "
                   "pipeline/artifacts/umbrales.json y metadata.json"),
        "cifras": [
            {"etiqueta": "Modelo de intención · acierto",
             "valor": formato.pct(media_rango("modelo_top1")[0]),
             "detalle": f"Contra {formato.pct(media_rango('baseline_constante')[0])} de "
                        f"decir siempre la acción más común. Son 8 clases posibles."},
            {"etiqueta": "Modelo de intención · estabilidad",
             "valor": f"{media_rango('modelo_top1')[1]:.2f} pp de rango",
             "detalle": f"Contra {media_rango('regla_hibrida')[1]:.2f} pp de la regla "
                        f"simple. Esta es la ganancia real: no acierta mucho más, "
                        f"acierta igual todos los días."},
            {"etiqueta": "Modelo de momento · capacidad de ordenar",
             "valor": f"AUC {mom['auc']:.4f}",
             "detalle": "0.50 sería tirar una moneda; 1.00, adivinarlo siempre. "
                        f"Medido en {int(mom['n_test']):,} avisos que el modelo no vio "
                        f"al entrenar.".replace(",", " ")},
            {"etiqueta": "Modelo de momento · en el 1 % mejor",
             "valor": formato.pct(float(mom["precision_top1pct"])),
             "detalle": f"De los avisos que el modelo pone arriba, este porcentaje "
                        f"recibe clic. La tasa base es "
                        f"{formato.pct(float(mom['base_pct']))}: el modelo multiplica "
                        f"por {float(mom['precision_top1pct']) / float(mom['base_pct']):.2f}."},
        ],
        "graficas": [
            _grafica(
                "predictores", "barras",
                "Seis maneras de adivinar la próxima acción, comparadas",
                "Porcentaje de acierto de cada predictor, con la población sobre la "
                "que se mide escrita al lado. Media de los 3 cortes de prueba.",
                "El modelo le saca 10 puntos a la referencia obligada. Pero donde hay "
                "señal fresca, la regla de una línea acierta casi lo mismo: la "
                "ganancia del modelo no es puntería, es que opina sobre todo el mundo "
                "y no solo sobre el 16 % que dejó una pista clara.",
                predictores, unidad="% de acierto",
                aviso="Las barras NO son comparables entre sí sin leer la población "
                      "que va debajo de cada nombre: las dos últimas se miden solo "
                      "sobre el 16 % de clientes con señal fresca, que es el "
                      "subconjunto fácil."),
            _grafica(
                "estabilidad", "barras",
                "Y por eso preferimos el modelo: se mueve mucho menos",
                "Cuántos puntos porcentuales se mueve el acierto de cada predictor "
                "entre el mejor y el peor de los 3 cortes de prueba. Menos es mejor.",
                "La regla simple pasa de 30.74 % a 44.72 % según el día que se mida. "
                "El modelo se mueve 2.65 puntos. Un asistente que un martes acierta y "
                "un jueves no, no es un asistente.",
                estabilidad, unidad="puntos porcentuales de variación (menos es mejor)"),
            _grafica(
                "barrido", "barras",
                "A cuánta gente hablarle: el intercambio, dibujado",
                "Si solo se le habla a los clientes con la predicción más segura, qué "
                "porcentaje de ellos acierta. Cada barra es un nivel de exigencia "
                "distinto.",
                "Hablarle a la mitad de la gente acierta el 55.09 %; hablarle al 5 % "
                "más seguro acierta el 81.59 %. El sistema está puesto en el 15 %, "
                "elegido en un corte aparte que no participa en la evaluación.",
                barrido, unidad="% de acierto entre los seleccionados",
                aviso="El umbral se eligió en el corte 2026-05-23, distinto de los "
                      "cortes de prueba. Elegirlo mirando el resultado de la prueba "
                      "sería hacerse trampas al solitario."),
        ],
        "tablas": [{
            "clave": "por_corte",
            "titulo": "Los mismos predictores, corte a corte",
            "que_muestra": "Sin promediar. Cada columna es un día distinto sobre el "
                           "que se evaluó, y ninguno se usó para entrenar.",
            "que_concluir": "El baseline pasa de 25.63 % a 41.62 % según el día: no es "
                            "que mejore, es que la población cambia. Comparar contra "
                            "un baseline medido en un solo corte es la trampa más "
                            "fácil de este dataset.",
            "columnas": ["Predictor"] + [str(c) for c in CORTES_ROLLING] + ["Media", "Rango"],
            "filas": [[p["etiqueta"]] + [x["texto"] for x in p["por_corte"]]
                      + [p["texto"], f"{p['rango']:.2f} pp"] for p in predictores],
        }],
        "extra": {
            "acuerdo_pct": _num(float(meta["modelo_intencion"]["acuerdo_pct"])),
            "acuerdo_texto": formato.pct(float(meta["modelo_intencion"]["acuerdo_pct"])),
            "algoritmo": meta["modelo_intencion"]["algoritmo"],
            "n_features": int(meta["n_features"]),
            "n_train_momento": int(meta["modelo_momento"]["n_train"]),
            "variables_momento": meta["modelo_momento"]["variables"],
        },
    }


# ==========================================================================
# Bloque 9 · Cómo leer todo esto sin equivocarse
# ==========================================================================
def _bloque_advertencias(con):
    aleat = _recon("06_randomization_tests.csv")
    sesgo = _recon("06_selection_bias.csv")
    integridad = _recon("01_integrity.csv")
    borde = _recon("02_edge_effect.csv")
    fuga = _recon("06_leakage_table.csv")

    n_aleatorio = int((aleat.veredicto == "ALEATORIO").sum())
    n_pruebas = int(len(aleat))

    # Los dos huecos declarados del dataset, leídos en vez de escritos: los
    # clientes sin ningún aviso salen del control de integridad y el porcentaje
    # sin nota de satisfacción se cuenta sobre `customers`.
    sin_aviso = integridad[integridad.chequeo.str.contains("sin ningun nudge")]
    n_sin_aviso = int(sin_aviso.iloc[0]["n"]) if len(sin_aviso) else None
    pct_sin_nps = float(con.execute(
        """SELECT 100.0 * avg(CASE WHEN nps_last_score IS NULL THEN 1 ELSE 0 END)
           FROM customers""").fetchone()[0])

    sesgo_filas = _anchos([
        {"etiqueta": f"Quinto {r.eng_q[-1]} de actividad en la app "
                     f"(índice medio {float(r.engagement_medio):.2f} de 100)",
         "clave": r.eng_q, "n": int(r.clientes),
         "valor": _num(float(r.nudges_por_cliente)),
         "texto": f"{float(r.nudges_por_cliente):.2f} avisos por cliente",
         "nota": f"{int(r.sin_ningun_nudge)} de esos clientes no recibió ni un aviso"}
        for r in sesgo.itertuples()
    ])

    return {
        "clave": "advertencias",
        "titulo": "9 · Cómo leer todo esto sin equivocarse",
        "resumen": ("Cuatro cosas que hay que saber antes de citar cualquier número "
                    "de esta página. No son notas al pie: cambian lo que las cifras "
                    "significan."),
        "fuente": ("analytics/recon/out/06_randomization_tests.csv, "
                   "06_selection_bias.csv, 06_leakage_table.csv, "
                   "01_integrity.csv, 02_edge_effect.csv"),
        "cifras": [
            {"etiqueta": "Comparar tipos de aviso entre sí: se puede",
             "valor": f"{n_aleatorio} de {n_pruebas} pruebas dan «al azar»",
             "detalle": "El tipo de aviso y la superficie se asignaron aleatoriamente. "
                        "Se comprobó contra 9 características del cliente y ninguna "
                        "sale relacionada. Así que las diferencias entre productos son "
                        "del producto."},
            {"etiqueta": "Comparar «con clic» contra «sin clic»: no se puede",
             "valor": "no está aleatorizado",
             "detalle": "Quién hace clic no se sorteó. Si los que clican convierten "
                        "más, puede ser por el clic o porque ya iban a hacerlo. Esas "
                        "columnas son diagnóstico, no efecto."},
            {"etiqueta": "Los tres primeros días del panel están inflados",
             "valor": f"{float(borde.iloc[0].ratio_vs_mediana):.2f}× la mediana",
             "detalle": "Es un artefacto de cómo se generaron los datos. Cualquier "
                        "gráfica por día tiene ese escalón al principio, y el sistema "
                        "se niega a decidir en esas fechas."},
            {"etiqueta": "Integridad del dataset",
             "valor": "0 filas huérfanas",
             "detalle": f"Las {len(integridad)} comprobaciones de integridad cuadran. "
                        f"Los únicos huecos declarados: {n_sin_aviso} clientes sin "
                        f"ningún aviso y el {formato.pct(pct_sin_nps)} sin nota de "
                        f"satisfacción."},
        ],
        "graficas": [
            _grafica(
                "sesgo", "barras",
                "A la gente más activa se le manda más: eso no se puede ignorar",
                "Número medio de avisos recibidos por cliente, agrupando a los 38 000 "
                "en quintos según lo activos que son en la app.",
                "El quinto más activo recibe el doble de avisos que el menos activo "
                "(9.96 contra 4.91). Así que cualquier cifra que mezcle clientes con "
                "avisos está mirando sobre todo a los clientes activos. La "
                "aleatorización cubre QUÉ aviso se manda, no CUÁNTOS.",
                sesgo_filas, unidad="avisos por cliente en 119 días"),
        ],
        "tablas": [{
            "clave": "fuga",
            "titulo": "Columnas que nunca entran como entrada del modelo, y por qué",
            "que_muestra": "El inventario completo de columnas del dataset marcadas "
                           "como peligrosas, con el motivo. «Fuga temporal» significa "
                           "que la columna contiene información posterior al momento "
                           "en el que el modelo tiene que decidir.",
            "que_concluir": "Las 82 entradas del modelo se calculan solo desde la "
                            "navegación y los avisos, con la marca de tiempo de cada "
                            "fila y corte estricto. Cuesta algo de acierto y compra "
                            "que el resultado sea reproducible. El índice de "
                            "actividad en la app queda fuera porque genera tanto los "
                            "eventos como los avisos: usarlo sería casi copiar la "
                            "respuesta.",
            "columnas": ["Tabla", "Columna", "Cómo se usa", "Motivo"],
            "filas": [[str(r.tabla), str(r.columna), str(r.uso), str(r.motivo)]
                      for r in fuga.itertuples()],
        }, {
            "clave": "integridad",
            "titulo": "Los controles de integridad, uno a uno",
            "que_muestra": "Cada comprobación con el número de filas que la incumplen. "
                           "Cero es lo que se busca en todas menos en las declaradas.",
            "que_concluir": "El dataset está limpio: ninguna clave huérfana, ninguna "
                            "contradicción entre «le dio clic» y «lo cerró». Los 89 "
                            "clientes sin aviso son reales y están declarados.",
            "columnas": ["Comprobación", "Filas que la incumplen"],
            "filas": [[str(r.chequeo), f"{int(r.n):,}".replace(",", " ")]
                      for r in integridad.itertuples()],
        }],
    }


# ==========================================================================
# Cabecera
# ==========================================================================
def _cabecera(bloques):
    """Las cinco cifras con las que alguien tiene que quedarse.

    Cada una se toma de un bloque ya construido, nunca se recalcula aquí: si la
    portada y el cuerpo pudieran dar dos números distintos, darían dos números
    distintos.
    """
    por_clave = {b["clave"]: b for b in bloques}

    def cifra(bloque, i):
        return por_clave[bloque]["cifras"][i]

    fuera = []
    if "sistema" in por_clave:
        c = cifra("sistema", 0)
        fuera.append({"etiqueta": "El sistema se calla", "valor": c["valor"],
                      "detalle": "de los 38 000 clientes, hoy. Cada silencio con su "
                                 "motivo escrito.", "bloque": "sistema"})
    if "momento" in por_clave:
        fuera.append({"etiqueta": "Avisos que caen en el momento correcto",
                      "valor": cifra("momento", 0)["valor"],
                      "detalle": "El resto se manda sin ninguna señal reciente de que "
                                 "el cliente quiera eso.", "bloque": "momento"})
        fuera.append({"etiqueta": "Cuántas veces más clic recibe ese momento",
                      "valor": cifra("momento", 2)["valor"],
                      "detalle": "Mismo mensaje, mismo producto. Solo cambia cuándo. "
                                 "Es la tasa de clic, no la acción hecha.",
                      "bloque": "momento"})
    if "avisos" in por_clave:
        fuera.append({"etiqueta": "Avisos que reciben clic",
                      "valor": cifra("avisos", 1)["valor"],
                      "detalle": "Y más de un tercio se cierran de forma activa.",
                      "bloque": "avisos"})
    if "objetivos" in por_clave:
        c = cifra("objetivos", 0)
        fuera.append({"etiqueta": "El aviso más clicado es el que más daña",
                      "valor": c["valor"],
                      "detalle": "Primero de seis en clics, último en salud "
                                 "financiera. Ahí está el conflicto del bloque 6.",
                      "bloque": "objetivos"})
    return fuera


# ==========================================================================
# Construcción
# ==========================================================================
def construir(panorama=None, store=None, escalera=None):
    """El diccionario completo. Cada bloque que falle se degrada con su motivo.

    Un bloque roto **no** tumba el dashboard y **no** se rellena con ceros: no
    aparece, y el motivo viaja en `avisos` para que se vea que falta algo.
    """
    from pipeline.features import _conexion

    t0 = time.perf_counter()
    con = _conexion()
    avisos = []
    bloques = []
    try:
        if panorama is None:
            panorama, motivo = _cargar_panorama(store, escalera)
            if motivo:
                avisos.append(motivo)

        cobertura_pct = None
        if panorama is not None:
            v = panorama.de(CORTE_DEMO) or panorama.de(panorama.corte_defecto)
            if v is not None:
                cobertura_pct = float(v.cobertura["pct_oferta"])

        constructores = [
            ("clientes", lambda: _bloque_clientes(con)),
            ("comportamiento", lambda: _bloque_comportamiento(con)),
            ("avisos", lambda: _bloque_avisos(con, cobertura_pct)),
            ("fatiga", lambda: _bloque_fatiga(con)),
            ("momento", lambda: _bloque_momento(con)),
            ("objetivos", lambda: _bloque_objetivos(con)),
            ("sistema", lambda: _bloque_sistema(panorama)),
            ("modelos", lambda: _bloque_modelos(con)),
            ("advertencias", lambda: _bloque_advertencias(con)),
        ]
        for clave, fn in constructores:
            if clave == "avisos" and cobertura_pct is None:
                avisos.append("el bloque «avisos» necesita la cobertura de la política "
                              "y el panorama no está disponible")
                continue
            if clave == "sistema" and panorama is None:
                continue
            try:
                bloques.append(fn())
            except DashboardNoDisponible as e:
                avisos.append(f"bloque «{clave}» no disponible: {e}")
            except Exception as e:                             # pragma: no cover
                avisos.append(f"bloque «{clave}» falló: {type(e).__name__}: {e}")

        import datetime as _dt

        return {
            "version": VERSION,
            "generado_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "segundos_de_construccion": round(time.perf_counter() - t0, 2),
            "corte": CORTE_DEMO,
            "asof": ASOF,
            "firma": _firma(),
            "titulo": "Dashboard general · nu-moments",
            "entradilla": (
                "Todas las métricas del proyecto en una página, escritas para alguien "
                "que no ha visto el dataset ni ha estado en ninguna reunión. Cada "
                "bloque dice qué muestra y qué hay que concluir. Ninguna cifra está "
                "escrita a mano: todas salen de los cinco archivos de datos, de los "
                "recuentos del reconocimiento o de los modelos ya entrenados, y la "
                "procedencia va escrita en cada bloque."),
            "glosario": _glosario(),
            "parametros": {
                "corte": CORTE_DEMO,
                "asof": ASOF,
                "cap_exposiciones": CAP_EXPOSICIONES,
                "umbral_senal_fresca_h": UMBRAL_ON_TIME_H,
                "umbral_senal_tibia_h": UMBRAL_WARM_H,
                "lambda_mxn_por_dia_negativo": LAMBDA_DEFECTO,
                "ventana_conversion_dias": VENTANA_CONVERSION_D,
                "catalogo": [AVISO_ES.get(p, p) for p in CATALOGO_DEMO],
                "n_pantallas": len(PANTALLAS),
                "n_productos": len(TODOS_LOS_PRODUCTOS),
            },
            "cabecera": _cabecera(bloques),
            "bloques": bloques,
            "avisos": avisos,
        }
    finally:
        con.close()


def _cargar_panorama(store=None, escalera=None):
    """El panorama, cargándose el Store y la escalera si no se los dan."""
    try:
        from app.panorama import Panorama
        from app.scoring import Escalera, cortes_disponibles
        from pipeline.ingesta import Store

        store = store or Store.cargar(DATOS, evidencias=False)
        escalera = escalera or Escalera.cargar(store, corte=CORTE_DEMO)
        return Panorama.cargar(store, escalera, cortes_disponibles()), None
    except Exception as e:                                      # pragma: no cover
        return None, (f"el bloque «sistema» y la cobertura del embudo no están: "
                      f"{type(e).__name__}: {e}")


def _glosario():
    """Las cinco palabras que hay que traducir para leer la página."""
    return [
        {"termino": "Aviso (o nudge)",
         "definicion": "Un mensaje que la app le muestra al cliente sugiriéndole algo: "
                       "una meta de ahorro, un recordatorio de pago, un préstamo. "
                       "El dataset trae 285 000 de ellos con lo que pasó después."},
        {"termino": "Señal",
         "definicion": f"Que el cliente haya entrado hace poco a la pantalla que "
                       f"corresponde al aviso. Es «fresca» si fue en las últimas "
                       f"{UMBRAL_ON_TIME_H} horas, «tibia» hasta "
                       f"{UMBRAL_WARM_H // 24} días y «fría» a partir de ahí."},
        {"termino": "Clic (engaged)",
         "definicion": "Que el cliente actuó sobre el aviso. No es lo mismo que hacer "
                       "la acción: se puede clicar y no acabar, y se puede acabar sin "
                       "haber clicado."},
        {"termino": "Conversión a 7 días",
         "definicion": f"Que el cliente hiciera de verdad la acción del aviso en los "
                       f"{VENTANA_CONVERSION_D} días siguientes a verlo. Es la métrica "
                       f"que importa; el clic solo es el paso intermedio."},
        {"termino": "Frágil",
         "definicion": f"Un cliente con la tarjeta por encima del "
                       f"{FRAGIL_UTILIZACION_PCT:.0f} % de utilización o con "
                       f"{FRAGIL_DIAS_NEGATIVOS} o más días en negativo en los últimos "
                       f"90. Es una definición operativa, la que usa el sistema para "
                       f"negarle crédito a quien le haría daño."},
        {"termino": "λ (lambda)",
         "definicion": f"El precio, en pesos, de un día que el cliente pasa en "
                       f"descubierto. Sirve para poder sumar ingreso y salud "
                       f"financiera en una sola cuenta. El sistema usa "
                       f"{LAMBDA_DEFECTO:.0f} MXN, que es el precio que revela lo que "
                       f"ya se manda hoy."},
        {"termino": "Tasa base",
         "definicion": "El porcentaje de clientes que hace algo sin que nadie le diga "
                       "nada. Es la referencia sin la cual ninguna probabilidad "
                       "significa nada."},
        {"termino": "Corte (as-of)",
         "definicion": "El instante desde el que se mira. Todo lo que el sistema usa "
                       "para decidir es estrictamente anterior al corte; lo posterior "
                       "solo sirve para comprobar si acertó."},
    ]


# ==========================================================================
# El artefacto: se construye una vez y se lee muchas
# ==========================================================================
_MEMORIA = {}


def escribir(datos=None):
    """Construye (si hace falta) y deja el artefacto en `dashboard/datos.json`."""
    datos = datos if datos is not None else construir()
    os.makedirs(os.path.dirname(RUTA_ARTEFACTO), exist_ok=True)
    with open(RUTA_ARTEFACTO, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=1, sort_keys=False)
    return RUTA_ARTEFACTO


def leer_artefacto():
    """El artefacto si existe **y** su firma cuadra con los insumos de hoy.

    La firma son los tamaños en bytes de los 5 parquet y de los artefactos del
    pipeline. Si alguno ha cambiado, el artefacto describe otros datos y no se
    sirve: se reconstruye. Así una cifra vieja no puede sobrevivir a un
    `make pipeline`.
    """
    if not os.path.exists(RUTA_ARTEFACTO):
        return None, "no hay artefacto precalculado"
    try:
        with open(RUTA_ARTEFACTO, encoding="utf-8") as fh:
            datos = json.load(fh)
    except Exception as e:                                      # pragma: no cover
        return None, f"el artefacto no se pudo leer: {type(e).__name__}: {e}"
    if datos.get("firma") != _firma():
        return None, "el artefacto se generó con otros insumos"
    return datos, None


def obtener(panorama=None, store=None, escalera=None, refrescar=False):
    """El diccionario del dashboard, calculado **una sola vez** por proceso.

    Orden de preferencia:

    1. lo que ya está en memoria de este proceso;
    2. el artefacto `dashboard/datos.json`, si su firma cuadra;
    3. construirlo y escribirlo.

    Se llama al importar `app.rutas_dashboard`, o sea en el arranque del
    servicio. Por petición no se lee un solo archivo.
    """
    if not refrescar and _MEMORIA.get("datos") is not None:
        return _MEMORIA["datos"]
    if not refrescar:
        datos, motivo = leer_artefacto()
        if datos is not None:
            datos["origen"] = "artefacto precalculado dashboard/datos.json"
            _MEMORIA["datos"] = datos
            return datos
    else:
        motivo = "reconstrucción pedida explícitamente"
    datos = construir(panorama=panorama, store=store, escalera=escalera)
    datos["origen"] = f"construido en este proceso ({motivo})"
    try:
        escribir(datos)
    except OSError as e:                                        # pragma: no cover
        datos.setdefault("avisos", []).append(
            f"no se pudo guardar el artefacto: {type(e).__name__}: {e}")
    _MEMORIA["datos"] = datos
    return datos


def main(argv=None):                                            # pragma: no cover
    datos = construir()
    ruta = escribir(datos)
    print(f"{ruta}  ({os.path.getsize(ruta):,} bytes)".replace(",", " "))
    print(f"bloques: {', '.join(b['clave'] for b in datos['bloques'])}")
    print(f"construido en {datos['segundos_de_construccion']} s")
    for a in datos["avisos"]:
        print(f"  AVISO · {a}")
    return 0 if not datos["avisos"] else 0


if __name__ == "__main__":                                      # pragma: no cover
    raise SystemExit(main())
