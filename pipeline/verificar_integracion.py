#!/usr/bin/env python3
"""ING-5 · Verificación de integración. El fallo más caro es el que no revienta.

Tres cosas degradan **en silencio** y ninguna lanza una excepción:

| Riesgo                                    | Comprobación                     |
|-------------------------------------------|----------------------------------|
| Los nombres de artefacto no coinciden      | contra `docs/arquitectura.md`    |
| El corte de `metadata.json` no es el demo  | `meta["corte"] == CORTE_DEMO`    |
| El POST responde con el fallback           | `respuesta["modelo"] == "v1"`    |

Y una cuarta que ING-9 exige a mano y aquí se automatiza: **recorrer los 9
escenarios curados** y confirmar que cada uno da la decisión que promete el guion.

    .venv/bin/python pipeline/verificar_integracion.py          # en proceso
    .venv/bin/python pipeline/verificar_integracion.py --url http://localhost:8000

Sale con **1** si algo no cuadra. Es criterio, no opinión: córrelo antes de
cada ensayo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__ in (None, ""):
    sys.path.insert(0, RAIZ)

from app.scoring import ARTEFACTOS, ARTIFACTS          # noqa: E402
from pipeline.mapas import CORTE_DEMO                   # noqa: E402

# Los nombres son ley: los produce otra área (docs/arquitectura.md).
ARTEFACTOS_OBLIGATORIOS = [
    ARTEFACTOS["modelo_intencion"],
    ARTEFACTOS["modelo_momento"],
    ARTEFACTOS["umbrales"],
    ARTEFACTOS["tabla_valor"],
    ARTEFACTOS["razones"],
    ARTEFACTOS["metadata"],
    ARTEFACTOS["demo_pack"],
    f"features_asof_{CORTE_DEMO}.parquet",
]

CLIENTE_ESTRELLA = 6016480          # frágil, señal fresca de línea, cupo libre
PUERTA_ESTRELLA = "S3_fragilidad"

VERDE, ROJO, GRIS, FIN = "\033[32m", "\033[31m", "\033[90m", "\033[0m"


class Resultado:
    def __init__(self):
        self.fallos = []
        self.avisos = []

    def ok(self, titulo, detalle=""):
        print(f"  {VERDE}✓{FIN} {titulo}{GRIS}{'  ' + detalle if detalle else ''}{FIN}")

    def falla(self, titulo, detalle=""):
        print(f"  {ROJO}✗{FIN} {titulo}{GRIS}{'  ' + detalle if detalle else ''}{FIN}")
        self.fallos.append(f"{titulo} · {detalle}".strip(" ·"))

    def avisa(self, titulo, detalle=""):
        print(f"  {GRIS}·{FIN} {titulo}{GRIS}{'  ' + detalle if detalle else ''}{FIN}")
        self.avisos.append(f"{titulo} · {detalle}".strip(" ·"))


# --------------------------------------------------------------------------
class ClienteEnProceso:
    """Levanta la app en memoria: sin puerto, sin red, con el lifespan real."""

    def __init__(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self._ctx = TestClient(app)
        self.c = self._ctx.__enter__()

    def get(self, ruta):
        r = self.c.get(ruta)
        return r.status_code, r.json()

    def post(self, ruta, cuerpo):
        r = self.c.post(ruta, json=cuerpo)
        return r.status_code, r.json()

    def cerrar(self):
        self._ctx.__exit__(None, None, None)


class ClienteHTTP:
    """Contra un servicio ya levantado. Mismo criterio, otro transporte."""

    def __init__(self, url):
        import httpx
        self.url = url.rstrip("/")
        self.c = httpx.Client(timeout=30.0)

    def get(self, ruta):
        r = self.c.get(self.url + ruta)
        return r.status_code, r.json()

    def post(self, ruta, cuerpo):
        r = self.c.post(self.url + ruta, json=cuerpo)
        return r.status_code, r.json()

    def cerrar(self):
        self.c.close()


# --------------------------------------------------------------------------
def verificar_artefactos(res):
    print("\n1 · Nombres de artefacto (docs/arquitectura.md)")
    for nombre in ARTEFACTOS_OBLIGATORIOS:
        ruta = os.path.join(ARTIFACTS, nombre)
        if os.path.exists(ruta):
            res.ok(nombre, f"{os.path.getsize(ruta):,} bytes")
        else:
            res.falla(nombre, "no está en pipeline/artifacts/")


def verificar_corte(res):
    print("\n2 · El corte de metadata.json es el del demo")
    ruta = os.path.join(ARTIFACTS, ARTEFACTOS["metadata"])
    if not os.path.exists(ruta):
        res.falla("metadata.json", f"no existe; el demo corre en {CORTE_DEMO}")
        return
    with open(ruta, encoding="utf-8") as fh:
        meta = json.load(fh)
    corte = meta.get("corte")
    if corte == CORTE_DEMO:
        res.ok("corte", f"{corte}")
    else:
        res.falla("corte", f"metadata declara {corte!r} != {CORTE_DEMO!r}")


def verificar_salud(res, cli):
    print("\n3 · /health")
    cod, h = cli.get("/health")
    if cod != 200:
        res.falla("/health", f"HTTP {cod}")
        return None
    res.ok("responde", f"nivel activo {h.get('modelo')}")
    if h.get("en_modelo"):
        res.ok("corre en modelo", "v1")
    else:
        res.falla("corre en fallback", json.dumps(h.get("escalera", {}).get("niveles_caidos", {}),
                                                  ensure_ascii=False))
    cob = h.get("cobertura") or {}
    if cob.get("pct_silencio") is None:
        res.falla("cobertura", "el contador de silencio no se calculó al arranque")
    else:
        res.ok("contador de silencio", f"{cob['pct_silencio']} % sobre {cob.get('n_clientes')} clientes")
    return h


def verificar_post(res, cli):
    print("\n4 · POST /api/decidir · el caso estrella")
    asof = f"{CORTE_DEMO}T12:00:00"
    cod, r = cli.post("/api/decidir", {"customer_id": CLIENTE_ESTRELLA, "asof": asof})
    if cod != 200:
        res.falla("POST", f"HTTP {cod} (debe ser 200 siempre)")
        return
    res.ok("HTTP 200", f"decisión {r.get('decision')}")

    modelo = r.get("modelo")
    if modelo == "v1":
        res.ok("modelo", "v1")
    else:
        res.falla("el POST está devolviendo fallback", f"modelo={modelo!r}")

    if r.get("puerta_reportada") == PUERTA_ESTRELLA:
        res.ok("prioridad de reporte", f"{CLIENTE_ESTRELLA} reporta {PUERTA_ESTRELLA}")
    else:
        res.falla("prioridad de reporte",
                  f"{CLIENTE_ESTRELLA} reporta {r.get('puerta_reportada')!r}, "
                  f"se esperaba {PUERTA_ESTRELLA!r}")

    if len(r.get("traza") or []) == 8:
        res.ok("traza", "8 puertas emitidas")
    else:
        res.falla("traza", f"{len(r.get('traza') or [])} filas, se esperaban 8")

    if r.get("silencios"):
        res.ok("silencios", f"{len(r['silencios'])} con código y razón")
    else:
        res.falla("silencios", "la respuesta no trae silencios")


def verificar_escenarios(res, cli):
    print("\n5 · Los 9 escenarios curados (ING-9, paso 3)")
    ruta = os.path.join(RAIZ, "pipeline", "artifacts", "casos_ejemplo.json")
    if not os.path.exists(ruta):
        res.falla("casos_ejemplo.json", "no está: el selector sería aleatorio")
        return
    with open(ruta, encoding="utf-8") as fh:
        casos = json.load(fh)["casos"]
    for c in casos:
        asof = str(c["ficha"]["decision"]["asof"]).replace(" ", "T")
        cod, r = cli.post("/api/decidir", {"customer_id": c["customer_id"], "asof": asof})
        esperado = c["decision"].get("nudge_type")
        obtenido = r["ofertas"][0]["producto"] if r.get("ofertas") else None
        etiqueta = f"{c['clave']} (#{c['customer_id']})"
        if cod != 200:
            res.falla(etiqueta, f"HTTP {cod}")
        elif obtenido == esperado:
            res.ok(etiqueta, f"{r.get('decision')} · {obtenido or r.get('puerta_reportada')}")
        else:
            res.falla(etiqueta, f"esperaba {esperado!r}, obtuvo {obtenido!r}")


# --------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description="ING-5 · verificación de integración")
    p.add_argument("--url", help="verificar contra un servicio ya levantado")
    args = p.parse_args(argv)

    print("=" * 72)
    print(f"nu-moments · verificación de integración · corte del demo {CORTE_DEMO}")
    print("=" * 72)

    res = Resultado()
    verificar_artefactos(res)
    verificar_corte(res)

    cli = ClienteHTTP(args.url) if args.url else ClienteEnProceso()
    try:
        salud = verificar_salud(res, cli)
        verificar_post(res, cli)
        verificar_escenarios(res, cli)
    finally:
        cli.cerrar()

    nivel = (salud or {}).get("modelo", "desconocido")
    print("\n" + "=" * 72)
    if res.fallos:
        print(f"{ROJO}FALLA{FIN} · {len(res.fallos)} comprobaciones no cuadran:")
        for f in res.fallos:
            print(f"  - {f}")
        print(f"\nEl servicio está sirviendo con el nivel {nivel!r}. "
              f"Hasta que esto esté en verde, la demo no está blindada.")
        return 1
    print(f"{VERDE}OK{FIN} · todo cuadra. La demo corre con el modelo v1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
