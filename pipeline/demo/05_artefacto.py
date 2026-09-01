"""
05_artefacto.py — Construye el artefacto precalculado que hace el demo instantáneo.

Produce dos cosas:
  1. demo_clientes.parquet  — UNA fila por (customer_id, corte) con todo lo que la
     política y el modelo necesitan ya agregado. Es la tabla de features as-of (C2)
     + la decisión de referencia. Se carga entera en RAM al arrancar la API.
  2. fichas_demo.json       — las fichas COMPLETAS (con timeline de eventos y
     movimientos) de una lista corta y curada de clientes: los casos del pitch
     + una muestra navegable para el selector del front.

Uso: /tmp/hackenv/bin/python 05_artefacto.py
"""
import json
import os
import time

import pandas as pd

from ficha import Store
from politica import decide

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
CORTES = ["2026-06-16", "2026-06-09", "2026-06-01"]
N_MUESTRA = 300     # clientes con ficha completa para el selector del front


def tabla_plana():
    """Concatena los scans por corte -> una fila por (customer_id, corte)."""
    partes = []
    for a in CORTES:
        p = os.path.join(OUT, f"scan_{a}.csv")
        if not os.path.exists(p):
            os.system(f'cd {HERE} && /tmp/hackenv/bin/python 01_scan_candidatos.py {a} >/dev/null')
        d = pd.read_csv(p)
        d.insert(1, "corte", a)
        partes.append(d)
    return pd.concat(partes, ignore_index=True)


def main():
    t0 = time.perf_counter()
    df = tabla_plana()
    p1 = os.path.join(OUT, "demo_clientes.parquet")
    df.to_parquet(p1, index=False, compression="zstd")
    print(f"-> {p1}")
    print(f"   {len(df):,} filas x {df.shape[1]} columnas ({len(CORTES)} cortes x 38,000 clientes)")
    print(f"   disco {os.path.getsize(p1)/1e6:.2f} MB   RAM {df.memory_usage(deep=True).sum()/1e6:.2f} MB")
    print(f"   construido en {time.perf_counter()-t0:.1f} s")

    # ---- fichas completas de una muestra curada ----
    st = Store()
    casos = json.load(open(os.path.join(HERE, "casos_ejemplo.json")))["casos"]
    cids_caso = {(c["customer_id"], c["corte"]) for c in casos}

    corte = CORTES[0]
    d0 = df[df.corte == corte].set_index("customer_id")
    # muestra navegable: mezcla de arquetipos para que el selector no sea aburrido
    con_senal = d0[d0.senal_fresca_alguna].index[:120]
    fragiles = d0[d0.fragil & d0.senal_7d_alguna].index[:60]
    fatig = d0[(d0.filter(like="exp_").max(axis=1) >= 3)].index[:60]
    silencio = d0[~d0.senal_7d_alguna].index[:60]
    muestra = list(dict.fromkeys(list(con_senal) + list(fragiles) + list(fatig) + list(silencio)))[:N_MUESTRA]

    t0 = time.perf_counter()
    fichas = {}
    for cid, c in cids_caso:
        fichas[f"{cid}|{c}"] = {"ficha": st.ficha(cid, c), "decision": None}
    for cid in muestra:
        k = f"{cid}|{corte}"
        if k not in fichas:
            fichas[k] = {"ficha": st.ficha(int(cid), corte), "decision": None}
    for k, v in fichas.items():
        v["decision"] = decide(v["ficha"])
    dt = time.perf_counter() - t0

    p2 = os.path.join(OUT, "fichas_demo.json")
    with open(p2, "w") as fh:
        json.dump(fichas, fh, ensure_ascii=False)
    print(f"\n-> {p2}")
    print(f"   {len(fichas)} fichas completas   disco {os.path.getsize(p2)/1e6:.2f} MB "
          f"({os.path.getsize(p2)/len(fichas)/1024:.1f} KB/ficha)   construido en {dt:.1f} s")

    # ---- índice ligero para el selector del front ----
    idx = []
    for k, v in fichas.items():
        f, dec = v["ficha"], v["decision"]
        p, s = f["perfil"], f["perfil"]["situacion_financiera"]
        idx.append({"key": k, "customer_id": p["customer_id"], "corte": f["decision"]["asof"][:10],
                    "edad": p["edad"], "estado": p["estado"], "banda_ingreso": p["banda_ingreso"],
                    "fragil": f["decision"]["es_fragil"],
                    "utilizacion": s["utilizacion_tarjeta_pct"],
                    "n_eventos_7d": f["navegacion"]["n_eventos_7d"],
                    "nudges_vistos": f["nudges"]["n_total"],
                    "decision": (dec.get("nudge_type") if dec["enviar"] else
                                 "silencio:" + str(dec["razon_silencio"]))})
    p3 = os.path.join(OUT, "indice_demo.json")
    with open(p3, "w") as fh:
        json.dump(idx, fh, ensure_ascii=False)
    print(f"-> {p3}   {len(idx)} filas   disco {os.path.getsize(p3)/1e3:.1f} KB")
    print("\ndistribución de decisiones en la muestra del selector:")
    print(pd.Series([r["decision"] for r in idx]).value_counts().to_string())


if __name__ == "__main__":
    main()
