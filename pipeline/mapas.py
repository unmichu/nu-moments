"""Mapas compartidos entre analítica e ingeniería.

Contrato BA-1. Este archivo es la única fuente de verdad sobre qué producto
se ofrece, qué acción lo confirma y en qué pantalla se detecta la intención.

⚠️ Una vez acordado, es de SOLO LECTURA. Cambiarlo rompe a la otra área en
silencio: los modelos se entrenan contra un catálogo y la política evalúa otro.
"""

# Producto (tipo de aviso) -> acción financiera que confirma la conversión.
PRODUCTO_A_ACCION = {
    "savings_goal": "savings_move",
    "limit_increase": "limit_increase_request",
    "loan_offer": "loan_request",
    "bill_reminder": "bill_payment",
    "invest_start": "investment_buy",
}

# Producto -> pantalla acoplada donde el cliente revela la intención.
PRODUCTO_A_PANTALLA = {
    "savings_goal": "savings_cajita",
    "limit_increase": "limit_increase",
    "loan_offer": "loan_simulation",
    "bill_reminder": "bill_payment",
    "invest_start": "investments",
}

# Catálogo del piloto: lo que el sistema puede ofrecer.
#
# `invest_start` queda fuera: conversión 1.87% y eficiencia del clic 0.26.
# `payroll_portability` no aparece en ningún mapa porque su pantalla acoplada
# es la de inicio, así que cualquiera que abra la app "tiene señal" y se lleva
# el 10.5% de las ofertas por trivialidad.
CATALOGO_DEMO = [
    "savings_goal",
    "limit_increase",
    "loan_offer",
    "bill_reminder",
]

# Todos los tipos presentes en los datos, para poder reportar los que quedan
# fuera con su propio código en vez de fingir un silencio por falta de señal.
TODOS_LOS_PRODUCTOS = [
    "savings_goal",
    "limit_increase",
    "bill_reminder",
    "loan_offer",
    "invest_start",
    "payroll_portability",
]

# Las 10 pantallas de app_events.
PANTALLAS = [
    "home",
    "transfer_spei",
    "bill_payment",
    "card_statement",
    "savings_cajita",
    "loan_simulation",
    "limit_increase",
    "investments",
    "support",
    "card_settings",
]

# Los 8 tipos de acción de financial_actions.
ACCIONES = [
    "spei_out",
    "bill_payment",
    "deposit_in",
    "savings_move",
    "loan_request",
    "limit_increase_request",
    "card_payment",
    "investment_buy",
]

# Cortes. Son dos y sirven para cosas distintas: el día de pago solo toma los
# valores 1, 15 y 30, y el corte del modelo cae en el hueco, así que ahí el
# caso de sincronía con la quincena no existe.
CORTE_MODELO = "2026-06-09"
CORTES_ROLLING = ["2026-05-30", "2026-06-09", "2026-06-14"]
CORTE_UMBRALES = "2026-05-23"
CORTE_DEMO = "2026-06-16"
CORTE_DEMO_RESPALDO = "2026-06-01"

# Guardrails.
CAP_EXPOSICIONES = 2          # derivado: en la 3ª exposición hay 0.72 bajas por enganche
UMBRAL_ON_TIME_H = 24         # señal fresca
UMBRAL_WARM_H = 24 * 7        # señal tibia
LAMBDA_DEFECTO = 266.0        # MXN por día en descubierto (precio revelado)
PESO_AHORRO = 0.3             # el signo de las 4 ofertas es invariante en [0,1]

# Fragilidad: utilización alta o días en negativo recientes.
FRAGIL_UTILIZACION_PCT = 70.0
FRAGIL_DIAS_NEGATIVOS = 3
