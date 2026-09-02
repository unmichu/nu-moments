"""PRD-4.c · «Cómo funciona», contado para alguien que no sabe nada de datos.

Esta pestaña la lee un directivo, no un analista. Por eso el módulo tiene una
sola regla y es la misma que el resto del servicio:

**el texto vive aquí, los números se calculan.** Los conteos de las puertas
salen de `app/panorama.py` —las mismas 8 puertas corridas sobre los 38 000 del
corte—, los valores de los productos salen de `tabla_valor.json`, el número de
señales que mira el modelo sale de `metadata.json` y los nueve ejemplos salen de
`casos_ejemplo.json` confrontados con lo que el panorama decide hoy. Si cambia
el corte, cambian todas; si cambia un artefacto, cambian solas.

Con **una excepción declarada**: el campo `narrativa` de los nueve casos
curados. Es prosa de analista congelada dentro de `casos_ejemplo.json` y trae
sus propias cifras escritas a mano, que NO se recalculan con el corte y que hoy
no coinciden del todo con lo que publica el dashboard (p. ej. dice «59.90 %»
donde el conteo da 59.89 %, y «4.60 % vs 1.20 %» donde la mediación del día de
pago da 4.59 % vs 1.16 %). Se sirve tal cual porque es el guion del demo; no se
puede citar como cifra del sistema. Lo demás de esta pantalla sí se calcula.

El glosario **no se duplica**: se toma el de `app/razones.py` —el que ya rige la
pantalla de decisión— y se le añaden los términos que allí no hacían falta
porque quien mira una decisión ya sabe qué es un modelo. Aquí no se supone nada.

Contrato con la pantalla: `GET /api/explicacion?corte=` devuelve `construir()`.
"""
from __future__ import annotations

import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__ in (None, ""):                                   # pragma: no cover
    import sys
    sys.path.insert(0, RAIZ)

from app import formato                                              # noqa: E402
from app.razones import (                                            # noqa: E402
    MOMENTO_ES,
    PUERTA_DESC,
    PUERTA_ES,
    RESULTADO_DESC,
    TITULO,
)
from pipeline import politica                                        # noqa: E402
from pipeline.mapas import (                                         # noqa: E402
    CAP_EXPOSICIONES,
    CATALOGO_DEMO,
    CORTE_DEMO,
    FRAGIL_DIAS_NEGATIVOS,
    FRAGIL_UTILIZACION_PCT,
    PRODUCTO_A_ACCION,
    PRODUCTO_A_PANTALLA,
    TODOS_LOS_PRODUCTOS,
    UMBRAL_ON_TIME_H,
    UMBRAL_WARM_H,
)
from pipeline.politica import C0, S0, S1, S2, S3, S4, S5, S6, S7     # noqa: E402

SILENCIO = "silencio"


def _miles(n):
    """`38000` → `'38 000'`. El mismo espacio fino que usa el resto de la app."""
    if n is None:
        return formato.GUION
    return f"{int(n):,}".replace(",", " ")


# ==========================================================================
# 1 · Los tres modelos y el respaldo, en el orden en que se ejecutan
# --------------------------------------------------------------------------
# El orden no es estético: es la cadena de preguntas. Primero *qué* quiere la
# persona, porque sin eso lo demás no tiene sujeto; luego *si es el momento*,
# porque la misma intención vale distinto según cuándo se hable; y al final
# *cuánto aporta o cuánto daña*, que es lo único que puede cambiar el signo.
#
# El tercero NO es un modelo. Decir que lo es sería la mentira más cómoda de
# esta pantalla, así que va marcada en cada sitio donde aparece.
# ==========================================================================
ES_ML = {
    True: "Sí, es aprendizaje automático",
    False: "No es aprendizaje automático",
}

MODELOS = [
    {
        "orden": 1,
        "clave": "intencion",
        "etiqueta": "Intención",
        "nombre": "¿Qué va a querer hacer esta persona?",
        "responde": "Qué acción financiera va a hacer el cliente en los próximos 7 días: "
                    "apartar dinero, pedir un préstamo, pedir más línea, pagar un servicio…",
        "mira": "Solo lo que ocurrió **antes** del corte: qué pantallas abrió y hace cuánto, "
                "cuántas veces entró en las últimas 24 y 72 horas, cuántos avisos ya vio, "
                "qué productos tiene contratados y cuántos días faltan para su día de pago. "
                "Nada de lo que pase después del corte existe para él.",
        "devuelve": "Una probabilidad por cada acción financiera. Un número entre 0 y 100: "
                    "de cada 100 clientes con el mismo perfil y la misma navegación, cuántos "
                    "harían esa acción.",
        "es_ml": True,
        "como_aprende": "Aprende de ejemplos pasados: se le enseñaron miles de semanas de "
                        "clientes con lo que hicieron después, y ajustó solo qué combinaciones "
                        "anticipan cada acción. Nadie le escribió las reglas.",
        "algoritmo": "HistGradientBoostingClassifier(max_depth=4), una cabeza binaria por acción",
        "por_que_aqui": "Va primero porque sin saber qué quiere el cliente, «¿es buen momento?» "
                        "no tiene sujeto y «¿cuánto aporta?» no tiene objeto.",
        "alimenta": "p_intencion",
    },
    {
        "orden": 2,
        "clave": "momento",
        "etiqueta": "Momento",
        "nombre": "¿Conviene hablarle ahora?",
        "responde": "Si el cliente respondería a un aviso enviado en este instante, o si el "
                    "mismo mensaje se desperdiciaría por llegar tarde o por llegar de más.",
        "mira": "Dos cosas, y nada más: cuánto hace que el cliente entró por su cuenta a la "
                "pantalla del producto —fresca, tibia, fría o nunca— y qué número de aviso "
                "sería este para él (el primero, el segundo…).",
        "devuelve": "La probabilidad de que ese aviso concreto se enganche.",
        "es_ml": True,
        "como_aprende": "También aprende de ejemplos, pero de otra cosa: no de clientes, sino "
                        "de avisos ya mostrados y de si funcionaron. Por eso son dos modelos y "
                        "no uno: la intención se mide por persona, el momento por aviso.",
        "algoritmo": "StandardScaler + LogisticRegression, 2 variables",
        "por_que_aqui": "Va segundo porque modula lo primero: la misma intención vale mucho "
                        "recién aparecida y casi nada una semana después.",
        "alimenta": "p_enganche",
    },
    {
        "orden": 3,
        "clave": "valor",
        "etiqueta": "Valor",
        "nombre": "¿Cuánto aporta o cuánto daña?",
        "responde": "Si un aviso de este tipo, cuando funciona, deja al cliente mejor o peor "
                    "que antes. Es la única de las tres preguntas que puede cambiar el signo.",
        "mira": "El historial completo de avisos que sí se engancharon y lo que le pasó a esa "
                "gente después, medido a 90 días: días en descubierto, ingreso y tasa de ahorro.",
        "devuelve": "Un número fijo por producto, el mismo para todos los clientes, medido en "
                    "días de descubierto evitados. Si es negativo, el producto hace daño.",
        "es_ml": False,
        "como_aprende": "No aprende. Es una resta y una división: se promedian tres diferencias "
                        "medidas y se combinan con una fórmula escrita a mano que no cambia. "
                        "Se recalcula, no se entrena; no tiene conjunto de prueba ni acierto que "
                        "reportar. Llamarla «modelo» sería engañoso, así que no se llama así.",
        "algoritmo": "media aritmética de tres diferencias medidas, fórmula cerrada",
        "por_que_aqui": "Va tercera porque es la que puede tumbar todo lo anterior: da igual "
                        "cuánto quiera el cliente un producto si ese producto le deja peor.",
        "alimenta": "V",
    },
]

RESPALDO = {
    "orden": None,
    "clave": "regla_24h",
    "etiqueta": "Regla de 24 h",
    "nombre": "¿Y si los modelos no cargan?",
    "responde": "Lo mismo que el primer modelo, pero con una regla escrita: si el cliente entró "
                "a la pantalla del producto en las últimas 24 horas, hay intención.",
    "mira": "Una sola cosa: la hora del último paso por la pantalla del producto.",
    "devuelve": "Una probabilidad tomada de una tabla de constantes medidas sobre los datos.",
    "es_ml": False,
    "como_aprende": "No aprende nada. Son cuatro constantes fijas. Está aquí para que el "
                    "sistema siga decidiendo —y diciendo con qué está decidiendo— cuando el "
                    "modelo entrenado no se puede cargar.",
    "algoritmo": "constantes medidas, sin entrenamiento",
    "por_que_aqui": "No se ejecuta nunca mientras el modelo entrenado esté disponible. Es el "
                    "segundo escalón de una escalera de tres, y el escalón activo se publica.",
    "alimenta": "p_intencion y p_enganche cuando el modelo entrenado no está",
}

# La escalera de respaldo, en lenguaje llano. El nivel activo se lee en vivo.
ESCALERA = [
    {"nivel": "v1", "titulo": "Modelo entrenado",
     "texto": "Los dos modelos aprendidos, sobre la foto de datos del corte que se pide. "
              "Es el escalón normal."},
    {"nivel": "regla_24h", "titulo": "Regla de 24 horas",
     "texto": "Si los modelos no se pueden cargar, se decide con la regla escrita. Peor, "
              "pero honesto: la pantalla lo dice en la esquina."},
    {"nivel": "demo_pack", "titulo": "Paquete precalculado",
     "texto": "El último recurso: decisiones calculadas de antemano para los clientes del "
              "guion. Sirve para que una demostración no se caiga."},
]


def modelos(metadata, tabla_valor, lmbda, nivel_activo):
    """Los tres modelos y el respaldo, con las cifras vivas de cada uno."""
    n_features = (metadata or {}).get("n_features")
    acciones = (metadata or {}).get("acciones") or []
    salida = []
    for m in MODELOS:
        d = dict(m)
        d["es_ml_texto"] = ES_ML[m["es_ml"]]
        if m["clave"] == "intencion":
            d["cifra"] = (f"{n_features} señales calculadas del pasado del cliente"
                          if n_features else None)
            d["detalle"] = ([f"{len(acciones)} acciones financieras posibles"]
                            if acciones else [])
        elif m["clave"] == "momento":
            d["cifra"] = "2 variables: cuán reciente es la señal y qué número de aviso sería"
            d["detalle"] = [f"{e['etiqueta']}: {e['texto']}" for e in MOMENTO_ES.values()]
        else:
            d["cifra"] = (f"λ = {lmbda:g} MXN por día en descubierto, para poder sumar "
                          f"dinero y días en la misma cuenta" if lmbda else None)
            d["detalle"] = [
                f"{TITULO.get(p, p)}: {formato.dias(float(tabla_valor[p]['V']))}"
                for p in CATALOGO_DEMO if p in (tabla_valor or {})]
        salida.append(d)
    r = dict(RESPALDO)
    r["es_ml_texto"] = ES_ML[r["es_ml"]]
    r["cifra"] = f"escalón activo ahora mismo: {nivel_activo}"
    r["detalle"] = []
    return salida, r


# ==========================================================================
# 2 · Las ocho puertas: a quién dejan fuera y por qué eso es bueno
# --------------------------------------------------------------------------
# `PUERTA_DESC` (app/razones.py) ya dice qué comprueba cada puerta y cuándo
# cierra. Aquí se añade lo que falta para alguien de fuera: **a quién deja
# fuera** y **por qué esa persona sale ganando**. No se reescribe lo que ya
# existe: se completa.
# ==========================================================================
PUERTA_EXTRA = {
    S0: {
        "deja_fuera": "A quien apagó las notificaciones después de un aviso anterior.",
        "bueno_porque": "Un «no» dicho una vez vale para siempre. Aunque hoy tuviera la señal "
                        "perfecta y el aviso le conviniera, no se le escribe: pedir permiso dos "
                        "veces es no haber escuchado la primera.",
    },
    S6: {
        "deja_fuera": "A nadie por su comportamiento: descarta fechas, no personas. Cierra los "
                      "días en los que los datos no sostienen una decisión.",
        "bueno_porque": "Decidir sobre una fecha rota es peor que no decidir. Preferimos no "
                        "hablar antes que hablar por un dato que no se sostiene.",
    },
    S1: {
        "deja_fuera": "A quien no ha entrado por su cuenta a la pantalla del producto en los "
                      "últimos 7 días.",
        "bueno_porque": "Es la puerta que más gente salva de una interrupción. Sin una señal "
                        "que el cliente haya dado, ofrecerle algo es adivinar en voz alta.",
    },
    S2: {
        "deja_fuera": "A quien ya vio dos veces este mismo aviso.",
        "bueno_porque": "La tercera vez ya no convence, molesta: en los datos engancha mucho "
                        "menos y provoca muchas más bajas. El tope protege la relación entera, "
                        "no solo este aviso.",
    },
    S5: {
        "deja_fuera": "A quien cerró este mismo aviso varias veces sin actuar.",
        "bueno_porque": "Cerrar un aviso es una forma de decir que no. Está implementada, pero "
                        "en el piloto no cierra a nadie.",
    },
    S3: {
        "deja_fuera": "A quien está en situación financiera frágil y pidió justo el producto "
                      "que empeoraría esa situación.",
        "bueno_porque": "Es la puerta que cuesta dinero y por eso es la que demuestra qué se "
                        "optimiza. El cliente pidió más línea; dársela sube su deuda. El sistema "
                        "no obedece la señal: la entiende. Cuando hay una alternativa sana, se "
                        "la ofrece en su lugar.",
    },
    S7: {
        "deja_fuera": "A quien el modelo no puntúa con suficiente confianza.",
        "bueno_porque": "Hablar con poca confianza es hablar por hablar. Está implementada, "
                        "pero en el piloto no cierra a nadie.",
    },
    S4: {
        "deja_fuera": "A todo el mundo, para los productos cuyo balance medido es negativo.",
        "bueno_porque": "No mira a la persona, mira al producto: si en promedio deja peor a "
                        "quien lo acepta, no se ofrece a nadie. Es la puerta que impide que un "
                        "producto rentable se cuele por serlo.",
    },
    C0: {
        "deja_fuera": "A ningún cliente: excluye productos completos que el piloto no ofrece.",
        "bueno_porque": "Un producto fuera del piloto se reporta como tal y no como «no había "
                        "señal». Dos silencios distintos no se cuentan como el mismo.",
    },
}

# Por qué una puerta puede cerrar 0 personas sin que eso sea un fallo.
MOTIVO_CERO = {
    "no_activa": "En el piloto esta puerta está implementada y se ejecuta, pero no cierra a "
                 "nadie. Es una decisión de alcance declarada, no un fallo: aparece en la "
                 "traza en vez de esconderse.",
    # Este texto es de S6 y SOLO de S6. Antes se le pegaba a cualquier puerta
    # activa que cerrase a 0 personas, así que S0 llegaba a decir que no había
    # cerrado a nadie «porque la fecha no cae en zona contaminada»: una razón
    # verdadera pegada a la puerta equivocada.
    "no_aplica_fecha": "En este corte no cerró a nadie, y eso es lo esperado: la fecha "
                       "elegida no cae en zona de datos contaminada.",
    "no_aplica": "En este corte no cerró a nadie. La puerta se evaluó y ningún cliente "
                 "cumplía su condición.",
    # Sin panorama no hay conteo: no se enseña un 0, que se leería como «no "
    # cerró a nadie». Se dice que no se sabe.
    "sin_panorama": "No hay conteo para este corte: el panorama no está calculado, así que "
                    "no se sabe a cuánta gente cerró. Un 0 aquí se leería como «no cerró a "
                    "nadie», que es otra cosa.",
    "por_producto": "No cierra personas, cierra productos: los que quedan fuera del catálogo "
                    "del piloto están cerrados para los 38 000 a la vez.",
}


def puertas(conteo_por_razon, n_silencio, n_clientes, sin_panorama=False):
    """Las 8 puertas + el fuera de catálogo, con el conteo real del corte.

    ⚠️ Matiz que se escribe en la pantalla, no se esconde: una persona puede
    estar cerrada por varias puertas a la vez. El conteo asigna cada silencio a
    **una** puerta, la de mayor prioridad de reporte —la misma con la que se le
    explica al cliente—, así que las 8 suman exactamente el silencio total.
    """
    conteo = conteo_por_razon or {}
    fuera = []
    for i, codigo in enumerate(politica.ORDEN_EVALUACION, start=1):
        d = PUERTA_DESC.get(codigo, {})
        extra = PUERTA_EXTRA.get(codigo, {})
        activa = politica.PUERTAS_ACTIVAS.get(codigo, True)
        n = None if sin_panorama else int(conteo.get(codigo, 0))
        motivo_cero = None
        if sin_panorama:
            motivo_cero = MOTIVO_CERO["sin_panorama"]
        elif n == 0:
            if not activa:
                motivo_cero = MOTIVO_CERO["no_activa"]
            elif codigo == S6:
                motivo_cero = MOTIVO_CERO["no_aplica_fecha"]
            else:
                motivo_cero = MOTIVO_CERO["no_aplica"]
        fuera.append({
            "orden": i,
            "puerta": codigo,
            "etiqueta": PUERTA_ES.get(codigo, codigo),
            "nombre": d.get("nombre"),
            "comprueba": d.get("comprueba"),
            "cierra_si": d.get("cierra_si"),
            "deja_fuera": extra.get("deja_fuera"),
            "bueno_porque": extra.get("bueno_porque"),
            "activa": activa,
            "estado": "activa" if activa else "implementada, no activa",
            "n": n,
            "n_texto": _miles(n) if n is not None else formato.GUION,
            "pct_de_la_base": (round(100.0 * n / n_clientes, 2)
                               if (n is not None and n_clientes) else None),
            "pct_de_la_base_texto": (formato.pct(100.0 * n / n_clientes)
                                     if (n is not None and n_clientes) else None),
            "pct_del_silencio": (round(100.0 * n / n_silencio, 2)
                                 if (n is not None and n_silencio) else None),
            "pct_del_silencio_texto": (formato.pct(100.0 * n / n_silencio)
                                       if (n is not None and n_silencio) else None),
            "motivo_cero": motivo_cero,
        })

    d, extra = PUERTA_DESC.get(C0, {}), PUERTA_EXTRA.get(C0, {})
    fuera.append({
        "orden": None,
        "puerta": C0,
        "etiqueta": PUERTA_ES.get(C0, C0),
        "nombre": d.get("nombre"),
        "comprueba": d.get("comprueba"),
        "cierra_si": d.get("cierra_si"),
        "deja_fuera": extra.get("deja_fuera"),
        "bueno_porque": extra.get("bueno_porque"),
        "activa": True,
        "estado": "fuera de las 8: cierra productos, no personas",
        "n": None, "n_texto": formato.GUION,
        "pct_de_la_base": None, "pct_de_la_base_texto": None,
        "pct_del_silencio": None, "pct_del_silencio_texto": None,
        "motivo_cero": MOTIVO_CERO["por_producto"],
    })
    return fuera


# ==========================================================================
# 3 · La cadena completa, de los tres números a los cuatro resultados
# ==========================================================================
CADENA = [
    {"paso": 1, "titulo": "Se juntan los tres números",
     "texto": "Los tres factores se multiplican entre sí. Multiplicar y no sumar tiene una "
              "consecuencia que se nota: si cualquiera de los tres es casi cero, el resultado "
              "es casi cero. No hay forma de compensar «no lo quiere» con «engancharía mucho».",
     "formula": "score = intención × enganche × valor"},
    {"paso": 2, "titulo": "Ese número no decide solo",
     "texto": "El score sirve para ordenar candidatos, nunca para autorizar un aviso. Antes de "
              "que salga nada, cada producto pasa por las 8 puertas en orden y la primera que "
              "cierra lo detiene ahí. Una puntuación altísima no abre ninguna puerta.",
     "formula": None},
    {"paso": 3, "titulo": "Entre los que sobreviven, gana uno",
     "texto": "De los productos que cruzaron las 8 puertas se elige el de score más alto. Si "
              "dos empatan, gana el que es mejor para la salud financiera del cliente, no el "
              "más rentable. Nunca sale más de un aviso.",
     "formula": None},
    {"paso": 4, "titulo": "Y se escribe por qué",
     "texto": "Salga aviso o salga silencio, la respuesta lleva el recorrido de las 8 puertas "
              "con el resultado de cada una. Ese registro es lo que permite comprobar que un "
              "silencio fue una decisión y no una caída.",
     "formula": None},
]


def resultados(conteo_por_oferta, n_sustitucion, n_clientes, n_fuera_catalogo):
    """Los cuatro resultados posibles, con cuánta gente cae en cada uno.

    `sustitucion` no es un quinto camino: es una oferta con un veto detrás, y
    por eso se cuenta **dentro** de las ofertas y se resta de ellas para que los
    tres primeros sumen los 38 000.
    """
    conteo = conteo_por_oferta or {}
    n_silencio = int(conteo.get(SILENCIO, 0))
    n_con_oferta = int(n_clientes) - n_silencio
    n_sust = int(n_sustitucion) if n_sustitucion is not None else None
    n_oferta_simple = (n_con_oferta - n_sust) if n_sust is not None else None

    def bloque(clave, titulo, que_ve, cuando, por_que, n, nota=None):
        return {
            "clave": clave, "titulo": titulo, "que_ve": que_ve, "cuando": cuando,
            "por_que": por_que,
            "n": n, "n_texto": _miles(n) if n is not None else formato.GUION,
            "pct": round(100.0 * n / n_clientes, 2) if (n is not None and n_clientes) else None,
            "pct_texto": (formato.pct(100.0 * n / n_clientes)
                          if (n is not None and n_clientes) else formato.GUION),
            "nota": nota,
        }

    return [
        bloque("oferta", "Ofrecer",
               "Una tarjeta con una sola acción, la que el sistema cree más útil hoy.",
               "Hay una señal reciente que dio el propio cliente, le queda cupo de avisos y el "
               "producto le deja mejor.",
               "Es el caso menos frecuente, y a propósito: hablar tiene un coste y solo se "
               "paga cuando hay algo que decir.",
               n_oferta_simple),
        bloque("sustitucion", "Sustituir",
               "Una tarjeta con una acción distinta de la que el cliente vino a buscar.",
               "El cliente reveló interés en un producto que le haría daño y existe una "
               "alternativa sana con cupo libre.",
               "El veto no es censura. Cuando se le puede dar algo mejor en la misma pantalla, "
               "se le da; el aviso vetado no deja un hueco, deja una alternativa.",
               n_sust,
               nota="Se cuenta dentro de las ofertas: no es un cuarto grupo de clientes, es una "
                    "oferta con un veto detrás."),
        bloque("silencio", "Callar",
               "Nada. La aplicación normal, sin tarjeta.",
               "Ninguna puerta dejó pasar a ningún producto.",
               "Callar es un resultado, no un fallo. La pantalla vacía de un sistema roto y la "
               "pantalla vacía de un sistema que decidió no interrumpir se ven igual, y por eso "
               "esta lleva su razón escrita y su recorrido de puertas. Que sea el resultado más "
               "frecuente es la tesis del producto, no un síntoma.",
               n_silencio),
        bloque("fuera_de_catalogo", "No estar en catálogo",
               "Nada, igual que el silencio, pero por un motivo distinto.",
               "El producto existe en los datos pero el piloto no lo ofrece.",
               "Se separa del silencio a propósito: «no te lo ofrecemos porque no lo ofrecemos "
               "a nadie» no es lo mismo que «hoy no es tu momento», y contarlos juntos "
               "escondería cuántos silencios son de verdad decisiones sobre la persona.",
               None,
               nota=f"Afecta a {n_fuera_catalogo} de los {len(TODOS_LOS_PRODUCTOS)} productos "
                    f"que hay en los datos, para los {_miles(n_clientes)} clientes a la vez. "
                    f"No es un conteo de personas."),
    ]


# ==========================================================================
# 4 · El glosario. Se REUTILIZA el de `app/razones.py` y se amplía.
# --------------------------------------------------------------------------
# El de la pantalla de decisión da por sabido lo que aquí no se puede dar por
# sabido. Estas entradas son las que faltan, y ninguna pisa a las existentes:
# si algún día `razones.glosario()` define una de estas claves, manda la suya.
# ==========================================================================
def terminos_extra(n_clientes, cap, lmbda):
    n = _miles(n_clientes)
    return {
        "modelo_entrenado": {
            "titulo": "Modelo (aprendizaje automático)",
            "texto": "Un programa que no lleva reglas escritas por una persona. Se le enseñan "
                     "muchos ejemplos del pasado con lo que ocurrió después y él ajusta solo "
                     "qué combinaciones anticipan qué. Dos de las tres piezas de este sistema "
                     "lo son; la tercera no, y está marcada en todas partes.",
        },
        "no_es_modelo": {
            "titulo": "Tabla de valor (no es un modelo)",
            "texto": "Una fórmula fija con números medidos. No aprende, no se entrena y no "
                     "tiene acierto que reportar: se recalcula. Presentarla como modelo daría "
                     "una impresión de sofisticación que no le corresponde.",
        },
        "probabilidad": {
            "titulo": "Probabilidad",
            "texto": "Una forma de decir «de cada 100 casos parecidos, en cuántos pasa». Un "
                     "30.00 % no significa que a esta persona le vaya a pasar: significa que de "
                     "100 personas en su misma situación, a 30 les pasó.",
        },
        "puerta": {
            "titulo": "Puerta",
            "texto": "Una comprobación que puede detener un aviso. Son 8 y se corren siempre en "
                     "el mismo orden; la primera que cierra detiene el recorrido de ese producto "
                     "y queda registrada como la razón. Ninguna puntuación, por alta que sea, "
                     "abre una puerta cerrada.",
        },
        "sustitucion": {
            "titulo": "Sustitución",
            "texto": "Cuando el cliente pide algo que le haría daño y el sistema le ofrece en su "
                     "lugar algo que sí le sirve. Es la única situación en la que el aviso que "
                     "sale no corresponde a la señal que entró.",
        },
        "catalogo": {
            "titulo": "Catálogo",
            "texto": f"Los productos que el piloto puede ofrecer: {len(CATALOGO_DEMO)} de los "
                     f"{len(TODOS_LOS_PRODUCTOS)} que aparecen en los datos. Los otros se "
                     f"reportan con su propio código y no se disfrazan de falta de señal.",
        },
        "fragilidad": {
            "titulo": "Fragilidad financiera",
            "texto": f"La definición que usa el sistema, sin adjetivos: tarjeta por encima del "
                     f"{formato.pct(FRAGIL_UTILIZACION_PCT)} de su límite, o "
                     f"{FRAGIL_DIAS_NEGATIVOS} días o más en números rojos en los últimos 90. "
                     f"Con cualquiera de las dos basta.",
        },
        "exposicion": {
            "titulo": "Exposición",
            "texto": f"Cada vez que se le enseña un aviso de un tipo. El tope es {cap} por tipo "
                     f"de producto, y se cuenta aunque el cliente ni lo mire: lo que cansa es "
                     f"el número de veces, no el tiempo que pasa entre ellas.",
        },
        "dias_de_descubierto": {
            "titulo": "Días en descubierto",
            "texto": "Días con el saldo en números rojos. Es la unidad en la que este sistema "
                     "mide si ayudó: no clics, no ingresos, días que el cliente no pasó "
                     "en descubierto.",
        },
        "lambda": {
            "titulo": "λ (el precio de un día en rojo)",
            "texto": f"Para poder sumar pesos y días hay que decir cuánto vale un día en "
                     f"descubierto. Aquí vale {lmbda:g} MXN, y ese número no se eligió a gusto: "
                     f"sale de los propios datos. Cambiarlo cambia el signo de algún producto, "
                     f"así que se publica en vez de esconderse dentro de la fórmula.",
        },
        "aviso": {
            "titulo": "Aviso",
            "texto": "La tarjeta que aparece dentro de la aplicación con una sola acción "
                     "propuesta y un botón. Nunca sale más de una a la vez.",
        },
        "foto_de_datos": {
            "titulo": "Foto de datos (as-of)",
            "texto": f"Una tabla congelada con todo lo que se sabía de los {n} clientes hasta "
                     f"un instante exacto. El sistema decide sobre la foto, no sobre el "
                     f"presente, y por eso una decisión de ayer se puede reproducir hoy "
                     f"idéntica.",
        },
        "cobertura": {
            "titulo": "Cobertura",
            "texto": f"Qué parte de los {n} clientes recibe algo en una fecha. Se cuenta "
                     f"corriendo las 8 puertas sobre toda la base, uno por uno; no es una "
                     f"estimación ni una cifra objetivo.",
        },
        "curva_de_fatiga": {
            "titulo": "Curva de fatiga",
            "texto": "Cómo cae el enganche y cómo sube la tasa de bajas conforme se repite el "
                     "mismo aviso. Es lo que fija el tope de exposiciones: no se eligió un "
                     "número redondo, se leyó dónde el aviso empieza a costar más de lo que "
                     "aporta.",
        },
    }


def glosario_ampliado(base, n_clientes, cap, lmbda):
    """El glosario de la decisión + los términos que aquí no se pueden suponer.

    El de `app/razones.py` manda: si una clave existe en los dos, se conserva la
    suya. Así la pestaña no puede contar una versión distinta de la que rige la
    pantalla de decisión.
    """
    fuera = {}
    for clave, entrada in terminos_extra(n_clientes, cap, lmbda).items():
        fuera[clave] = {**entrada, "origen": "cómo funciona"}
    for clave, entrada in (base or {}).items():
        fuera[clave] = {**entrada, "origen": "pantalla de decisión"}
    return fuera


# ==========================================================================
# 5 · Los nueve escenarios curados, contados como historias
# --------------------------------------------------------------------------
# No se copia lo que el guion promete: se confronta con lo que el panorama
# decide hoy en el corte de cada caso. Si algún día dejan de coincidir, la
# pantalla lo dice en vez de repetir la promesa.
# ==========================================================================
def ejemplos(casos, panorama):
    fuera = []
    for caso in casos:
        corte = caso.get("corte")
        vista = panorama.de(corte) if corte else None
        oferta = puerta = None
        if vista is not None:
            try:
                i = vista.idx.get_loc(int(caso["customer_id"]))
            except KeyError:                                     # pragma: no cover
                i = None
            if i is not None:
                oferta = str(vista.oferta[i])
                puerta = vista.puerta[i]
                puerta = str(puerta) if puerta is not None else None

        esperado = caso.get("esperado") or {}
        sustituye_a = esperado.get("sustituye_a")
        hay_oferta = bool(oferta) and oferta != SILENCIO
        if hay_oferta and sustituye_a:
            salida = "sustitucion"
        elif hay_oferta:
            salida = "oferta"
        elif oferta == SILENCIO:
            salida = "silencio"
        else:                                                    # pragma: no cover
            salida = None

        fuera.append({
            "customer_id": caso["customer_id"],
            "clave": caso.get("clave"),
            "titulo": caso.get("titulo"),
            "narrativa": caso.get("narrativa"),
            "corte": corte,
            "asof": caso.get("asof"),
            "salida": salida,
            "producto": oferta if hay_oferta else None,
            "producto_titulo": TITULO.get(oferta) if hay_oferta else None,
            "sustituye_a": sustituye_a,
            "sustituye_a_titulo": TITULO.get(sustituye_a) if sustituye_a else None,
            "puerta": puerta,
            "puerta_etiqueta": PUERTA_ES.get(puerta) if puerta else None,
            "puerta_nombre": (PUERTA_DESC.get(puerta) or {}).get("nombre") if puerta else None,
            # El guion y la ejecución tienen que decir lo mismo. Se comprueba
            # aquí y viaja a la pantalla, en vez de darse por hecho.
            "coincide_con_el_guion": (
                (esperado.get("nudge_type") == oferta) if esperado.get("enviar")
                else (oferta == SILENCIO)),
        })
    return fuera


# ==========================================================================
# 6 · Cuántas sustituciones hay de verdad en un corte
# --------------------------------------------------------------------------
# El panorama no lo guarda: sus arrays dicen qué se ofrece y por qué se calla,
# no si la oferta llegó en lugar de otra. Se cuenta con la misma evaluación
# vectorizada que usa la cobertura (~0.13 s), con la definición literal de
# `politica.armar_respuesta`: producto vetado por S3 con señal viva **y** algún
# candidato sano que ocupe su lugar.
# ==========================================================================
def contar_sustituciones(store, asof, tabla_valor):
    """Nº de clientes que reciben una oferta distinta de la que pidieron, o None."""
    masas = politica.evaluar_masivo(store, asof, tabla_valor)
    if "por_producto" not in masas:
        return None
    hay_oferta = masas["hay_oferta"]
    n = 0
    for producto in politica.PRODUCTOS_DANINOS_PARA_FRAGIL:
        d = masas["por_producto"].get(producto)
        if d is None:                                            # pragma: no cover
            continue
        # Si S3 es la puerta que cerró el producto, S1 no cerró antes: hay señal.
        n += int(((d["cierra"] == S3) & hay_oferta).sum())
    return n


# ==========================================================================
# 7 · El ensamblado
# ==========================================================================
def construir(estado, corte=None):
    """Todo lo que la pestaña «Cómo funciona» necesita, para un corte.

    `estado` es `app.state`: panorama, escalera, store, casos, metadata y el
    glosario de la pantalla de decisión. Nada se lee de disco aquí.
    """
    corte = corte or estado.panorama.corte_defecto or CORTE_DEMO
    vista = estado.panorama.de(corte)
    n_clientes = int(len(estado.store.cust))
    escalera = estado.escalera
    tabla_valor = escalera.tabla_valor or {}

    if vista is None:
        conteo_oferta, conteo_razon, cobertura, n_sust = {}, {}, None, None
        motivo = estado.panorama.motivos.get(corte) or f"no hay panorama para el corte {corte}"
    else:
        conteo_oferta = vista.conteo_por_oferta()
        conteo_razon = vista.conteo_por_razon()
        cobertura = dict(vista.cobertura)
        for clave in [k for k in list(cobertura) if k.startswith("pct_")]:
            cobertura[clave + "_texto"] = formato.pct(cobertura[clave])
        n_sust = contar_sustituciones(estado.store, vista.asof, tabla_valor)
        motivo = None

    n_silencio = int((conteo_oferta or {}).get(SILENCIO, 0))
    fuera_catalogo = [p for p in TODOS_LOS_PRODUCTOS if p not in CATALOGO_DEMO]
    lista_modelos, respaldo = modelos(
        estado.metadata, tabla_valor, escalera.lmbda, escalera.nivel_activo)

    return {
        "corte": corte,
        "es_corte_demo": corte == CORTE_DEMO,
        "motivo_sin_panorama": motivo,
        "n_clientes": n_clientes,
        "n_clientes_texto": _miles(n_clientes),
        "cobertura": cobertura,
        "conteo_por_oferta": conteo_oferta,
        "conteo_por_razon": conteo_razon,

        "modelos": lista_modelos,
        "respaldo": respaldo,
        "escalera": ESCALERA,
        "nivel_activo": escalera.nivel_activo,
        "orden_de_ejecucion": (
            "Primero qué va a querer el cliente, luego si conviene hablarle ahora, y al final "
            "cuánto aporta o cuánto daña. El orden es la cadena de preguntas: cada una necesita "
            "la respuesta de la anterior para tener sentido."),
        "aviso_sobre_el_tercero": (
            "Dos de las tres piezas son aprendizaje automático. La tercera —la tabla de valor— "
            "no lo es: es aritmética sobre datos medidos. Se dice aquí, y en cada tarjeta, "
            "porque presentarla como modelo sería engañoso."),

        "puertas": puertas(conteo_razon, n_silencio, n_clientes,
                           sin_panorama=vista is None),
        "nota_conteo_puertas": (
            f"Una misma persona puede estar cerrada por varias puertas a la vez. El conteo "
            f"asigna cada silencio a una sola —la que se le explica al cliente, la de mayor "
            f"prioridad—, así que las columnas suman exactamente los {_miles(n_silencio)} "
            f"silencios de este corte y ni una persona se cuenta dos veces."),
        "puertas_no_activas": [c for c in politica.ORDEN_EVALUACION
                               if not politica.PUERTAS_ACTIVAS.get(c, True)],
        "nota_no_activas": (
            "Dos de las ocho están implementadas y se ejecutan, pero en el piloto no cierran a "
            "nadie. No es un fallo ni un descuido: es alcance declarado. Se dejan en la traza, "
            "con su resultado a la vista, porque esconder una puerta que existe sería peor que "
            "enseñarla apagada."),
        "resultados_traza": RESULTADO_DESC,

        "cadena": CADENA,
        "resultados": resultados(conteo_oferta, n_sust, n_clientes, len(fuera_catalogo)),
        "n_sustituciones": n_sust,
        "por_que_callar": (
            "Porque la alternativa es hablar sin tener nada que decir, y eso tiene un precio "
            "que se paga una sola vez: cuando el cliente apaga las notificaciones, no vuelve. "
            "Un silencio con su razón escrita es una decisión que se puede revisar; una tarjeta "
            "de más es una relación que se gasta."),

        "glosario": glosario_ampliado(
            getattr(estado, "glosario", None), n_clientes, CAP_EXPOSICIONES, escalera.lmbda),
        "ejemplos": ejemplos(estado.casos["casos"], estado.panorama),

        "catalogo": [{"producto": p, "titulo": TITULO.get(p, p),
                      "pantalla": PRODUCTO_A_PANTALLA.get(p),
                      "accion": PRODUCTO_A_ACCION.get(p),
                      "V": float(tabla_valor[p]["V"]) if p in tabla_valor else None,
                      "V_texto": (formato.dias(float(tabla_valor[p]["V"]))
                                  if p in tabla_valor else formato.GUION)}
                     for p in CATALOGO_DEMO],
        "fuera_de_catalogo": [{"producto": p, "titulo": TITULO.get(p, p)}
                              for p in fuera_catalogo],
        "cap_exposiciones": CAP_EXPOSICIONES,
        "umbral_on_time_h": UMBRAL_ON_TIME_H,
        "umbral_warm_h": UMBRAL_WARM_H,
        "lambda": escalera.lmbda,
        "momentos": MOMENTO_ES,
    }
