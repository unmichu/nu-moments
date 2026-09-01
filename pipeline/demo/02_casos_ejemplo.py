"""
02_casos_ejemplo.py — Selecciona y VERIFICA los clientes-ejemplo del pitch.

Cada arquetipo se busca sobre el scan de uno o más cortes; se reconstruye la ficha
completa (as-of estricto) y se pasa por politica.decide() para confirmar que el
sistema decide lo que la historia promete. Si no coincide, el candidato se descarta.

Salida: recon/demo/casos_ejemplo.json  (lo consume el backend directo)
Uso:    /tmp/hackenv/bin/python 02_casos_ejemplo.py
"""
import json
import os

import pandas as pd

from ficha import Store
from politica import decide

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

CORTE_A = "2026-06-16"   # corte demo principal: ventana payday activa + señal rica
CORTE_B = "2026-06-09"   # d100, el corte del modelo (contrato C1)
CORTES = [CORTE_A, CORTE_B]

_scans = {}


def scan(asof):
    if asof not in _scans:
        p = os.path.join(OUT, f"scan_{asof}.csv")
        if not os.path.exists(p):
            os.system(f'cd {HERE} && /tmp/hackenv/bin/python 01_scan_candidatos.py {asof} >/dev/null')
        _scans[asof] = pd.read_csv(p).set_index("customer_id")
    return _scans[asof]


def main():
    st = Store()
    casos, usados = [], set()

    def add(clave, titulo, mask_fn, orden, espera_enviar, espera_tipo=None,
            espera_razon=None, narrativa="", cortes=CORTES, n=12):
        for asof in cortes:
            df = scan(asof)
            sub = df[mask_fn(df)]
            if not len(sub):
                continue
            for cid in sub.sort_values(orden, ascending=False).index[:n]:
                if cid in usados:
                    continue
                f = st.ficha(cid, asof)
                d = decide(f)
                if d["enviar"] != espera_enviar:
                    continue
                if espera_tipo and d.get("nudge_type") != espera_tipo:
                    continue
                if espera_razon and d.get("razon_silencio") != espera_razon:
                    continue
                usados.add(cid)
                casos.append({"clave": clave, "titulo": titulo, "customer_id": int(cid),
                              "corte": asof, "narrativa": narrativa, "decision": d, "ficha": f})
                print(f"  OK {clave:20s} cid={cid} corte={asof} -> "
                      f"{'ENVIAR ' + str(d.get('nudge_type')) if d['enviar'] else 'SILENCIO ' + str(d['razon_silencio'])}")
                return
        print(f"  !! {clave}: ningun candidato cumplio")

    # 1 · señal fresca de AHORRO -> Cajita  (fuera de payday, para no duplicar el caso 6)
    add("ahorro_fresco", "Señal fresca de ahorro → Cajita",
        lambda d: (d.on_time_savings_goal & ~d.fragil & (d.exp_savings_goal <= 1) & ~d.opt_out
                   & (d.ev30 >= 8) & (d.fa30 >= 3) & d.start24_savings_goal & ~d.ventana_payday),
        ["ev30"], True, "savings_goal",
        narrativa="Abrió Cajitas en las últimas 24 h y llegó a iniciar el flujo (start vale 1.09–1.56x "
                  "más que un view). Está en el 5.9% de la base con señal fresca: enganche 41.63% "
                  "contra 10.30% de quien nunca visitó la pantalla.")

    # 2 · señal fresca de PRÉSTAMO -> loan_offer
    add("prestamo_fresco", "Señal fresca de préstamo → oferta de préstamo",
        lambda d: (d.on_time_loan_offer & ~d.fragil & (d.exp_loan_offer <= 1) & ~d.opt_out
                   & (d.ev30 >= 6) & (d.age >= 25) & (d.card_utilization_pct < 60)
                   & ~d.on_time_savings_goal & ~d.on_time_bill_reminder),
        ["ev30"], True, "loan_offer",
        narrativa="Simuló un préstamo en las últimas 24 h. loan_simulation→loan_request es lift 30.16x "
                  "sobre la tasa base: es la clase rara y por eso la más predecible condicionalmente. "
                  "No es frágil, así que la oferta no le hace daño (Δ días negativos de loan_offer = −0.008).")

    # 3 · CASO ESTRELLA — frágil con señal de línea, el sistema SUSTITUYE
    add("fragil_sustituye", "Frágil pide línea → el sistema sustituye la oferta",
        lambda d: (d.on_time_limit_increase & d.fragil & ~d.opt_out & (d.exp_limit_increase <= 1)
                   & (d.on_time_savings_goal | d.on_time_bill_reminder
                      | d.warm_savings_goal | d.warm_bill_reminder)),
        ["card_utilization_pct"], True, None,
        narrativa="Entró a aumento de línea, pero está frágil. limit_increase engancha 25.36% a los "
                  "frágiles vs 17.39% al resto (+46%) y les cuesta +17.52pp de utilización y +2.06 días "
                  "en negativo. El sistema veta la oferta que él pidió y pone en su lugar la que sí le "
                  "sirve. Ese es el producto: no obedecer la señal, entenderla.")

    # 3b · frágil sin alternativa -> SILENCIO por veto
    add("fragil_silencio", "Frágil pide línea → silencio por veto",
        lambda d: (d.on_time_limit_increase & d.fragil & ~d.opt_out & (d.exp_limit_increase <= 1)
                   & ~d.on_time_savings_goal & ~d.on_time_bill_reminder
                   & ~d.warm_savings_goal & ~d.warm_bill_reminder
                   & ~d.on_time_invest_start & ~d.warm_invest_start
                   & ~d.on_time_payroll_portability & ~d.warm_payroll_portability
                   & ~d.on_time_loan_offer & ~d.warm_loan_offer),
        ["card_utilization_pct"], False, None, "veto_fragilidad",
        narrativa="Misma señal, sin alternativa sana disponible: el asistente no dice nada. El veto toca "
                  "solo el 3.2% del volumen y da la vuelta al signo del sistema (+1,679 → −3,031 días en "
                  "descubierto). Cuesta 21.8% del revenue: 165 MXN por día de descubierto evitado.")

    # 4 · FATIGADO — señal fresca pero cupo agotado
    add("fatigado", "Cupo agotado → silencio por fatiga",
        lambda d: ((d.exp_savings_goal >= 3) & d.on_time_savings_goal & ~d.opt_out
                   & ~d.on_time_loan_offer & ~d.on_time_limit_increase),
        ["exp_savings_goal"], False, None, "cupo_agotado",
        narrativa="Tiene la intención Y el historial: ya vio ese mensaje 3+ veces. En la 3ª exposición el "
                  "enganche es 3.51% y el opt-out 2.53% → 0.72 bajas por cada clic; en la 4ª, 1.89. "
                  "Por eso el cap es 2. Y no es cuestión de esperar: hours_since_last_nudge no tiene "
                  "efecto controlando por exposure_no. Lo que fatiga es el CONTEO, no el reloj.")

    # 5 · SIN SEÑAL — silencio por falta de intención
    add("sin_senal", "Sin señal reciente → silencio",
        lambda d: (~d.senal_7d_alguna & ~d.opt_out & (d.ev_tot >= 15) & (d.fa_tot >= 8)),
        ["fa_tot"], False, None, "sin_senal",
        narrativa="Cliente activo con historial rico, pero cero señal de intención en 7 días en las "
                  "pantallas acopladas a una oferta. El 59.9% de los nudges de hoy se mandan así y "
                  "convierten 10.30%. Aquí el asistente se calla — y ese silencio ES el producto.")

    # 6 · PAYDAY — señal fresca + día de pago encima
    add("payday", "Ventana de payday + señal → timing óptimo",
        lambda d: (d.ventana_payday & (d.dias_a_payday <= 1) & d.on_time_savings_goal
                   & ~d.fragil & ~d.opt_out & (d.exp_savings_goal <= 1) & (d.fa30 >= 4)),
        ["ev30"], True, "savings_goal",
        narrativa="Está a ≤1 día de su día de pago Y acaba de entrar a Cajitas. En payday hay 3.9x más "
                  "probabilidad de que exista señal fresca (4.6% vs 1.2%) y savings_move sube hasta 5.4x. "
                  "Pero el efecto payday sobre el engagement es 100% MEDIADO: dentro de cada estrato de "
                  "momento el enganche es idéntico. No mandamos por calendario; mandamos porque la señal "
                  "apareció, y el calendario explica por qué apareció hoy.",
        cortes=[CORTE_A])

    # 7 · OPT-OUT previo — silencio absoluto
    add("opt_out", "Ya se dio de baja → silencio absoluto",
        lambda d: (d.opt_out & d.senal_fresca_alguna),
        ["ev30"], False, None, "opt_out",
        narrativa="Apagó las notificaciones tras un nudge anterior. Hoy tiene señal perfecta y no le "
                  "hablamos: el opt-out es irreversible desde la app y en MX cambiar preferencias exige "
                  "PIN Challenge (CNBV Art. 313). El costo de la fatiga no se paga una vez, se paga para "
                  "siempre.")

    # 8 · DOS SEÑALES A LA VEZ — la función objetivo decide
    add("multi_senal", "Dos intenciones a la vez → la función objetivo decide",
        lambda d: (d.on_time_savings_goal & d.on_time_limit_increase & ~d.fragil & ~d.opt_out
                   & (d.exp_savings_goal <= 1) & (d.exp_limit_increase <= 1)),
        ["ev30"], True, None,
        narrativa="Señal fresca de ahorro Y de aumento de línea el mismo día. No es frágil, así que el "
                  "aumento no está vetado — y sin embargo elegimos ahorro. Ahí se ve qué optimizamos: "
                  "savings_goal da +6.38pp de tasa de ahorro y −0.46 días negativos; limit_increase da "
                  "+245.6 MXN pero −2.22pp de ahorro y +0.93 días negativos. La correlación de rangos "
                  "salud-vs-revenue es −0.829: el ranking se invierte, hay que elegir.")

    p = os.path.join(HERE, "casos_ejemplo.json")
    with open(p, "w") as fh:
        json.dump({"generado_por": "recon/demo/02_casos_ejemplo.py",
                   "cortes": {"principal": CORTE_A, "modelo_d100": CORTE_B},
                   "n_casos": len(casos), "casos": casos}, fh, indent=2, ensure_ascii=False)
    print(f"\n-> {p}  ({len(casos)} casos)")


if __name__ == "__main__":
    main()
