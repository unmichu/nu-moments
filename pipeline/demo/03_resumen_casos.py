"""03_resumen_casos.py — Imprime el resumen humano de cada caso (numeros reales)
   para pegar en la documentacion y en el pitch."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, "casos_ejemplo.json")))
for c in d["casos"]:
    f, dec = c["ficha"], c["decision"]
    p, sf, dcs = f["perfil"], f["perfil"]["situacion_financiera"], f["decision"]
    print("="*100)
    print(f"[{c['clave']}] cid={c['customer_id']}  corte={c['corte']}  — {c['titulo']}")
    print(f"  perfil: {p['edad']}a {p['estado']} · {p['banda_ingreso']} · ingreso {p['ingreso_mensual_est_mxn']:.0f} "
          f"· antig {p['antiguedad_meses']}m · payday d{p['dia_de_pago']} (a {dcs['dias_a_payday']}d)")
    print(f"  productos: " + ", ".join(k for k,v in p["productos"].items() if v) or "  productos: ninguno")
    print(f"  finanzas: util {sf['utilizacion_tarjeta_pct']}% · dias_neg {sf['dias_en_negativo_90d']} "
          f"· ahorro90d {sf['tasa_ahorro_90d_pct']}% · saldo {sf['saldo_promedio_mxn']:.0f} · NPS {sf['nps_ultimo']}"
          f"  || FRAGIL={dcs['es_fragil']} {dcs['motivo_fragilidad']}")
    print(f"  actividad: {f['navegacion']['n_eventos_24h']} ev/24h, {f['navegacion']['n_eventos_7d']} ev/7d, "
          f"{f['movimientos']['n_total_historico']} acciones hist; nudges vistos {f['nudges']['n_total']}, opt_out={f['nudges']['opt_out']}")
    print("  senales:")
    for t, s in dcs["senales_por_nudge"].items():
        if s["momento"] in ("on_time", "warm") or s["exposure_no_siguiente"] > 1:
            print(f"    {t:22s} {s['momento']:8s} h={s['horas_desde_senal']}  start24={s['hubo_start_24h']}  "
                  f"exp_prox={s['exposure_no_siguiente']} cupo_agotado={s['cupo_agotado']}")
    print(f"  ultimas pantallas: " + " | ".join(f"{e['ts'][5:16]} {e['pantalla']}/{e['accion']}"
                                                for e in f["navegacion"]["ultimas_pantallas"][:5]))
    print(f"  >> DECISION: {'ENVIAR ' + str(dec.get('nudge_type')) + ' (' + str(dec.get('surface')) + ', boton: ' + str(dec.get('etiqueta_boton')) + ')' if dec['enviar'] else 'SILENCIO / ' + str(dec['razon_silencio'])}"
          + (f"  [sustituye a {dec['sustituye_a']}]" if dec.get("sustituye_a") else ""))
    print(f"  >> LEYENDA UI: {dec['leyenda']}")
