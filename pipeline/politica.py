"""ING-3 · El Reglamento del Silencio: las 8 puertas S0–S7.

Dos listas distintas, y es a propósito:

* **Orden de evaluación** `S0 → S6 → S1 → S2 → S5 → S3 → S7 → S4`
  Es el orden en que se corren las puertas y el orden en que se escribe la traza.

* **Prioridad de reporte** `S0 > S6 > S3 > S2 > S5 > S7 > S4 > S1`
  Es el orden en que se elige *qué* silencio se le cuenta al usuario. Un cliente
  frágil con cupo libre reporta **veto por daño**, no un silencio genérico.

Este módulo no escribe copy: emite códigos y hechos. La redacción vive en
`app/razones.py`, para que la política se pueda probar sin depender del texto.
"""
from __future__ import annotations

import os

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.mapas import (
    CAP_EXPOSICIONES,
    CATALOGO_DEMO,
    FRAGIL_DIAS_NEGATIVOS,
    FRAGIL_UTILIZACION_PCT,
    PRODUCTO_A_PANTALLA,
    TODOS_LOS_PRODUCTOS,
    UMBRAL_ON_TIME_H,
    UMBRAL_WARM_H,
)

# --------------------------------------------------------------------------
# Códigos de puerta. Son contrato: la traza los emite tal cual.
# --------------------------------------------------------------------------
S0 = "S0_opt_out"
S6 = "S6_fecha"
S1 = "S1_sin_senal"
S2 = "S2_cupo"
S5 = "S5_descartes"
S3 = "S3_fragilidad"
S7 = "S7_confianza"
S4 = "S4_valor"
C0 = "C0_fuera_de_catalogo"

ORDEN_EVALUACION = [S0, S6, S1, S2, S5, S3, S7, S4]
PRIORIDAD_REPORTE = [S0, S6, S3, S2, S5, S7, S4, S1]

# S5 y S7 se declaran no activas en el piloto (D14). Están implementadas: se
# evalúan, se registran como `no_activa` y no cierran a nadie.
PUERTAS_ACTIVAS = {S0: True, S6: True, S1: True, S2: True,
                   S5: False, S3: True, S7: False, S4: True}

# Puertas que aplican al cliente entero, no a un producto.
PUERTAS_DE_CLIENTE = {S0, S6}

# D5 · veto duro, no precio. El préstamo se evaluó y se descartó extender el
# veto: cuesta 6.5 pp de ingreso y no mejora los días en negativo.
PRODUCTOS_DANINOS_PARA_FRAGIL = {"limit_increase"}

# S5: descartes repetidos. Umbral derivado del mismo cap de exposición.
UMBRAL_DESCARTES = 2

# S7: confianza mínima del modelo para hablar.
UMBRAL_CONFIANZA_DEFECTO = 0.05

# Momentos que la puerta S1 considera "señal reciente".
MOMENTOS_CON_SENAL = ("on_time", "warm")

# Los cuatro estados de la señal, del más fresco al más frío. El orden ordinal
# es el mismo que consume `modelo_momento.pkl` (variable `senal`).
MOMENTO_ON_TIME, MOMENTO_WARM, MOMENTO_COLD, MOMENTO_NEVER = 0, 1, 2, 3
MOMENTOS = ("on_time", "warm", "cold", "never")

# Prioridad de salud financiera para desempatar candidatos con el mismo score.
PRIORIDAD_SALUD = ["savings_goal", "bill_reminder", "loan_offer", "limit_increase"]

SUPERFICIE = "in_app_modal"   # +4.64 pp sobre push con el mismo opt-out


class ErrorDePolitica(Exception):
    """Falta un insumo que la política necesita. Nunca se sustituye en silencio."""


# --------------------------------------------------------------------------
# Las puertas, una por una.
# Cada una devuelve (cierra: bool, hechos: dict).
# --------------------------------------------------------------------------
def puerta_S0(ficha, producto, ctx):
    """El cliente desactivó notificaciones."""
    opt_out = bool(ficha["nudges"]["opt_out"])
    return opt_out, {"opt_out": opt_out}


def puerta_S6(ficha, producto, ctx):
    """La fecha cae en zona de datos contaminada."""
    d = ficha["decision"]
    return bool(d.get("fecha_contaminada")), {"motivo_fecha": d.get("motivo_fecha")}


def puerta_S1(ficha, producto, ctx):
    """No hay señal reciente de intención en la pantalla acoplada."""
    s = ficha["decision"]["senales_por_nudge"][producto]
    cierra = s["momento"] not in MOMENTOS_CON_SENAL
    return cierra, {"momento": s["momento"], "horas_desde_senal": s["horas_desde_senal"],
                    "pantalla": s["pantalla_acoplada"]}


def puerta_S2(ficha, producto, ctx):
    """Ya se agotó el cupo de exposiciones del producto (cap = 2)."""
    t = ficha["nudges"]["por_tipo"][producto]
    cierra = t["exposiciones"] >= CAP_EXPOSICIONES
    return cierra, {"exposiciones": t["exposiciones"], "cap": CAP_EXPOSICIONES}


def puerta_S5(ficha, producto, ctx):
    """El cliente descartó este producto repetidamente. Implementada, no activa."""
    t = ficha["nudges"]["por_tipo"][producto]
    cierra = t["n_descartados"] >= UMBRAL_DESCARTES
    return cierra, {"n_descartados": t["n_descartados"], "umbral": UMBRAL_DESCARTES}


def puerta_S3(ficha, producto, ctx):
    """El cliente es frágil y el producto le haría daño."""
    fragil = bool(ficha["decision"]["es_fragil"])
    cierra = fragil and producto in PRODUCTOS_DANINOS_PARA_FRAGIL
    return cierra, {"es_fragil": fragil,
                    "motivo_fragilidad": ficha["decision"]["motivo_fragilidad"],
                    "utilizacion_pct": ficha["perfil"]["situacion_financiera"]["utilizacion_tarjeta_pct"],
                    "dias_en_negativo_90d": ficha["perfil"]["situacion_financiera"]["dias_en_negativo_90d"]}


def puerta_S7(ficha, producto, ctx):
    """El modelo no tiene confianza suficiente. Implementada, no activa."""
    sc = ctx["scores"].get(producto, {})
    conf = sc.get("confianza", sc.get("score"))
    umbral = ctx["umbral_confianza"]
    cierra = conf is None or float(conf) < umbral
    return cierra, {"confianza": conf, "umbral": umbral}


def puerta_S4(ficha, producto, ctx):
    """El valor esperado del aviso es negativo."""
    tabla = ctx["tabla_valor"]
    if producto not in tabla:
        raise ErrorDePolitica(f"la tabla de valor no trae {producto}")
    v = float(tabla[producto]["V"])
    return v <= 0.0, {"V": round(v, 4), "lambda": ctx["lambda"]}


PUERTAS = {S0: puerta_S0, S6: puerta_S6, S1: puerta_S1, S2: puerta_S2,
           S5: puerta_S5, S3: puerta_S3, S7: puerta_S7, S4: puerta_S4}


# --------------------------------------------------------------------------
def _orden_reporte(codigo):
    try:
        return PRIORIDAD_REPORTE.index(codigo)
    except ValueError:
        return len(PRIORIDAD_REPORTE)      # C0 va al final


def _prioridad_salud(producto):
    try:
        return PRIORIDAD_SALUD.index(producto)
    except ValueError:
        return len(PRIORIDAD_SALUD)


# --------------------------------------------------------------------------
def decide(ficha, fecha, scores, artefactos):
    """Devuelve {decision, ofertas[], silencios[], traza[8], modelo}.

    `ficha`      · salida de `Store.ficha(cid, asof)`
    `fecha`      · el asof, tal cual se pidió (solo viaja a la respuesta)
    `scores`     · {producto: {score, p_intencion, p_enganche, V, confianza}}
    `artefactos` · {tabla_valor, umbrales, cobertura, modelo}
    """
    tabla_valor = artefactos.get("tabla_valor")
    if not tabla_valor:
        raise ErrorDePolitica("falta la tabla de valor: la puerta S4 no se puede evaluar")

    ctx = {
        "scores": scores or {},
        "tabla_valor": tabla_valor,
        "lambda": artefactos.get("lambda"),
        "umbral_confianza": float((artefactos.get("umbrales") or {})
                                  .get("confianza_minima", UMBRAL_CONFIANZA_DEFECTO)),
    }

    silencios, candidatos = [], []
    # Por puerta: qué productos cerró (en orden de evaluación).
    cerradas = {c: [] for c in ORDEN_EVALUACION}

    # D15 · fuera de catálogo lleva su propio código, nunca "sin señal".
    for producto in TODOS_LOS_PRODUCTOS:
        if producto not in CATALOGO_DEMO:
            silencios.append({"producto": producto, "puerta": C0,
                              "hechos": {"catalogo": list(CATALOGO_DEMO)}})

    # S0 y S6 aplican al cliente entero. Se evalúan primero, que es justo su
    # lugar en el orden de evaluación, y cierran el catálogo completo.
    corte_de_cliente = None
    for codigo in [c for c in ORDEN_EVALUACION if c in PUERTAS_DE_CLIENTE]:
        if not PUERTAS_ACTIVAS[codigo]:
            continue
        cierra, hechos = PUERTAS[codigo](ficha, CATALOGO_DEMO[0], ctx)
        if cierra:
            corte_de_cliente = (codigo, hechos)
            break

    if corte_de_cliente is not None:
        codigo, hechos = corte_de_cliente
        for producto in CATALOGO_DEMO:
            silencios.append({"producto": producto, "puerta": codigo, "hechos": hechos})
            cerradas[codigo].append(producto)
        return armar_respuesta(candidatos, silencios, cerradas, ficha, fecha, artefactos)

    for producto in CATALOGO_DEMO:
        cerrado_por = None
        for codigo in ORDEN_EVALUACION:
            if codigo in PUERTAS_DE_CLIENTE:
                continue                      # ya evaluadas arriba, ninguna cerró
            if not PUERTAS_ACTIVAS[codigo]:
                PUERTAS[codigo](ficha, producto, ctx)   # se evalúa; no cierra
                continue
            cierra, hechos = PUERTAS[codigo](ficha, producto, ctx)
            if cierra:
                cerrado_por = (codigo, hechos)
                cerradas[codigo].append(producto)
                break

        if cerrado_por is None:
            sc = ctx["scores"].get(producto, {})
            candidatos.append({
                "producto": producto,
                "score": round(float(sc.get("score", 0.0)), 6),
                "p_intencion": sc.get("p_intencion"),
                "p_enganche": sc.get("p_enganche"),
                "V": float(tabla_valor[producto]["V"]),
                # De qué foto as-of salió `p_intencion`. Nunca puede ser
                # posterior al `asof` de la petición: eso sería fuga en caliente.
                "corte_features": sc.get("corte_features"),
                "surface": SUPERFICIE,
                "senal": ficha["decision"]["senales_por_nudge"][producto],
            })
        else:
            codigo, hechos = cerrado_por
            silencios.append({"producto": producto, "puerta": codigo, "hechos": hechos})

    return armar_respuesta(candidatos, silencios, cerradas, ficha, fecha, artefactos)


# --------------------------------------------------------------------------
def armar_respuesta(candidatos, silencios, cerradas, ficha, fecha, artefactos):
    """Ordena candidatos y silencios, arma la traza y decide sustitución."""
    # traza: siempre 8 filas, en orden de EVALUACIÓN.
    traza = []
    for codigo in ORDEN_EVALUACION:
        if not PUERTAS_ACTIVAS[codigo]:
            traza.append({"puerta": codigo, "resultado": "no_activa"})
            continue
        prods = cerradas.get(codigo, [])
        fila = {"puerta": codigo, "resultado": "cierra" if prods else "pasa"}
        if prods:
            fila["producto"] = prods[0]
            if len(prods) > 1:
                fila["productos"] = prods
        traza.append(fila)

    # silencios: en orden de PRIORIDAD DE REPORTE.
    silencios = sorted(silencios, key=lambda s: (_orden_reporte(s["puerta"]), s["producto"]))

    # candidatos: score desc, desempate por prioridad de salud.
    candidatos = sorted(candidatos, key=lambda c: (-c["score"], _prioridad_salud(c["producto"])))

    # Sustitución: S3 cerró un producto en el que el cliente SÍ reveló intención
    # y hay una alternativa sana con cupo. El veto no es censura, es sustitución.
    vetados_con_senal = [
        s["producto"] for s in silencios
        if s["puerta"] == S3
        and ficha["decision"]["senales_por_nudge"][s["producto"]]["momento"] in MOMENTOS_CON_SENAL
    ]
    sustituye_a = vetados_con_senal[0] if (vetados_con_senal and candidatos) else None

    if candidatos:
        decision = "sustitucion" if sustituye_a else "oferta"
    else:
        decision = "silencio"

    ofertas = []
    for i, c in enumerate(candidatos):
        o = dict(c)
        o["sustituye_a"] = sustituye_a if i == 0 else None
        ofertas.append(o)

    # El silencio que se le cuenta al usuario: el de mayor prioridad de reporte
    # entre los productos DEL CATÁLOGO (un C0 nunca es la razón principal).
    principal = next((s for s in silencios if s["puerta"] != C0), None)

    return {
        "customer_id": ficha["perfil"]["customer_id"],
        "asof": fecha,
        "decision": decision,
        "modelo": artefactos.get("modelo"),
        "ofertas": ofertas,
        "silencios": silencios,
        "traza": traza,
        "puerta_reportada": principal["puerta"] if principal else None,
        "sustituye_a": sustituye_a,
        "cobertura": artefactos.get("cobertura"),
    }


# --------------------------------------------------------------------------
def evaluar_masivo(store, asof, tabla_valor):
    """Las puertas S0/S1/S2/S3/S4/S6 sobre los 38,000 clientes, vectorizadas.

    Devuelve máscaras booleanas por cliente. Es la base del contador de
    cobertura y de los arquetipos del selector: ninguno de los dos se escribe
    a mano.
    """
    import numpy as np
    import pandas as pd

    asof = pd.Timestamp(asof)
    idx = store.cust.index
    n = len(idx)
    if ficha_fecha_contaminada(asof):
        return {"n": n, "idx": idx, "motivo": "S6_fecha"}

    # S0 · opt-out (cualquier aviso previo con la baja marcada)
    nu = store.nu.reset_index()
    nu = nu[nu.shown_ts < asof]
    opt_out = (nu.groupby("customer_id").opted_out_after.any()
               .reindex(idx).fillna(False).to_numpy().astype(bool))

    # S2 · exposiciones previas por tipo
    exp = (nu.groupby(["customer_id", "nudge_type"], observed=True).size()
             .unstack(fill_value=0).reindex(idx).fillna(0))

    # S1 · recencia en la pantalla acoplada
    ev = store.ev.reset_index()
    ev = ev[ev.event_ts < asof]
    ultima = (ev.groupby(["customer_id", "screen"], observed=True).event_ts.max()
                .unstack().reindex(idx))

    # S3 · fragilidad
    c = store.cust
    fragil = ((c.card_utilization_pct > FRAGIL_UTILIZACION_PCT)
              | (c.days_negative_90d >= FRAGIL_DIAS_NEGATIVOS)).to_numpy().astype(bool)

    hay_oferta = np.zeros(n, dtype=bool)
    hay_oferta_sin_S4 = np.zeros(n, dtype=bool)
    senal_alguna = np.zeros(n, dtype=bool)
    senal_fresca = np.zeros(n, dtype=bool)
    fatigado = np.zeros(n, dtype=bool)
    # Detalle por producto: el mismo recorrido de puertas que `decide()`, pero
    # sobre los 38,000 a la vez. Es lo que permite filtrar el selector por el
    # tipo de oferta que el sistema daría sin puntuar cliente a cliente.
    por_producto = {}
    for producto in CATALOGO_DEMO:
        valor_positivo = float(tabla_valor.get(producto, {}).get("V", 0.0)) > 0.0
        pantalla = PRODUCTO_A_PANTALLA[producto]
        if pantalla in ultima.columns:
            horas = (asof - ultima[pantalla]).dt.total_seconds().to_numpy() / 3600.0
        else:
            horas = np.full(n, np.inf)
        horas = np.where(np.isnan(horas), np.inf, horas)
        con_senal = horas <= UMBRAL_WARM_H            # on_time o warm
        senal_alguna |= con_senal
        senal_fresca |= horas <= UMBRAL_ON_TIME_H
        vistas = (exp[producto].to_numpy(dtype="float64") if producto in exp.columns
                  else np.zeros(n))
        con_cupo = vistas < CAP_EXPOSICIONES
        fatigado |= con_senal & ~con_cupo
        danino = producto in PRODUCTOS_DANINOS_PARA_FRAGIL
        sano = ~fragil if danino else np.ones(n, dtype=bool)
        pasa = (con_senal & con_cupo & sano & ~opt_out).astype(bool)
        hay_oferta_sin_S4 |= pasa
        if valor_positivo:
            hay_oferta |= pasa                         # S4 cierra V <= 0

        # La primera puerta que cierra, en ORDEN DE EVALUACIÓN. S5 y S7 no
        # están activas en el piloto y por eso no aparecen aquí: no cierran.
        cierra = np.full(n, None, dtype=object)
        for codigo, mascara in ((S4, np.full(n, not valor_positivo)),
                                (S3, ~sano),
                                (S2, ~con_cupo),
                                (S1, ~con_senal),
                                (S0, opt_out)):
            cierra = np.where(mascara, codigo, cierra)
        # momento, con el mismo criterio que `Store.ficha()`
        momento = np.where(horas <= UMBRAL_ON_TIME_H, MOMENTO_ON_TIME,
                   np.where(horas <= UMBRAL_WARM_H, MOMENTO_WARM,
                    np.where(np.isfinite(horas), MOMENTO_COLD, MOMENTO_NEVER)))
        por_producto[producto] = {
            "horas": horas, "momento": momento, "exposiciones": vistas.astype("int64"),
            "cierra": cierra, "pasa": (cierra == None).astype(bool),   # noqa: E711
        }

    return {"n": n, "idx": idx, "opt_out": opt_out, "fragil": fragil,
            "senal_alguna": senal_alguna, "senal_fresca": senal_fresca,
            "fatigado": fatigado, "hay_oferta": hay_oferta,
            "hay_oferta_sin_S4": hay_oferta_sin_S4,
            "por_producto": por_producto}


# --------------------------------------------------------------------------
def cobertura(store, asof, tabla_valor):
    """Las 8 puertas sobre los 38,000 clientes, vectorizadas.

    Devuelve el contador que la pantalla de silencio necesita
    (`{"pct_silencio": …, "pct_oferta": …}`). Se calcula al arranque desde los
    datos: el contador **nunca** se escribe a mano en el HTML.

    Referencia BA-9: 14.0 % de oferta ± 0.1 con el catálogo de 4.
    """
    import numpy as np
    import pandas as pd

    masas = evaluar_masivo(store, asof, tabla_valor)
    n = masas["n"]
    if masas.get("motivo") == "S6_fecha":
        return {"pct_silencio": 100.0, "pct_oferta": 0.0, "n_clientes": int(n),
                "asof": str(pd.Timestamp(asof).date()), "motivo": "S6_fecha"}
    hay_oferta = masas["hay_oferta"]
    hay_oferta_sin_S4 = masas["hay_oferta_sin_S4"]

    pct = round(100.0 * float(hay_oferta.mean()), 2)
    pct_sin_S4 = round(100.0 * float(hay_oferta_sin_S4.mean()), 2)
    return {"pct_oferta": pct, "pct_silencio": round(100.0 - pct, 2),
            # Referencia de BA-9 (14.0 % / 86.0 %): se midió con el catálogo de
            # 4 pero SIN la puerta S4. Se publican las dos para no maquillar.
            "pct_oferta_sin_S4": pct_sin_S4,
            "pct_silencio_sin_S4": round(100.0 - pct_sin_S4, 2),
            "n_clientes": int(n), "n_con_oferta": int(hay_oferta.sum()),
            "asof": str(pd.Timestamp(asof).date()), "catalogo": list(CATALOGO_DEMO)}


def ficha_fecha_contaminada(asof):
    from pipeline.ingesta import zona_contaminada
    contaminada, _ = zona_contaminada(asof)
    return contaminada
