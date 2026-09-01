"""
politica.py — Implementación de referencia del contrato C5:
    decide(ficha) -> {enviar, nudge_type, surface, razon, razon_silencio}

Reglas (todas ancladas en CONTEXTO.md §3):
  R1 cap de exposición = 2 por tipo         (§3.2: exp.3 ya da 0.72 opt-outs por enganche)
  R2 momento: solo on_time (<=24h) o warm   (§3.1: 41.6% vs 10.1%)
  R3 veto limit_increase a frágiles         (§3.4: +17.52pp utilización, +2.06 días negativos)
     -> si hay señal de limit_increase en un frágil, SUSTITUIR por bill_reminder/savings_goal
  R4 opt-out previo = silencio absoluto
  R5 superficie: in_app_modal               (§3.11: +4.64pp sobre push, mismo opt-out)
"""

PRIORIDAD_SALUD = ["savings_goal", "bill_reminder", "payroll_portability",
                   "invest_start", "loan_offer", "limit_increase"]

ETIQUETA = {
    "savings_goal": "Crear una Cajita",
    "limit_increase": "Aumentar tu línea",
    "loan_offer": "Simular un préstamo",
    "bill_reminder": "Programar tu pago",
    "invest_start": "Empezar a invertir",
    "payroll_portability": "Traer tu nómina",
}
PANTALLA_ES = {
    "savings_cajita": "Cajitas", "loan_simulation": "simulador de préstamo",
    "limit_increase": "aumento de línea", "bill_payment": "pago de servicios",
    "investments": "inversiones", "home": "inicio", "transfer_spei": "transferencias",
    "card_statement": "estado de cuenta", "support": "ayuda", "card_settings": "ajustes de tarjeta",
}


def decide(f):
    d = f["decision"]
    nud = f["nudges"]

    if nud["opt_out"]:
        return {"enviar": False, "nudge_type": None, "surface": None,
                "razon_silencio": "opt_out",
                "leyenda": "Este cliente desactivó las notificaciones. No le hablamos."}

    cand = []
    for t, s in d["senales_por_nudge"].items():
        if s["momento"] not in ("on_time", "warm"):
            continue
        if s["cupo_agotado"]:
            continue
        cand.append((t, s))

    # R3 · veto duro
    vetados = []
    for t, s in list(cand):
        if t == "limit_increase" and d["es_fragil"]:
            cand.remove((t, s))
            vetados.append((t, s))

    if not cand:
        # ¿por qué nos callamos?
        hay_senal = any(s["momento"] in ("on_time", "warm")
                        for s in d["senales_por_nudge"].values())
        if vetados:
            razon = "veto_fragilidad"
            leyenda = ("Detectamos que quiere ampliar su línea, pero " +
                       " y ".join(d["motivo_fragilidad"]) +
                       ". Ofrecerle más crédito hoy le costaría días en descubierto mañana. Nos callamos.")
        elif hay_senal:
            razon = "cupo_agotado"
            # ¿en qué tipo tiene la señal y cuántas veces ya lo vio?
            t_sig = next(t for t, s in d["senales_por_nudge"].items()
                         if s["momento"] in ("on_time", "warm"))
            n_vistas = nud["por_tipo"][t_sig]["exposiciones"]
            leyenda = (f"Tiene la intención ({ETIQUETA[t_sig].lower()}), pero ya vio ese mensaje "
                       f"{n_vistas} veces. La 3ª exposición convierte 3.51% y provoca 2.53% de opt-out "
                       f"—0.72 bajas por cada clic—. El cupo es 2: gastaríamos al cliente, no el cupo.")
        else:
            razon = "sin_senal"
            leyenda = ("No hay ninguna señal fresca de intención en la app. "
                       "Sin señal el enganche cae a 10%: hoy el asistente permanece en silencio.")
        return {"enviar": False, "nudge_type": None, "surface": None,
                "razon_silencio": razon, "leyenda": leyenda, "vetados": [t for t, _ in vetados]}

    # ordenar: on_time antes que warm, luego prioridad de salud
    cand.sort(key=lambda x: (0 if x[1]["momento"] == "on_time" else 1,
                             PRIORIDAD_SALUD.index(x[0])))
    t, s = cand[0]
    scr = PANTALLA_ES.get(s["pantalla_acoplada"], s["pantalla_acoplada"])
    h = s["horas_desde_senal"]
    if s["momento"] == "on_time":
        cuando = f"hace {h:.0f} h" if h >= 1 else "hace menos de una hora"
    else:
        cuando = f"hace {h/24:.0f} días"

    ley = f"Entró a {scr} {cuando}"
    if s["hubo_start_24h"]:
        ley += " y llegó a iniciar el flujo"
    ley += f". Es su exposición #{s['exposure_no_siguiente']} de 2 a este mensaje."
    if d["ventana_payday"]:
        ley += f" Además está a {d['dias_a_payday']} días de su día de pago, cuando esa acción es hasta 5x más probable."
    if vetados:
        ley += " Sustituimos el aumento de línea, que hoy le haría daño."

    return {"enviar": True, "nudge_type": t, "surface": "in_app_modal",
            "etiqueta_boton": ETIQUETA[t], "momento": s["momento"],
            "razon_silencio": None, "leyenda": ley,
            "sustituye_a": "limit_increase" if vetados else None}
