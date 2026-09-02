"""ING-4 · El servicio. Un proceso, un puerto, sin paso de compilación.

Diez endpoints (`docs/arquitectura.md`). Ocho se definen aquí:

    GET  /                        la pantalla (Jinja2 + Alpine, sin compilación)
    GET  /api/contexto            cortes con SU cobertura, glosario, las 8 puertas
    GET  /api/explicacion?corte=  «Cómo funciona»: modelos, puertas con conteo,
                                  cadena de decisión y glosario ampliado
    GET  /api/clientes            selector, escenarios curados al frente
    GET  /api/clientes/{id}?asof= ficha as-of del cliente
    GET  /api/clientes/{id}/linea-tiempo   navegación y avisos en un mismo eje
    POST /api/decidir             la decisión + traza + razones
    GET  /health                  qué artefactos se cargaron y en qué nivel corre

y dos llegan montadas desde `app/rutas_dashboard.py`:

    GET  /dashboard               el dashboard general, pintado en el servidor
    GET  /api/dashboard           los mismos 9 bloques, en JSON

Tres reglas que no se negocian:

1. **Todo se carga en el `lifespan`.** Los 1.7 M de filas, la escalera de
   scoring, las plantillas de razones, los casos curados y el contador de
   cobertura. Por petición no se lee un solo archivo.
2. **Cualquier excepción devuelve silencio con HTTP 200.** El modo degradado es
   coherente con la tesis del producto; un 500 se ve como una app rota.
3. **Nada de valores por defecto silenciosos.** Si falta un artefacto, el nivel
   se declara caído con el motivo escrito y `/health` lo publica.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__ in (None, ""):                                   # pragma: no cover
    import sys
    sys.path.insert(0, RAIZ)

from app import explicacion, formato                                 # noqa: E402
from app.panorama import (                                             # noqa: E402
    MIN_AVISOS_POR_EXPOSICION,
    SILENCIO,
    Panorama,
)
from app.razones import (                                              # noqa: E402
    ETIQUETA_BOTON,
    MOMENTO_ES,
    PUERTA_DESC,
    PUERTA_ES,
    RESULTADO_DESC,
    TITULO,
    Razones,
    glosario,
)
from app.scoring import (                                              # noqa: E402
    ARTEFACTOS,
    ARTIFACTS,
    Escalera,
    corte_vigente,
    cortes_disponibles,
    fecha_de,
)
from pipeline import politica                                          # noqa: E402
from pipeline.ingesta import Store, registrar_evidencia                # noqa: E402
from pipeline.mapas import (                                           # noqa: E402
    CAP_EXPOSICIONES,
    CATALOGO_DEMO,
    CORTE_DEMO,
    TODOS_LOS_PRODUCTOS,
    UMBRAL_ON_TIME_H,
    UMBRAL_WARM_H,
)

RUTA_DATOS = os.path.join(RAIZ, "data")
RUTA_CASOS = os.path.join(RAIZ, "pipeline", "artifacts", "casos_ejemplo.json")
RUTA_PLANTILLAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
RUTA_ESTATICOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

HORA_DEMO = "T12:00:00"
ASOF_DEMO = CORTE_DEMO + HORA_DEMO

# La cobertura depende del `asof`, no solo del corte: a las 00:00 y a las 12:00
# del mismo día la señal tiene distinta edad. Se precalculan en el arranque las
# que el demo usa (los 5 cortes y los 9 escenarios) y el resto se cachea con
# tope, para que un `asof` arbitrario no pueda hacer crecer la memoria.
MAX_COBERTURAS_CACHEADAS = 64

# Ventana por defecto de la línea del tiempo, y cuánto se dibuja **después** del
# corte para que se vea la zona en la que el sistema no puede mirar.
VENTANA_LINEA_DIAS = 14
MARGEN_POSTERIOR = 0.15

# La respuesta del modo degradado. Es un contrato, no un mensaje de error.
SILENCIO_DEGRADADO = {
    "decision": "silencio",
    "razon_silencio": "El sistema no pudo evaluar este caso con confianza.",
    "modelo": "degradado",
}


def _degradado(detalle=None, customer_id=None, asof=None):
    """Silencio con HTTP 200. El detalle viaja para depurar, nunca oculto."""
    cuerpo = dict(SILENCIO_DEGRADADO)
    cuerpo["customer_id"] = customer_id
    cuerpo["asof"] = asof
    cuerpo["ofertas"] = []
    cuerpo["silencios"] = []
    cuerpo["traza"] = [{"puerta": c, "resultado": "no_evaluada"}
                       for c in politica.ORDEN_EVALUACION]
    cuerpo["puerta_reportada"] = None
    cuerpo["encabezado"] = {"titulo": "El sistema no pudo evaluar este caso",
                            "texto": SILENCIO_DEGRADADO["razon_silencio"]}
    if detalle:
        cuerpo["detalle_tecnico"] = str(detalle)[:500]
    return JSONResponse(status_code=200, content=cuerpo)


# ==========================================================================
# Arranque
# ==========================================================================
def _leer_artefacto_json(clave):
    """Lee un artefacto JSON o dice **por qué** no pudo. Sin valores por defecto."""
    ruta = os.path.join(ARTIFACTS, ARTEFACTOS[clave])
    if not os.path.exists(ruta):
        return None, f"falta {ARTEFACTOS[clave]}"
    try:
        with open(ruta, encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as e:                                       # pragma: no cover
        return None, f"{type(e).__name__}: {e}"


def _inventario_artefactos():
    """Los nombres de `docs/arquitectura.md` son ley. Aquí se dice cuáles están."""
    inv = {}
    for clave, nombre in ARTEFACTOS.items():
        ruta = os.path.join(ARTIFACTS, nombre)
        existe = os.path.exists(ruta)
        inv[nombre] = {"presente": existe,
                       "bytes": os.path.getsize(ruta) if existe else None}
    feats = f"features_asof_{CORTE_DEMO}.parquet"
    ruta = os.path.join(ARTIFACTS, feats)
    inv[feats] = {"presente": os.path.exists(ruta),
                  "bytes": os.path.getsize(ruta) if os.path.exists(ruta) else None}
    return inv


def cargar_casos():
    """Los 9 escenarios curados. Sin ellos el selector sería aleatorio (ING-6)."""
    if not os.path.exists(RUTA_CASOS):
        raise FileNotFoundError(
            f"faltan los escenarios curados en {RUTA_CASOS}: el selector no puede "
            f"ser aleatorio (el 82.84 % de los clientes no tiene eventos en 24 h "
            f"al corte del demo)")
    with open(RUTA_CASOS, encoding="utf-8") as fh:
        bruto = json.load(fh)
    casos = []
    for c in bruto["casos"]:
        # El `asof` es el que quedó registrado en la ficha del caso, no una hora
        # inventada: los 9 escenarios se verificaron a esa marca exacta y con
        # otra hora la señal envejece y el guion deja de cuadrar.
        asof = str(c["ficha"]["decision"]["asof"]).replace(" ", "T")
        casos.append({
            "customer_id": int(c["customer_id"]),
            "clave": c["clave"],
            "titulo": c["titulo"],
            "narrativa": c.get("narrativa"),
            "corte": c.get("corte", CORTE_DEMO),
            "asof": asof,
            "esperado": {
                "enviar": c["decision"].get("enviar"),
                "nudge_type": c["decision"].get("nudge_type"),
                "razon_silencio": c["decision"].get("razon_silencio"),
                "sustituye_a": c["decision"].get("sustituye_a"),
            },
            "curado": True,
        })
    return {"casos": casos, "cortes": bruto.get("cortes", {}),
            "generado_por": bruto.get("generado_por")}


@asynccontextmanager
async def lifespan(app: FastAPI):
    t0 = time.perf_counter()
    app.state.errores_arranque = []

    app.state.store = Store.cargar(RUTA_DATOS)
    app.state.escalera = Escalera.cargar(app.state.store, corte=CORTE_DEMO)
    app.state.razones = Razones.cargar()
    app.state.casos = cargar_casos()
    app.state.metadata, app.state.motivo_metadata = _leer_artefacto_json("metadata")
    app.state.umbrales, app.state.motivo_umbrales = _leer_artefacto_json("umbrales")
    app.state.artefactos = _inventario_artefactos()

    # El contador del silencio se calcula aquí, sobre los 38,000 clientes.
    # NUNCA se escribe a mano en el HTML (ING-6).
    app.state.cobertura = politica.cobertura(
        app.state.store, ASOF_DEMO, app.state.escalera.tabla_valor)

    # Los 5 cortes con foto de features. El selector de la pantalla sale de
    # aquí, no de una lista escrita a mano.
    app.state.cortes = cortes_disponibles()

    # El panorama: por corte, la cobertura, la tasa base observada de cada
    # acción, la distribución completa de `p_intencion` y de `score` sobre los
    # 38,000 y qué ofrecería el sistema a cada uno. Es lo que convierte un
    # `0.03007` en «5.78 veces la tasa base, percentil 98.40».
    app.state.panorama = Panorama.cargar(
        app.state.store, app.state.escalera, app.state.cortes)

    # Caché de coberturas por `asof`. Se ceba con lo que el demo va a pedir de
    # verdad: los 5 cortes a mediodía y el `asof` exacto de cada escenario.
    app.state.coberturas = {ASOF_DEMO: app.state.cobertura}
    for corte in app.state.cortes:
        vista = app.state.panorama.de(corte)
        app.state.coberturas.setdefault(
            corte + HORA_DEMO,
            vista.cobertura if vista else politica.cobertura(
                app.state.store, corte + HORA_DEMO, app.state.escalera.tabla_valor))
    for caso in app.state.casos["casos"]:
        if caso["asof"] not in app.state.coberturas:
            app.state.coberturas[caso["asof"]] = politica.cobertura(
                app.state.store, caso["asof"], app.state.escalera.tabla_valor)

    # El glosario se arma con las cifras que de verdad rigen la ejecución, no
    # con constantes copiadas en la plantilla.
    app.state.glosario = glosario(
        CORTE_DEMO, int(len(app.state.store.cust)), CAP_EXPOSICIONES,
        UMBRAL_ON_TIME_H, UMBRAL_WARM_H, app.state.escalera.lmbda)

    # La pestaña «Cómo funciona» se arma con los mismos conteos del panorama.
    # La del corte del demo se deja hecha al arranque —es la que se abre— y el
    # resto se cachea por corte la primera vez que alguien la pide.
    app.state.explicaciones = {CORTE_DEMO: explicacion.construir(app.state, CORTE_DEMO)}

    app.state.arranque_s = round(time.perf_counter() - t0, 3)
    registrar_evidencia("app.arranque", 0, len(app.state.casos["casos"]), t0,
                        nivel_activo=app.state.escalera.nivel_activo,
                        pct_silencio=app.state.cobertura["pct_silencio"])
    yield
    app.state.store = None


app = FastAPI(title="nu-moments", version="1.0", lifespan=lifespan)

if os.path.isdir(RUTA_ESTATICOS):
    app.mount("/static", StaticFiles(directory=RUTA_ESTATICOS), name="static")
plantillas = Jinja2Templates(directory=RUTA_PLANTILLAS)

# El dashboard vive en su propio módulo y se monta aquí: `GET /dashboard` y
# `GET /api/dashboard`. Si su artefacto no se puede construir, el servicio
# arranca igual y la pestaña «Panorama» devuelve 404 en vez de tumbar el demo.
try:
    from app.rutas_dashboard import router as router_dashboard

    app.include_router(router_dashboard)
    DASHBOARD_MONTADO, DASHBOARD_MOTIVO = True, None
except Exception as exc:  # pragma: no cover - se reporta en /health
    DASHBOARD_MONTADO, DASHBOARD_MOTIVO = False, f"{type(exc).__name__}: {exc}"


# ==========================================================================
# Silencio con HTTP 200 · red de seguridad global
# ==========================================================================
@app.middleware("http")
async def silencio_en_vez_de_500(request: Request, call_next):
    """Ninguna excepción sale como 500. El modo degradado es una decisión."""
    try:
        return await call_next(request)
    except Exception as e:                                       # pragma: no cover
        traceback.print_exc()
        return _degradado(f"{type(e).__name__}: {e}")


@app.exception_handler(Exception)
async def cualquier_error(request: Request, exc: Exception):     # pragma: no cover
    return _degradado(f"{type(exc).__name__}: {exc}")


# ==========================================================================
# Helpers de decisión
# ==========================================================================
def _asof(valor):
    """`asof` explícito o el corte del demo. Siempre viaja de vuelta resuelto."""
    if not valor:
        return ASOF_DEMO
    valor = str(valor).strip()
    return valor + HORA_DEMO if len(valor) == 10 else valor


def _cobertura_para(estado, asof):
    """La cobertura **de ese `asof`**, no la del corte del demo disfrazada.

    Los cinco cortes y los nueve escenarios ya están precalculados desde el
    arranque; cualquier otra fecha se calcula una vez y se cachea con tope.
    """
    cache = estado.coberturas
    if asof in cache:
        return cache[asof]
    cob = politica.cobertura(estado.store, asof, estado.escalera.tabla_valor)
    if len(cache) < MAX_COBERTURAS_CACHEADAS:
        cache[asof] = cob
    return cob


def _vista_de(estado, asof, corte_features=None):
    """La vista poblacional contra la que se comparan los números de la oferta.

    Se usa **el mismo corte de features con el que se puntuó**, que el propio
    score publica en `corte_features`. Comparar contra otro día sería inventar
    el percentil.
    """
    corte = corte_features or corte_vigente(fecha_de(asof), estado.panorama.cortes)
    return estado.panorama.de(corte) if corte else None


def _factor(clave, valor, glos, *, unidad="porcentaje", como_se_lee=None,
            poblacion=None, referencia=None, texto=None):
    """Un número de la pantalla con todo lo que hace falta para leerlo."""
    g = glos.get(clave, {})
    if texto is None:
        texto = (formato.pct(valor, de_fraccion=True) if unidad == "porcentaje"
                 else formato.dias(valor))
    return {
        "clave": clave,
        "titulo": g.get("titulo", clave),
        "valor": valor,
        "texto": texto,
        "unidad": unidad,
        "que_mide": g.get("texto"),
        "poblacion": poblacion,
        "como_se_lee": como_se_lee,
        "referencia": referencia,
    }


def _miles(n):
    """`38000` → `'38 000'`. Espacio fino, como el resto de la pantalla."""
    return f"{int(n):,}".replace(",", " ")


# ==========================================================================
# Las gráficas del «por qué». Todo sale de `app/panorama.py` y de la ficha:
# ni un número se escribe a mano, ni se estima uno que no esté contado.
# ==========================================================================
def _grafica_poblacion(estado, producto, vista):
    """Dónde cae este cliente en el reparto de los 38,000 de ese corte.

    Responde la pregunta literal —«¿por qué él y no otro?»— con el conteo:
    cuántos reciben esta misma oferta, cuántos reciben otra y cuántos se quedan
    en silencio, con el segmento del cliente marcado.
    """
    conteo = vista.conteo_por_oferta()
    n_total = sum(conteo.values()) or 1
    orden = list(CATALOGO_DEMO) + [SILENCIO]
    segmentos = []
    for clave in orden:
        n = int(conteo.get(clave, 0))
        if not n:
            continue
        segmentos.append({
            "clave": clave,
            "titulo": "Silencio" if clave == SILENCIO else TITULO.get(clave, clave),
            "n": n, "n_texto": _miles(n),
            "pct": round(100.0 * n / n_total, 2),
            "pct_texto": formato.pct(100.0 * n / n_total),
            "es_del_cliente": clave == producto,
        })
    razones = vista.conteo_por_razon()
    por_razon = sorted(
        ({"puerta": p, "etiqueta": PUERTA_ES.get(p, p), "n": int(n), "n_texto": _miles(n),
          "pct": round(100.0 * int(n) / n_total, 2),
          "pct_texto": formato.pct(100.0 * int(n) / n_total)}
         for p, n in razones.items()),
        key=lambda r: -r["n"])
    mio = next((s for s in segmentos if s["es_del_cliente"]), None)
    return {
        "titulo": "Su lugar entre los 38 000",
        "corte": vista.corte,
        "n_total": n_total, "n_total_texto": _miles(n_total),
        "segmentos": segmentos,
        "silencio_por_razon": por_razon,
        "alternativa": (
            f"De los {_miles(n_total)} clientes evaluados al corte {vista.corte}, "
            f"{mio['n_texto']} ({mio['pct_texto']}) reciben esta misma oferta y el resto no."
            if mio else None),
    }


def _grafica_distribucion(producto, p_int, vista, customer_id=None):
    """El histograma de `p_intencion` de los 38,000, con la posición del cliente.

    El eje es logarítmico porque la distribución lo pide (`app/panorama.py`
    explica por qué); las marcas son la mediana de la población, la tasa base
    observada de la acción y el cliente.

    El eje **no** es el percentil: la marca del cliente cae a la altura de su
    probabilidad en escala log, que es otra cosa. Por eso se publican las dos
    lecturas (`pos_pct_cliente` y `percentil`) y la plantilla las enseña juntas:
    debajo hay una regla donde la posición sí es el percentil, y las dos franjas
    no se pueden leer con la misma regla.
    """
    h = vista.histograma_intencion(producto, p_int)
    pos = vista.posicion_intencion(producto, p_int, customer_id)
    if h is None or pos is None:
        return None
    etiquetas = {"mediana": "mediana de los 38 000",
                 "tasa_base": "tasa base observada",
                 "cliente": "este cliente"}
    for m in h["marcas"]:
        m["etiqueta"] = etiquetas.get(m["clave"], m["clave"])
        m["texto"] = formato.pct(m["valor"], de_fraccion=True)
    # Dónde cae la marca del cliente **sobre el eje**, que no es su percentil.
    pos_cliente = next((m["pos_pct"] for m in h["marcas"] if m["clave"] == "cliente"), None)
    return {
        "titulo": "Dónde cae en la distribución",
        "eje": "probabilidad de intención (escala logarítmica)",
        "eje_es_percentil": False,
        "pos_pct_cliente": pos_cliente,
        "pos_pct_cliente_texto": formato.pct(pos_cliente),
        # La frase que impide leer esta franja como si fuera la regla del
        # percentil que va justo debajo. Los dos números salen del cálculo.
        "nota_escala": (
            f"La marca cae al {formato.pct(pos_cliente)} del ancho porque el eje mide "
            f"probabilidad en escala logarítmica; su percentil es "
            f"{formato.pct(pos['percentil'])}. No son la misma escala."
            if pos_cliente is not None else None),
        "histograma": h,
        "valor": p_int, "valor_texto": formato.pct(p_int, de_fraccion=True),
        "percentil": pos["percentil"], "percentil_texto": formato.pct(pos["percentil"]),
        "n_total": pos["n_total"], "n_total_texto": _miles(pos["n_total"]),
        "n_encima": pos["n_encima"], "n_encima_texto": _miles(pos["n_encima"]),
        "minimo_texto": formato.pct(h["minimo"], de_fraccion=True),
        "maximo_texto": formato.pct(h["maximo"], de_fraccion=True),
        "alternativa": (
            f"Su probabilidad de intención es {formato.pct(p_int, de_fraccion=True)}: "
            f"percentil {formato.pct(pos['percentil'])} de los {_miles(pos['n_total'])} "
            f"clientes evaluados a este corte. Solo {_miles(pos['n_encima'])} tienen una "
            f"probabilidad más alta. El eje del dibujo es logarítmico: la posición de la "
            f"marca no es el percentil."),
    }


def _barra_contra_base(clave, titulo, valor, base, veces, glos):
    """La barra del cliente contra la barra de la población, con el múltiplo."""
    if valor is None or base is None:
        return None
    tope = max(float(valor), float(base)) or 1.0
    return {
        "clave": clave, "titulo": titulo,
        "que_mide": glos.get(clave, {}).get("texto"),
        "cliente": {"valor": valor, "texto": formato.pct(valor, de_fraccion=True),
                    "ancho_pct": round(100.0 * float(valor) / tope, 2)},
        "poblacion": {"valor": base, "texto": formato.pct(base, de_fraccion=True),
                      "ancho_pct": round(100.0 * float(base) / tope, 2)},
        "veces": veces, "veces_texto": formato.veces(veces),
        "alternativa": (
            f"{titulo}: este cliente {formato.pct(valor, de_fraccion=True)} frente a "
            f"{formato.pct(base, de_fraccion=True)} de la población, "
            f"{formato.veces(veces)} la tasa base."),
    }


def _grafica_recencia(senal):
    """La recencia de la señal situada en los umbrales que usa la política.

    El eje es lineal y va de 0 a `UMBRAL_WARM_H + UMBRAL_ON_TIME_H` horas, así
    que las tres zonas —fresca, tibia, fría— caen exactamente donde están los
    umbrales de `pipeline/politica.py`, no donde quedaría bonito.
    """
    dominio = float(UMBRAL_WARM_H + UMBRAL_ON_TIME_H)
    zonas = [
        ("on_time", 0.0, float(UMBRAL_ON_TIME_H)),
        ("warm", float(UMBRAL_ON_TIME_H), float(UMBRAL_WARM_H)),
        ("cold", float(UMBRAL_WARM_H), dominio),
    ]
    horas = senal.get("horas_desde_senal")
    momento = senal.get("momento")
    m = MOMENTO_ES.get(momento, {})
    return {
        "titulo": "Cuándo fue la señal",
        "dominio_h": dominio,
        "zonas": [{"clave": c, "etiqueta": MOMENTO_ES.get(c, {}).get("etiqueta", c),
                   "desde_h": d, "hasta_h": ha,
                   "izq_pct": round(100.0 * d / dominio, 2),
                   "ancho_pct": round(100.0 * (ha - d) / dominio, 2)}
                  for c, d, ha in zonas],
        "umbral_on_time_h": UMBRAL_ON_TIME_H,
        "umbral_warm_h": UMBRAL_WARM_H,
        "horas": horas,
        "horas_texto": (f"{float(horas):.1f} h" if horas is not None else formato.GUION),
        "pos_pct": (round(100.0 * min(float(horas), dominio) / dominio, 2)
                    if horas is not None else None),
        "fuera_de_eje": horas is not None and float(horas) > dominio,
        "momento": momento,
        "momento_etiqueta": m.get("etiqueta", momento),
        "momento_texto": m.get("texto"),
        "pantalla": senal.get("pantalla_acoplada"),
        "alternativa": (
            f"Entró a {senal.get('pantalla_acoplada')} hace {float(horas):.1f} horas: "
            f"señal {m.get('etiqueta', momento)}, dentro del umbral de "
            f"{UMBRAL_ON_TIME_H} h que la política llama fresca."
            if horas is not None and float(horas) <= UMBRAL_ON_TIME_H else
            f"Entró a {senal.get('pantalla_acoplada')} hace {float(horas):.1f} horas: "
            f"señal {m.get('etiqueta', momento)}." if horas is not None else
            f"No hay registro de que haya entrado a {senal.get('pantalla_acoplada')}."),
    }


def _grafica_cupo(exposiciones, senal, vista):
    """Sus exposiciones frente al cupo, y la curva de fatiga que fija ese cupo."""
    usadas = int(exposiciones)
    siguiente = int(senal.get("exposure_no_siguiente") or usadas + 1)
    curva = [dict(p) for p in (vista.curva_fatiga if vista else [])]
    tope = max([p["enganche"] for p in curva], default=0.0) or 1.0
    for p in curva:
        p["enganche_texto"] = formato.pct(p["enganche"], de_fraccion=True)
        p["baja_texto"] = formato.pct(p["baja"], de_fraccion=True)
        p["n_texto"] = _miles(p["n"])
        p["alto_pct"] = round(100.0 * p["enganche"] / tope, 2)
        p["es_del_cliente"] = p["exposure_no"] == siguiente
    mio = next((p for p in curva if p["es_del_cliente"]), None)
    return {
        "titulo": "Cuántas veces ya se le dijo",
        "exposiciones": usadas,
        "cap": CAP_EXPOSICIONES,
        "restante": max(0, CAP_EXPOSICIONES - usadas),
        "siguiente": siguiente,
        "casillas": [{"n": i + 1, "usada": i < usadas,
                      "es_la_siguiente": i + 1 == siguiente}
                     for i in range(CAP_EXPOSICIONES)],
        "curva": curva,
        "min_avisos_por_exposicion": MIN_AVISOS_POR_EXPOSICION,
        "alternativa": (
            f"Se le han mostrado {usadas} de {CAP_EXPOSICIONES} avisos de este tipo. "
            f"Este sería el número {siguiente}"
            + (f", y en los datos la exposición {siguiente} engancha "
               f"{mio['enganche_texto']} y provoca {mio['baja_texto']} de bajas."
               if mio else ".")),
    }


def _graficas(estado, oferta, ficha, vista):
    """Las cinco vistas del «por qué», todas alimentadas por el panorama."""
    if vista is None:
        return None
    glos = estado.glosario
    producto = oferta["producto"]
    p_int, p_eng = oferta.get("p_intencion"), oferta.get("p_enganche")
    senal = oferta.get("senal") or {}
    expuestas = ficha["nudges"]["por_tipo"].get(producto, {}).get("exposiciones", 0)

    contra_base = [b for b in (
        _barra_contra_base("p_intencion", glos["p_intencion"]["titulo"], p_int,
                           vista.tasa_base_intencion.get(producto),
                           vista.veces_sobre_base(producto, p_int), glos),
        _barra_contra_base("p_enganche", glos["p_enganche"]["titulo"], p_eng,
                           vista.tasa_base_enganche.get(producto),
                           vista.veces_sobre_base_enganche(producto, p_eng), glos),
    ) if b]

    return {
        "corte": vista.corte,
        "poblacion": _grafica_poblacion(estado, producto, vista),
        "distribucion": _grafica_distribucion(
            producto, p_int, vista, ficha["perfil"]["customer_id"]),
        "contra_base": {
            "titulo": "Su probabilidad contra la tasa base",
            "barras": contra_base,
        },
        "recencia": _grafica_recencia(senal),
        "cupo": _grafica_cupo(expuestas, senal, vista),
    }


def _explicar_oferta(estado, oferta, ficha, vista, n_clientes):
    """Los tres factores del score, cada uno en su unidad natural y comparado.

    `0.03007` no se le enseña a nadie sin esto: qué probabilidad hay de que
    quiera la acción, qué probabilidad hay de que responda al aviso, cuántos
    días de descubierto le ahorra, y contra qué se compara cada cifra.
    """
    glos = estado.glosario
    producto = oferta["producto"]
    p_int = oferta.get("p_intencion")
    p_eng = oferta.get("p_enganche")
    v = oferta.get("V")
    score = oferta.get("score")

    base_int = vista.tasa_base_intencion.get(producto) if vista else None
    base_eng = vista.tasa_base_enganche.get(producto) if vista else None
    veces_int = vista.veces_sobre_base(producto, p_int) if vista else None
    cid = ficha["perfil"]["customer_id"]
    pct_int = vista.percentil_intencion(producto, p_int, cid) if vista else None
    veces_eng = vista.veces_sobre_base_enganche(producto, p_eng) if vista else None
    pos_score = vista.posicion_score(producto, score, cid) if vista else None
    pct_score = pos_score["percentil"] if pos_score else None
    poblacion = (f"los {n_clientes:,} clientes evaluados al corte {vista.corte}".replace(",", " ")
                 if vista else None)

    factores = [
        _factor("p_intencion", p_int, glos, poblacion=poblacion,
                como_se_lee=(
                    f"De cada 100 clientes así, {formato.pct_num(p_int, True):.2f} harían esta "
                    f"acción en 7 días." if p_int is not None else None),
                referencia={
                    "tasa_base": base_int,
                    "tasa_base_texto": formato.pct(base_int, de_fraccion=True),
                    "veces": veces_int, "veces_texto": formato.veces(veces_int),
                    "percentil": pct_int,
                    "percentil_texto": formato.pct(pct_int),
                    "titulo": glos["tasa_base"]["titulo"],
                    "texto": glos["tasa_base"]["texto"],
                }),
        _factor("p_enganche", p_eng, glos, poblacion=poblacion,
                como_se_lee=(
                    f"De cada 100 avisos así, {formato.pct_num(p_eng, True):.2f} se enganchan."
                    if p_eng is not None else None),
                referencia={
                    "tasa_base": base_eng,
                    "tasa_base_texto": formato.pct(base_eng, de_fraccion=True),
                    "veces": veces_eng, "veces_texto": formato.veces(veces_eng),
                    "percentil": None, "percentil_texto": formato.GUION,
                    "titulo": glos["tasa_base_enganche"]["titulo"],
                    "texto": glos["tasa_base_enganche"]["texto"],
                }),
        _factor("valor", v, glos, unidad="dias",
                poblacion="los avisos de este tipo que sí se engancharon, medidos a 90 días",
                como_se_lee=(
                    f"Un aviso de este tipo que engancha le ahorra {formato.dias(v)} de "
                    f"descubierto." if v is not None else None),
                referencia=None),
    ]

    resultado = _factor(
        "score", score, glos, unidad="dias",
        poblacion=poblacion,
        como_se_lee=(
            f"{formato.dias(score)} de descubierto evitados en promedio, contando ya que "
            f"quizá no quería la acción y que quizá no habría enganchado."
            if score is not None else None),
        referencia={
            "percentil": pct_score,
            "percentil_texto": formato.pct(pct_score),
            # Los dos conteos que respaldan el percentil: sin ellos la cifra no
            # se puede comprobar contando.
            "n_total": pos_score["n_total"] if pos_score else None,
            "n_encima": pos_score["n_encima"] if pos_score else None,
            "n_encima_texto": _miles(pos_score["n_encima"]) if pos_score else None,
            "titulo": glos["percentil"]["titulo"],
            "texto": glos["percentil"]["texto"],
        })
    resultado["horas"] = formato.horas_de_dias(score)
    resultado["formula"] = "score = p_intencion × p_enganche × V"

    return {"factores": factores, "resultado": resultado,
            "corte_comparacion": vista.corte if vista else None,
            # Las gráficas del «por qué». Si no hay vista poblacional van a
            # `None` y la pantalla lo dice, en vez de dibujar un eje inventado.
            "graficas": _graficas(estado, oferta, ficha, vista),
            "motivo_sin_comparacion": None if vista else (
                "no hay vista poblacional para este corte: se muestran los factores "
                "sin percentil ni gráficas en vez de inventar uno")}


def _decidir(estado, customer_id: int, asof: str):
    """El camino completo: ficha → scores → 8 puertas → razones."""
    ficha = estado.store.ficha(customer_id, asof)
    scores, nivel = estado.escalera.puntuar(ficha)
    cobertura = _cobertura_para(estado, asof)
    resp = politica.decide(ficha, asof, scores, {
        "tabla_valor": estado.escalera.tabla_valor,
        "umbrales": estado.umbrales or {},
        "lambda": estado.escalera.lmbda,
        "cobertura": cobertura,
        "modelo": nivel,
    })
    n_clientes = int(len(estado.store.cust))

    # --- ofertas: título, botón, la leyenda del porqué y los tres factores --
    for o in resp["ofertas"]:
        p = o["producto"]
        o["titulo"] = TITULO.get(p, p)
        o["etiqueta_boton"] = ETIQUETA_BOTON.get(p, "Ver")
        o["razon"] = estado.razones.oferta(ficha, o, sustituye_a=o.get("sustituye_a"))
        o["explicacion"] = _explicar_oferta(
            estado, o, ficha, _vista_de(estado, asof, o.get("corte_features")), n_clientes)

    # --- silencios: cada uno con su razón en lenguaje natural --------------
    for s in resp["silencios"]:
        s["producto_titulo"] = TITULO.get(s["producto"], s["producto"])
        s["puerta_etiqueta"] = PUERTA_ES.get(s["puerta"], s["puerta"])
        s["razon"] = estado.razones.silencio(ficha, s)
        s.update(_describir_puerta(s["puerta"]))

    # --- traza: las 8 puertas con nombre llano, qué comprueban y su estado --
    for i, fila in enumerate(resp["traza"], start=1):
        fila["etiqueta"] = PUERTA_ES.get(fila["puerta"], fila["puerta"])
        fila["orden"] = i
        fila.update(_describir_puerta(fila["puerta"]))
        desc = RESULTADO_DESC.get(fila["resultado"], {})
        fila["resultado_etiqueta"] = desc.get("etiqueta", fila["resultado"])
        fila["resultado_texto"] = desc.get("texto")

    # --- la pantalla de silencio es una pantalla diseñada (ING-6) ---------
    titulo, texto = estado.razones.encabezado_silencio(ficha, resp)
    resp["encabezado"] = {"titulo": titulo, "texto": texto}
    resp["cobertura"] = _cobertura_con_texto(cobertura)
    resp["senales"] = _senales_explicadas(ficha)
    resp["es_fragil"] = ficha["decision"]["es_fragil"]
    resp["catalogo"] = list(CATALOGO_DEMO)
    resp["fuera_de_catalogo"] = [p for p in TODOS_LOS_PRODUCTOS if p not in CATALOGO_DEMO]
    resp["corte"] = fecha_de(asof)
    return resp


def _describir_puerta(codigo):
    """Nombre llano, qué comprueba y si la puerta cierra en el piloto."""
    d = PUERTA_DESC.get(codigo, {})
    return {
        "puerta_nombre": d.get("nombre", PUERTA_ES.get(codigo, codigo)),
        "puerta_comprueba": d.get("comprueba"),
        "puerta_cierra_si": d.get("cierra_si"),
        "puerta_activa": politica.PUERTAS_ACTIVAS.get(codigo, True),
    }


def _senales_explicadas(ficha):
    """Las señales de la ficha, con el estado traducido y el cupo explicado."""
    out = {}
    for producto, s in ficha["decision"]["senales_por_nudge"].items():
        m = MOMENTO_ES.get(s["momento"], {})
        t = ficha["nudges"]["por_tipo"][producto]
        out[producto] = dict(s)
        out[producto].update({
            "momento_etiqueta": m.get("etiqueta", s["momento"]),
            "momento_texto": m.get("texto"),
            "exposiciones": t["exposiciones"],
            "cupo": CAP_EXPOSICIONES,
            "cupo_restante": t["cupo_restante"],
            "cupo_texto": f"{t['exposiciones']} de {CAP_EXPOSICIONES}",
        })
    return out


def _cobertura_con_texto(cob):
    """La misma cobertura, con cada porcentaje también escrito con dos decimales."""
    if not cob:
        return cob
    out = dict(cob)
    for clave in [k for k in cob if k.startswith("pct_")]:
        out[clave + "_texto"] = formato.pct(cob[clave])
    return out


# ==========================================================================
# Endpoints
# ==========================================================================
@app.get("/", response_class=HTMLResponse)
def pantalla(request: Request):
    e = request.app.state
    return plantillas.TemplateResponse(request, "index.html", {
        "casos": e.casos["casos"],
        "cobertura": e.cobertura,
        "nivel_activo": e.escalera.nivel_activo,
        "corte_demo": CORTE_DEMO,
        "asof_demo": ASOF_DEMO,
    })


@app.get("/api/contexto")
def contexto(request: Request):
    """Todo lo que la pantalla necesita para explicarse, en una sola petición.

    Los cortes disponibles con **su** cobertura (que cambia con el corte y por
    eso no se puede fijar), el glosario, las 8 puertas en lenguaje llano, los
    estados de la señal y los conteos con los que se filtra el selector.
    """
    e = request.app.state
    cortes = []
    for corte in e.cortes:
        vista = e.panorama.de(corte)
        cob = _cobertura_con_texto(
            vista.cobertura if vista else _cobertura_para(e, corte + HORA_DEMO))
        cortes.append({
            "corte": corte,
            "asof": corte + HORA_DEMO,
            "es_demo": corte == CORTE_DEMO,
            "cobertura": cob,
            "conteo_por_oferta": vista.conteo_por_oferta() if vista else None,
            "conteo_por_razon": vista.conteo_por_razon() if vista else None,
            "motivo": e.panorama.motivos.get(corte),
        })
    return {
        "corte_demo": CORTE_DEMO,
        "cortes": cortes,
        "glosario": e.glosario,
        "puertas": [{"puerta": c, "orden": i,
                     "etiqueta": PUERTA_ES.get(c, c),
                     "activa": politica.PUERTAS_ACTIVAS.get(c, True),
                     **_describir_puerta(c)}
                    for i, c in enumerate(politica.ORDEN_EVALUACION, start=1)],
        "resultados": RESULTADO_DESC,
        "momentos": MOMENTO_ES,
        "catalogo": list(CATALOGO_DEMO),
        "titulos": {p: TITULO.get(p, p) for p in TODOS_LOS_PRODUCTOS},
        "silencio": SILENCIO,
        "cap_exposiciones": CAP_EXPOSICIONES,
        "umbral_on_time_h": UMBRAL_ON_TIME_H,
        "umbral_warm_h": UMBRAL_WARM_H,
        "n_clientes": int(len(e.store.cust)),
    }


@app.get("/api/explicacion")
def explicacion_como_funciona(request: Request,
                              corte: str | None = Query(
                                  None, description="corte del panorama")):
    """La pestaña «Cómo funciona», con las cifras del corte que se mire.

    Es la misma información que produce la decisión, contada para alguien que no
    ha visto nunca el dataset: los tres modelos en su orden, las 8 puertas con
    **cuánta gente silencia cada una en este corte**, la cadena hasta los cuatro
    resultados y el glosario. Ni un número está escrito en la plantilla: si el
    corte cambia, cambian todos (`app/explicacion.py`).
    """
    e = request.app.state
    clave = corte or CORTE_DEMO
    if clave not in e.explicaciones:
        if len(e.explicaciones) >= MAX_COBERTURAS_CACHEADAS:     # pragma: no cover
            return explicacion.construir(e, clave)
        e.explicaciones[clave] = explicacion.construir(e, clave)
    return e.explicaciones[clave]


@app.get("/api/clientes")
def listar_clientes(request: Request,
                    q: str | None = Query(None, description="búsqueda libre por id"),
                    limite: int = Query(25, ge=1, le=200),
                    corte: str | None = Query(None, description="corte del panorama"),
                    oferta: str | None = Query(
                        None, description="producto que el sistema daría, o 'silencio'"),
                    razon: str | None = Query(
                        None, description="código de puerta del silencio (S0_opt_out…)")):
    """Escenarios curados al frente; búsqueda libre como secundaria (ING-6).

    La búsqueda libre se puede filtrar por **el tipo de oferta que el sistema le
    daría** al cliente y, cuando es silencio, por la puerta que se lo cerró. El
    filtro no adivina: se resuelve contra el panorama, que corre las mismas
    puertas y el mismo score sobre los 38,000 de una sola pasada.
    """
    e = request.app.state
    curados = e.casos["casos"]
    ids_curados = {c["customer_id"] for c in curados}
    texto = str(q).strip() if q else ""

    if texto:
        coincide = [c for c in curados if texto in str(c["customer_id"])
                    or texto.lower() in c["titulo"].lower()
                    or texto.lower() in c["clave"].lower()]
    else:
        coincide = curados

    corte_panorama = corte or CORTE_DEMO
    vista = e.panorama.de(corte_panorama)
    filtrando = bool(oferta or razon)
    motivo_filtro = None

    if filtrando and vista is None:
        candidatos, motivo_filtro = [], (
            e.panorama.motivos.get(corte_panorama)
            or f"no hay panorama para el corte {corte_panorama}")
    elif filtrando:
        candidatos = [int(cid) for cid in vista.clientes(tipo=oferta, razon=razon)]
    else:
        candidatos = [int(cid) for cid in e.store.cust.index]

    otros = []
    for cid in candidatos:
        if cid in ids_curados:
            continue
        if texto and texto not in str(cid):
            continue
        otros.append(cid)
        if len(otros) >= limite:
            break

    asof_libre = (corte_panorama + HORA_DEMO) if corte else ASOF_DEMO
    libres = []
    for cid in otros:
        c = e.store.cust.loc[cid]
        fila = {"customer_id": int(cid), "curado": False,
                "estado": str(c.state), "banda_ingreso": str(c.income_band),
                "utilizacion_tarjeta_pct": float(c.card_utilization_pct),
                "utilizacion_tarjeta_texto": formato.pct(c.card_utilization_pct),
                "asof": asof_libre}
        if vista is not None:
            i = vista.idx.get_loc(cid)
            fila["oferta_prevista"] = str(vista.oferta[i])
            fila["razon_silencio"] = (str(vista.puerta[i])
                                      if vista.oferta[i] == SILENCIO else None)
            fila["oferta_titulo"] = (TITULO.get(fila["oferta_prevista"])
                                     if fila["oferta_prevista"] != SILENCIO else "Silencio")
        libres.append(fila)

    return {"n_curados": len(coincide), "n_libres": len(libres),
            "consulta": q, "corte_demo": CORTE_DEMO,
            "corte": corte_panorama,
            "filtro": {"oferta": oferta, "razon": razon, "motivo": motivo_filtro},
            "n_coincidencias": len(candidatos) if filtrando else None,
            "conteo_por_oferta": vista.conteo_por_oferta() if vista else None,
            "conteo_por_razon": vista.conteo_por_razon() if vista else None,
            "clientes": coincide + libres}


@app.get("/api/clientes/{customer_id}")
def ficha_cliente(request: Request, customer_id: int, asof: str | None = None):
    """Ficha: perfil, movimientos, navegación reciente e historial de avisos."""
    e = request.app.state
    fecha = _asof(asof)
    try:
        ficha = e.store.ficha(customer_id, fecha)
    except KeyError:
        return JSONResponse(status_code=404,
                            content={"error": f"el cliente {customer_id} no existe",
                                     "customer_id": customer_id})
    caso = next((c for c in e.casos["casos"] if c["customer_id"] == customer_id), None)
    ficha["asof"] = fecha
    ficha["caso_curado"] = caso
    return ficha


@app.get("/api/clientes/{customer_id}/linea-tiempo")
def linea_tiempo(request: Request, customer_id: int, asof: str | None = None,
                 dias: int = Query(VENTANA_LINEA_DIAS, ge=1, le=90)):
    """Navegación y avisos **en el mismo eje**, con el corte marcado.

    Es la tesis del producto dibujada: se ve la señal y se ve si el aviso llegó
    cerca o lejos de ella.

    El corte es estricto, igual que en la ficha: aquí **no** viaja ni un evento
    con `ts >= asof`. Lo que se dibuja después del corte es la zona ciega —el
    tramo del eje donde el sistema no puede mirar—, y va vacía a propósito.
    """
    import pandas as pd

    e = request.app.state
    fecha = _asof(asof)
    if not e.store.existe(customer_id):
        return JSONResponse(status_code=404,
                            content={"error": f"el cliente {customer_id} no existe",
                                     "customer_id": customer_id})

    corte = pd.Timestamp(fecha)
    inicio = corte - pd.Timedelta(days=dias)
    # El eje sigue un poco más allá del corte para que la zona ciega se vea.
    fin = corte + pd.Timedelta(days=dias * MARGEN_POSTERIOR)
    total = (fin - inicio).total_seconds()

    def posicion(ts):
        return round(100.0 * (ts - inicio).total_seconds() / total, 4)

    ev = e.store._sub(e.store.ev, customer_id, "event_ts", corte)
    ev = ev[ev.event_ts >= inicio]
    nu = e.store._sub(e.store.nu, customer_id, "shown_ts", corte)
    nu = nu[nu.shown_ts >= inicio]

    eventos = [{
        "carril": "navegacion",
        "ts": r.event_ts.isoformat(sep=" "),
        "pos_pct": posicion(r.event_ts),
        "horas_antes_del_corte": round((corte - r.event_ts).total_seconds() / 3600, 2),
        "pantalla": str(r.screen),
        "accion": str(r.action),
        "etiqueta": f"{r.screen} · {r.action}",
    } for r in ev.itertuples()]

    avisos = [{
        "carril": "aviso",
        "ts": r.shown_ts.isoformat(sep=" "),
        "pos_pct": posicion(r.shown_ts),
        "horas_antes_del_corte": round((corte - r.shown_ts).total_seconds() / 3600, 2),
        "tipo": str(r.nudge_type),
        "titulo": TITULO.get(str(r.nudge_type), str(r.nudge_type)),
        "exposure_no": int(r.exposure_no),
        "enganchado": bool(r.engaged),
        "descartado": bool(r.dismissed),
        "etiqueta": f"{TITULO.get(str(r.nudge_type), str(r.nudge_type))} · #{int(r.exposure_no)}",
    } for r in nu.itertuples()]

    return {
        "customer_id": customer_id,
        "asof": fecha,
        "corte": fecha_de(fecha),
        "ventana_dias": dias,
        "inicio": inicio.isoformat(sep=" "),
        "fin": fin.isoformat(sep=" "),
        "corte_pos_pct": posicion(corte),
        "navegacion": eventos,
        "avisos": avisos,
        "n_navegacion": len(eventos),
        "n_avisos": len(avisos),
        "n_enganchados": sum(1 for a in avisos if a["enganchado"]),
        # Contrato explícito con la prueba anti-fuga: siempre 0.
        "n_posteriores_al_corte": 0,
        "zona_ciega": {
            "desde_pct": posicion(corte),
            "texto": "Después del corte el sistema no mira. Este tramo del eje va "
                     "vacío a propósito: no es que no haya pasado nada, es que nada "
                     "de lo que pase aquí entra en la decisión.",
        },
    }


class PeticionDecidir(BaseModel):
    customer_id: int
    asof: str | None = None


@app.post("/api/decidir")
def decidir(request: Request, peticion: PeticionDecidir):
    """La decisión, la traza de las 8 puertas y la explicación, en una respuesta.

    La explicación viaja **dentro** del POST: el clic es instantáneo y la leyenda
    no puede divergir de la decisión que la produjo.
    """
    e = request.app.state
    fecha = _asof(peticion.asof)
    try:
        return _decidir(e, peticion.customer_id, fecha)
    except Exception as ex:
        traceback.print_exc()
        return _degradado(f"{type(ex).__name__}: {ex}",
                          customer_id=peticion.customer_id, asof=fecha)


@app.get("/health")
def health(request: Request):
    """Estado y versión de los artefactos. Dice si corre en modelo o en fallback."""
    e = request.app.state
    esc = e.escalera
    nivel = esc.nivel_activo
    corte_meta = (e.metadata or {}).get("corte")
    return {
        "estado": "ok",
        "modelo": nivel,
        "en_modelo": nivel == "v1",
        "en_fallback": nivel != "v1",
        "escalera": esc.estado(),
        "corte_demo": CORTE_DEMO,
        "corte_metadata": corte_meta,
        "corte_coincide": corte_meta == CORTE_DEMO,
        "motivo_metadata": e.motivo_metadata,
        "motivo_umbrales": e.motivo_umbrales,
        "umbrales": e.umbrales,
        "metadata": e.metadata,
        "artefactos": e.artefactos,
        "razones_origen": e.razones.origen,
        # El dashboard se monta en un `try` al importar. Si no se montó, aquí
        # se dice —el comentario del montaje ya prometía que /health lo publica
        # y hasta ahora no lo hacía: un artefacto caído en silencio es
        # exactamente lo que la regla 3 del módulo prohíbe.
        "dashboard_montado": DASHBOARD_MONTADO,
        "dashboard_motivo": DASHBOARD_MOTIVO,
        "cobertura": _cobertura_con_texto(e.cobertura),
        # Los cortes con foto de features y la cobertura de cada uno: cambia con
        # el corte, así que se publican las cinco, no una sola repetida.
        "cortes_features": list(e.cortes),
        "coberturas_por_corte": {c: _cobertura_con_texto(e.panorama.cobertura(c))
                                 for c in e.panorama.cortes},
        "panorama": e.panorama.estado(),
        "casos_curados": len(e.casos["casos"]),
        "datos": {"clientes": int(len(e.store.cust)),
                  "eventos_app": int(len(e.store.ev)),
                  "acciones": int(len(e.store.fa)),
                  "avisos": int(len(e.store.nu)),
                  "grano_evento": int(len(e.store.eventos))},
        "arranque_s": e.arranque_s,
        "catalogo": list(CATALOGO_DEMO),
    }
