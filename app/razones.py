"""BA-5 / PRD-3 · El motor de razones.

La leyenda explica con **el hecho del cliente**, nunca con la probabilidad del
modelo. Nadie quiere leer "tu probabilidad de intención es 0.34".

Las plantillas viven aquí y se pueden sobreescribir con
`pipeline/artifacts/razones.json` (contrato: producto + analítica). Si el
artefacto no está, se usan estas y `/health` dice de dónde salieron.
"""
from __future__ import annotations

import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__ in (None, ""):
    import sys
    sys.path.insert(0, RAIZ)

from app import formato                                            # noqa: E402
from pipeline.politica import C0, S0, S1, S2, S3, S4, S5, S6, S7   # noqa: E402

RUTA_RAZONES = os.path.join(RAIZ, "pipeline", "artifacts", "razones.json")

TITULO = {
    "savings_goal": "Aparta para tu meta",
    "limit_increase": "Sube tu línea de crédito",
    "loan_offer": "Tu préstamo, a tu medida",
    "bill_reminder": "Ponte al día sin intereses",
    "invest_start": "Empieza a invertir",
    "payroll_portability": "Trae tu nómina",
}

ETIQUETA_BOTON = {
    "savings_goal": "Crear una Cajita",
    "limit_increase": "Aumentar mi línea",
    "loan_offer": "Simular mi préstamo",
    "bill_reminder": "Programar mi pago",
    "invest_start": "Empezar a invertir",
    "payroll_portability": "Traer mi nómina",
}

PRODUCTO_ES = {
    "savings_goal": "una Cajita de ahorro",
    "limit_increase": "un aumento de línea",
    "loan_offer": "un préstamo",
    "bill_reminder": "programar tu pago",
    "invest_start": "empezar a invertir",
    "payroll_portability": "traer tu nómina",
}

PANTALLA_ES = {
    "savings_cajita": "Cajitas",
    "loan_simulation": "el simulador de préstamo",
    "limit_increase": "subir tu línea",
    "bill_payment": "pago de servicios",
    "investments": "inversiones",
    "home": "inicio",
    "transfer_spei": "transferencias",
    "card_statement": "tu estado de cuenta",
    "support": "ayuda",
    "card_settings": "ajustes de tarjeta",
}

# Etiqueta humana de cada puerta, para la traza plegada de la UI.
PUERTA_ES = {
    S0: "Bajas de notificaciones",
    S6: "Zona de datos contaminada",
    S1: "Señal reciente de intención",
    S2: "Cupo de exposiciones",
    S5: "Descartes repetidos",
    S3: "Fragilidad financiera",
    S7: "Confianza del modelo",
    S4: "Valor esperado",
    C0: "Fuera de catálogo",
    # el fixture nombra así al silencio de S3; se acepta como sinónimo
    "S3_veto_dano": "Fragilidad financiera",
}


def _horas(h):
    if h is None:
        return "hace mucho"
    if h < 1:
        return "hace menos de una hora"
    if h < 48:
        return f"hace {h:.0f} horas"
    return f"hace {h / 24:.0f} días"


def _mxn(v):
    if v is None:
        return "—"
    return f"{v:,.0f} MXN".replace(",", " ")


class Razones:
    """Plantillas cargadas al arranque. `origen` viaja a /health."""

    def __init__(self, plantillas=None, origen="plantillas internas (app/razones.py)"):
        self.plantillas = plantillas or {}
        self.origen = origen

    @classmethod
    def cargar(cls):
        if os.path.exists(RUTA_RAZONES):
            with open(RUTA_RAZONES, encoding="utf-8") as fh:
                return cls(json.load(fh), f"artefacto {os.path.basename(RUTA_RAZONES)}")
        return cls()

    # ------------------------------------------------------------- ofertas
    def oferta(self, ficha, oferta, sustituye_a=None):
        prod = oferta["producto"]
        s = oferta["senal"]
        h = _horas(s.get("horas_desde_senal"))
        sf = ficha["perfil"]["situacion_financiera"]
        util = sf.get("utilizacion_tarjeta_pct")
        d = ficha["decision"]

        propia = self.plantillas.get("ofertas", {}).get(prod)
        if propia:
            return propia.format(horas=h, util=util,
                                 pantalla=PANTALLA_ES.get(s.get("pantalla_acoplada"), ""),
                                 producto=PRODUCTO_ES.get(prod, prod))

        if sustituye_a:
            hv = _horas(d["senales_por_nudge"][sustituye_a].get("horas_desde_senal"))
            txt = (f"Entraste a subir tu línea {hv} y tu tarjeta está al {formato.pct(util)}. "
                   f"Un aumento ahora te costaría más de lo que te ayuda. "
                   f"Esto sí te conviene: {PRODUCTO_ES.get(prod, prod)}.")
            return txt

        if prod == "savings_goal":
            monto = _monto_ahorro(ficha)
            meta = monto * 2 * 6 if monto else None
            base = f"Entraste a Cajitas {h}"
            if s.get("hubo_start_24h"):
                base += " y llegaste a iniciar el flujo"
            if monto:
                base += (f". Apartando {_mxn(monto)} cada quincena —lo que ya mueves en "
                         f"promedio— en 6 meses juntas {_mxn(meta)}")
            return base + "."
        if prod == "loan_offer":
            return (f"Simulaste un préstamo {h}. Con tu historial, esto es lo que te "
                    f"podemos ofrecer hoy.")
        if prod == "limit_increase":
            dias = sf.get("dias_en_negativo_90d") or 0
            cola = ("y no llevas días en negativo en los últimos 90"
                    if dias == 0 else f"y llevas {dias} días en negativo en los últimos 90")
            return f"Tu tarjeta está al {formato.pct(util)} {cola}. Podemos subirte la línea."
        if prod == "bill_reminder":
            extra = ""
            if d.get("ventana_payday"):
                extra = f" Además estás a {d['dias_a_payday']} días de tu día de pago."
            return f"Entraste a pago de servicios {h}. Programarlo hoy te evita el recargo.{extra}"
        return f"Mostraste interés en {PRODUCTO_ES.get(prod, prod)} {h}."

    # ------------------------------------------------------------ silencios
    def silencio(self, ficha, silencio):
        prod = silencio["producto"]
        puerta = silencio["puerta"]
        hechos = silencio.get("hechos", {})
        sf = ficha["perfil"]["situacion_financiera"]

        propia = self.plantillas.get("silencios", {}).get(puerta)
        if propia:
            return propia.format(producto=PRODUCTO_ES.get(prod, prod), **hechos)

        if puerta == S0:
            return "Desactivaste las notificaciones. Se respeta."
        if puerta == S6:
            return (f"La fecha elegida no es evaluable: {hechos.get('motivo_fecha')}. "
                    f"Preferimos callarnos antes que decidir con datos que no sostienen nada.")
        if puerta == S1:
            return ("No hay nada que hayas mostrado interés en hacer. Mejor no interrumpir.")
        if puerta == S2:
            n = hechos.get("exposiciones")
            return (f"Ya te avisamos {n} veces de esto. Insistir una tercera vez cuesta "
                    f"más de lo que suma.")
        if puerta == S5:
            return (f"Descartaste este aviso {hechos.get('n_descartados')} veces. "
                    f"Tomamos nota.")
        if puerta in (S3, "S3_veto_dano"):
            motivos = hechos.get("motivo_fragilidad") or []
            detalle = " y ".join(motivos) if motivos else (
                f"utilización {formato.pct(sf.get('utilizacion_tarjeta_pct'))}")
            return (f"Sí detectamos que buscabas {PRODUCTO_ES.get(prod, prod)}, pero con "
                    f"tu situación actual ({detalle}) te dejaría peor. No te lo vamos a ofrecer.")
        if puerta == S7:
            return ("El modelo no llega al umbral de confianza para hablar de esto hoy.")
        if puerta == S4:
            v = hechos.get("V")
            return (f"El valor esperado de este aviso es {v:+.3f} con λ={hechos.get('lambda')}: "
                    f"en promedio te deja peor de lo que te ayuda.")
        if puerta == C0:
            return "Este producto no se ofrece en el piloto."
        return "Sin razón registrada."

    # ------------------------------------------------------- silencio global
    def encabezado_silencio(self, ficha, respuesta):
        """El texto grande de la pantalla de silencio. Es una pantalla diseñada."""
        puerta = respuesta.get("puerta_reportada")
        principal = next((s for s in respuesta["silencios"] if s["puerta"] == puerta), None)
        if principal is None:
            return ("El sistema evaluó las 8 puertas y decidió no interrumpir.",
                    "Sin razón registrada.")
        titulos = {
            S0: "Desactivaste las notificaciones",
            S6: "Esta fecha no es evaluable",
            S1: "Hoy no hay nada que decir",
            S2: "Ya te lo dijimos suficiente",
            S5: "Ya lo descartaste",
            S3: "Podíamos hablarle. Decidimos no hacerlo.",
            S7: "No hay confianza suficiente",
            S4: "Hablar aquí te dejaría peor",
        }
        return (titulos.get(puerta, "El sistema decidió callarse"),
                self.silencio(ficha, principal))


def _monto_ahorro(ficha):
    """Promedio real de sus movimientos a Cajita en 90 días; 10 % del ingreso si no hay."""
    agg = ficha["movimientos"].get("agregado_90d", {})
    s = agg.get("savings_move")
    if s and s.get("monto_prom_mxn"):
        return round(float(s["monto_prom_mxn"]) / 2, -1)   # por quincena
    ing = ficha["perfil"].get("ingreso_mensual_est_mxn")
    return round(float(ing) * 0.05, -1) if ing else None


# ==========================================================================
# Lenguaje llano · el diccionario que la pantalla usa para explicarse
# --------------------------------------------------------------------------
# Cada puerta con su nombre humano, qué comprueba y qué significa cerrarla.
# Vive aquí y no en la plantilla para que la pantalla no pueda contar una
# versión distinta de la que ejecuta `pipeline/politica.py`.
# ==========================================================================
PUERTA_DESC = {
    S0: {"nombre": "¿Quiere que le hablemos?",
         "comprueba": "Si el cliente desactivó las notificaciones en algún aviso anterior.",
         "cierra_si": "Se dio de baja. No se le vuelve a escribir, aunque el aviso le conviniera."},
    S6: {"nombre": "¿La fecha es de fiar?",
         "comprueba": "Si el día elegido cae en una zona de los datos que no sostiene una decisión "
                      "(los 3 primeros días del panel son un artefacto del generador y los 3 "
                      "últimos están censurados por la ventana de etiqueta de 7 días).",
         "cierra_si": "La fecha no es evaluable. Callarse es preferible a decidir con datos rotos."},
    S1: {"nombre": "¿Mostró interés hace poco?",
         "comprueba": "Si entró a la pantalla acoplada al producto en los últimos 7 días.",
         "cierra_si": "No hay nada que el cliente haya dado a entender que quiere. Interrumpir sería adivinar."},
    S2: {"nombre": "¿Le queda cupo de avisos?",
         "comprueba": "Cuántas veces se le ha mostrado ya este mismo tipo de aviso (tope: 2).",
         "cierra_si": "Ya se le dijo dos veces. La tercera cuesta más bajas que enganches."},
    S5: {"nombre": "¿Ya lo había descartado?",
         "comprueba": "Cuántas veces cerró este mismo aviso sin actuar.",
         "cierra_si": "Descartó el aviso de forma repetida. En el piloto esta puerta no está activa."},
    S3: {"nombre": "¿Este producto le haría daño?",
         "comprueba": "Si el cliente está en situación frágil (tarjeta por encima del 70 % de "
                      "utilización o 3 o más días en negativo en 90) y el producto empeoraría eso.",
         "cierra_si": "Sí quería el producto, pero le dejaría peor. Es un veto, no una falta de datos."},
    S7: {"nombre": "¿El modelo está seguro?",
         "comprueba": "Si la confianza del modelo llega al mínimo para hablar.",
         "cierra_si": "El modelo no llega al umbral. En el piloto esta puerta no está activa."},
    S4: {"nombre": "¿Aporta más de lo que quita?",
         "comprueba": "El valor esperado del aviso, medido en días de descubierto evitados.",
         "cierra_si": "El valor es cero o negativo: en promedio el aviso deja al cliente peor."},
    C0: {"nombre": "Fuera del catálogo del piloto",
         "comprueba": "Si el producto forma parte de los 4 que el piloto puede ofrecer.",
         "cierra_si": "El producto existe en los datos pero no se ofrece en el piloto."},
}

# Qué significa cada resultado de la traza. `no_activa` es el que más se
# malinterpreta: la puerta existe y se ejecuta, simplemente no cierra a nadie.
RESULTADO_DESC = {
    "pasa": {"etiqueta": "pasa",
             "texto": "La puerta se evaluó y no cerró a ningún producto."},
    "cierra": {"etiqueta": "cierra",
               "texto": "La puerta se evaluó y cerró al menos un producto. El recorrido "
                        "de ese producto termina aquí."},
    "no_activa": {"etiqueta": "no activa",
                  "texto": "La puerta está implementada y se ejecuta, pero en el piloto no "
                           "cierra a nadie. No es un fallo ni un error: es una decisión de "
                           "alcance, y por eso se muestra en la traza en vez de esconderse."},
    "no_evaluada": {"etiqueta": "no evaluada",
                    "texto": "El sistema entró en modo degradado y no llegó a correr esta puerta."},
}

# Los cuatro estados de la señal, con el umbral que los separa.
MOMENTO_ES = {
    "on_time": {"etiqueta": "fresca",
                "texto": "Entró a la pantalla en las últimas 24 horas. Es la señal más fuerte "
                         "que tiene el sistema."},
    "warm": {"etiqueta": "tibia",
             "texto": "Entró a la pantalla hace entre 24 horas y 7 días. Sirve, pero pesa menos."},
    "cold": {"etiqueta": "fría",
             "texto": "Entró a la pantalla hace más de 7 días. Para la política es como no haber entrado."},
    "never": {"etiqueta": "nunca",
              "texto": "No hay ni un registro de que haya entrado a esa pantalla antes del corte."},
}


def glosario(corte, n_clientes, cap, umbral_on_time_h, umbral_warm_h, lmbda):
    """Las explicaciones de cada número de la pantalla, con sus cifras reales.

    Se arma en el arranque con los valores que de verdad rigen la ejecución
    (el corte, los 38,000 clientes, el cap, los umbrales, λ) para que el texto
    no pueda quedarse desfasado respecto a lo que hace el código.
    """
    n = f"{n_clientes:,}".replace(",", " ")     # 38 000, sin tocar las comas del texto
    return {
        "corte": {
            "titulo": "Corte",
            "texto": f"La fecha desde la que el sistema mira hacia atrás. Para decidir el "
                     f"{corte} solo existe lo ocurrido antes de ese instante: nada posterior "
                     f"se usa, ni para las features ni para la ficha. Cambiar el corte mueve "
                     f"la cámara, no cambia al cliente.",
        },
        "silencio": {
            "titulo": "Silencio",
            "texto": f"El porcentaje de los {n} clientes a los que el sistema decide no "
                     f"decirles nada en esta fecha. Se recalcula corriendo las puertas sobre "
                     f"toda la base: no está escrito en ninguna parte.",
        },
        "oferta": {
            "titulo": "Oferta",
            "texto": f"El porcentaje de los {n} clientes que sí recibiría un aviso en esta "
                     f"fecha. Silencio y oferta suman 100.00 %.",
        },
        "p_intencion": {
            "titulo": "Probabilidad de intención",
            "texto": "De cada 100 clientes con el mismo perfil y la misma navegación previa al "
                     "corte, cuántos harían esta acción financiera en los 7 días siguientes. "
                     "Lo predice el modelo de intención —el que en «Cómo funciona» se "
                     "llama «¿Qué va a querer hacer esta persona?»— sobre la foto de datos "
                     "del corte.",
        },
        "p_enganche": {
            "titulo": "Probabilidad de enganche",
            "texto": "De cada 100 avisos como este mostrados a clientes en el mismo estado de "
                     "señal y en el mismo número de exposición, cuántos se enganchan. Lo predice "
                     "el modelo de momento —el que en «Cómo funciona» se llama «¿Conviene "
                     "hablarle ahora?»— con dos variables: frescura de la señal y número de "
                     "exposición.",
        },
        "valor": {
            "titulo": "Valor esperado (V)",
            "texto": f"Cuántos días de descubierto le ahorra al cliente, en promedio, un aviso de "
                     f"este tipo que sí engancha. Se mide comparando resultados a 90 días y se "
                     f"expresa en días, con λ={lmbda:g} MXN por día en descubierto para poder "
                     f"sumar el efecto en ingreso. Es un número pequeño porque un aviso mueve "
                     f"días, no meses. Si es negativo, el aviso deja peor al cliente.",
        },
        "score": {
            "titulo": "Score",
            "texto": "El producto de los tres factores: intención × enganche × valor. Está en "
                     "días de descubierto evitados esperados, ya descontando que el cliente "
                     "quizá no quería la acción y que quizá no habría enganchado. Sirve para "
                     "ordenar candidatos, no para leerlo suelto.",
        },
        "tasa_base": {
            "titulo": "Tasa base",
            "texto": f"La fracción de los {n} clientes que de verdad hizo esa acción en la "
                     f"ventana de 7 días de este corte. Es un conteo sobre los datos, no una "
                     f"predicción. Es el punto de comparación honesto: un cliente con 3× la "
                     f"tasa base tiene el triple de probabilidad que la media.",
        },
        "tasa_base_enganche": {
            "titulo": "Tasa base de enganche",
            "texto": "La fracción de avisos de este tipo que se engancharon, contada sobre todos "
                     "los avisos mostrados antes del corte.",
        },
        "percentil": {
            "titulo": "Percentil",
            "texto": f"A qué porcentaje de los {n} clientes evaluados en este mismo corte "
                     f"supera este cliente. El percentil 99.00 % significa que solo 1 de cada "
                     f"100 tiene un valor más alto.",
        },
        "cupo": {
            "titulo": "Cupo",
            "texto": f"El tope de exposiciones por tipo de producto: {cap} y no más. No es una "
                     f"cifra de despacho, sale de la curva de fatiga de los datos: en la primera "
                     f"exposición engancha el 15.68 % y se dan de baja el 0.28 %; en la tercera "
                     f"engancha el 3.51 % y se dan de baja el 2.53 %, es decir 0.72 bajas por "
                     f"cada enganche. A partir de ahí insistir destruye más de lo que gana.",
        },
        "senal": {
            "titulo": "Señal",
            "texto": f"Una señal es que el cliente entró por su cuenta a la pantalla acoplada al "
                     f"producto —Cajitas para el ahorro, el simulador para el préstamo— antes del "
                     f"corte. Es fresca hasta las {umbral_on_time_h} h y tibia hasta los "
                     f"{umbral_warm_h // 24} días; más allá, la política actúa como si no existiera.",
        },
        "traza": {
            "titulo": "Traza",
            "texto": "El recorrido completo de las 8 puertas, en el orden en que se ejecutan. "
                     "Se muestra siempre, haya oferta o silencio: es la única forma de comprobar "
                     "que el silencio fue una decisión y no un fallo.",
        },
        "modelo": {
            "titulo": "Nivel de la escalera",
            "texto": "Con qué está puntuando el servicio: `v1` es el modelo entrenado, "
                     "`regla_24h` la regla de respaldo y `demo_pack` el paquete precalculado. "
                     "Si baja de nivel, `/health` dice por qué.",
        },
    }
