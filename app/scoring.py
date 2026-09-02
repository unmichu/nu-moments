"""ING-4 · La escalera de fallback de tres niveles.

    U = p_intencion × p_enganche × V(λ)

1. **Modelo entrenado** (`modelo` = `v1`) — los `.pkl` de `pipeline/artifacts/`
   sobre la tabla de features as-of **del corte que pide la petición**.
2. **Regla de 24 h** (`modelo` = `regla_24h`) — si hay señal en la pantalla
   acoplada del producto en las últimas 24 h, hay intención. Acierta 63.45 %
   donde hay señal. **Es una línea del pitch, no una vergüenza.**
3. **Paquete precalculado** (`modelo` = `demo_pack`) — `demo_pack.json`.

Nada se sustituye en silencio: cada nivel deja escrito por qué no pudo ser el
anterior, y `/health` lo publica.

Y se puede degradar a propósito, sin tocar archivos: `NU_MOMENTS_NIVEL_MAX=demo_pack`
apaga los niveles por encima del que se nombra y lo deja escrito en `/health`.
"""
from __future__ import annotations

import glob
import json
import os
import re
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__ in (None, ""):
    import sys
    sys.path.insert(0, RAIZ)

from pipeline.mapas import (          # noqa: E402
    CATALOGO_DEMO,
    CORTE_DEMO,
    LAMBDA_DEFECTO,
    PRODUCTO_A_ACCION,
    PRODUCTO_A_PANTALLA,
)

ARTIFACTS = os.path.join(RAIZ, "pipeline", "artifacts")
RECON = os.path.join(RAIZ, "analytics", "recon", "out")

# Nombres de artefacto: son ley (docs/arquitectura.md). Otra área los produce.
ARTEFACTOS = {
    "modelo_intencion": "modelo_intencion.pkl",
    "modelo_momento": "modelo_momento.pkl",
    "umbrales": "umbrales.json",
    "tabla_valor": "tabla_valor.json",
    "razones": "razones.json",
    "metadata": "metadata.json",
    "demo_pack": "demo_pack.json",
}

# --------------------------------------------------------------------------
# Constantes del nivel 2. Todas reproducibles con analytics/recon/.
# --------------------------------------------------------------------------
# 07_policy_simulation.csv · P2 (solo on_time) y P3−P2 (solo warm).
TASA_ENGANCHE_POR_MOMENTO = {"on_time": 0.4163, "warm": 0.2127, "cold": 0.0, "never": 0.0}

# 04_fatigue_curve.csv · engaged_rel_vs_exp1, por número de exposición.
FATIGA_RELATIVA_DOC = {1: 1.0, 2: 0.499, 3: 0.224, 4: 0.112, 5: 0.045, 6: 0.0}

# 03_screen_action_p24h.csv / _p72h.csv · P(acción | pantalla vista), en %.
# Solo el catálogo de 4; se usa si los CSV de recon no están.
CONVERSION_DOC_24H = {"savings_goal": 49.39, "limit_increase": 30.57,
                      "loan_offer": 24.84, "bill_reminder": 56.81}
CONVERSION_DOC_72H = {"savings_goal": 72.82, "limit_increase": 47.45,
                      "loan_offer": 38.76, "bill_reminder": 82.72}


def _normalizar_tabla_valor(bruto, lmbda):
    """El artefacto publica `V_lambda_266` / `V_lambda_165`; la política pide `V`.

    Si el λ pedido no está tabulado se recalcula con la fórmula que el propio
    artefacto declara, en vez de caer a un valor por defecto.
    """
    productos = bruto.get("productos", bruto)
    peso = float(bruto.get("peso_ahorro", 0.3))
    escala = float(bruto.get("escala_ahorro_pp", 10.0))
    tabla = {}
    for nombre, e in productos.items():
        if not isinstance(e, dict):
            tabla[nombre] = {"V": float(e)}
            continue
        clave = f"V_lambda_{int(lmbda)}" if float(lmbda).is_integer() else None
        if "V" in e:
            v = float(e["V"])
        elif clave and clave in e:
            v = float(e[clave])
        elif {"delta_dias_negativos", "delta_ingreso_mxn", "delta_ahorro_pp"} <= set(e):
            v = (-float(e["delta_dias_negativos"])
                 + float(e["delta_ingreso_mxn"]) / float(lmbda)
                 + peso * float(e["delta_ahorro_pp"]) / escala)
        else:
            raise NivelNoDisponible(
                f"tabla_valor.json no permite obtener V para {nombre} con lambda={lmbda}")
        tabla[nombre] = {**e, "V": round(v, 4)}
    return tabla


class NivelNoDisponible(Exception):
    """El nivel no se pudo montar. Trae el motivo, que va a /health."""


# --------------------------------------------------------------------------
# Cortes: cómo se nombra una foto de features y cómo se elige la que toca
# --------------------------------------------------------------------------
PATRON_FEATURES = re.compile(r"^features_asof_(\d{4}-\d{2}-\d{2})\.parquet$")

# Niveles de la escalera, del mejor al peor. El orden es el de la degradación.
ORDEN_NIVELES = ["v1", "regla_24h", "demo_pack"]

# Interruptor explícito de degradación (ING-4). `NU_MOMENTS_NIVEL_MAX=demo_pack`
# apaga v1 y regla_24h para poder ensayar el nivel 3 sin corromper artefactos.
VAR_NIVEL_MAX = "NU_MOMENTS_NIVEL_MAX"


def nivel_max():
    """El nivel más alto que el entorno permite montar, o None si no hay tope."""
    valor = (os.environ.get(VAR_NIVEL_MAX) or "").strip()
    if not valor:
        return None
    if valor not in ORDEN_NIVELES:
        raise NivelNoDisponible(
            f"{VAR_NIVEL_MAX}={valor!r} no es un nivel: {', '.join(ORDEN_NIVELES)}")
    return valor


def fecha_de(asof, defecto=None):
    """`2026-06-09T12:00:00` / `2026-06-09 00:00:00` / date → `'2026-06-09'`."""
    if asof is None:
        return defecto
    texto = str(asof).strip()
    return texto[:10] if len(texto) >= 10 else defecto


def cortes_disponibles(directorio=None):
    """Los cortes con tabla de features en disco, ordenados. Se lee al arranque."""
    directorio = directorio or ARTIFACTS
    cortes = []
    for ruta in glob.glob(os.path.join(directorio, "features_asof_*.parquet")):
        m = PATRON_FEATURES.match(os.path.basename(ruta))
        if m:
            cortes.append(m.group(1))
    return sorted(cortes)


def corte_vigente(asof, cortes):
    """El corte que se puede usar para decidir en `asof`, o None.

    Coincidencia exacta si la hay; si no, el corte más reciente **anterior o
    igual**. Nunca uno posterior: eso sería mirar el futuro en tiempo de
    servicio, que es exactamente lo que `pipeline/tests/test_leakage.py`
    prohíbe en la construcción.
    """
    fecha = fecha_de(asof)
    if fecha is None:
        return None
    anteriores = [c for c in cortes if c <= fecha]
    return max(anteriores) if anteriores else None


# --------------------------------------------------------------------------
def _leer_json(nombre):
    p = os.path.join(ARTIFACTS, ARTEFACTOS[nombre])
    if not os.path.exists(p):
        raise NivelNoDisponible(f"falta {ARTEFACTOS[nombre]}")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _leer_csv_recon(nombre):
    """Lee un CSV de recon como {fila: {col: float}}. Sin pandas: es 10 líneas."""
    p = os.path.join(RECON, nombre)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        lineas = [l.rstrip("\n") for l in fh if l.strip()]
    cab = lineas[0].split(",")
    out = {}
    for l in lineas[1:]:
        celdas = l.split(",")
        fila = {}
        for k, v in zip(cab[1:], celdas[1:]):
            try:
                fila[k] = float(v)
            except ValueError:
                fila[k] = None
        out[celdas[0]] = fila
    return out


# ==========================================================================
# Nivel 2 · La regla de 24 h
# ==========================================================================
class ReglaVeinticuatroHoras:
    """Si hay señal en la pantalla acoplada del producto, hay intención.

    `p_intencion` es la conversión medida de esa pantalla a su acción acoplada
    (49.39 % ahorro · 30.57 % línea · 24.84 % préstamo, señal ≤24 h).
    `p_enganche` es la tasa de enganche por momento, atenuada por la curva de
    fatiga según la exposición que tocaría.
    """

    nombre = "regla_24h"

    def __init__(self, conv24, conv72, fatiga, origen):
        self.conv24 = conv24
        self.conv72 = conv72
        self.fatiga = fatiga
        self.origen = origen

    @classmethod
    def cargar(cls):
        p24 = _leer_csv_recon("03_screen_action_p24h.csv")
        p72 = _leer_csv_recon("03_screen_action_p72h.csv")
        fat = _leer_csv_recon("04_fatigue_curve.csv")
        if p24 and p72:
            conv24, conv72 = {}, {}
            for prod in CATALOGO_DEMO:
                pantalla = PRODUCTO_A_PANTALLA[prod]
                accion = PRODUCTO_A_ACCION[prod]
                conv24[prod] = p24[pantalla][accion] / 100.0
                conv72[prod] = p72[pantalla][accion] / 100.0
            origen = "analytics/recon/out/03_screen_action_p{24,72}h.csv"
        else:
            conv24 = {k: v / 100.0 for k, v in CONVERSION_DOC_24H.items()}
            conv72 = {k: v / 100.0 for k, v in CONVERSION_DOC_72H.items()}
            origen = "constantes documentadas (instrucciones/ba.md); faltan los CSV de recon"

        if fat:
            fatiga = {}
            for k, fila in fat.items():
                try:
                    fatiga[int(k.rstrip("+"))] = float(fila["engaged_rel_vs_exp1"])
                except (ValueError, KeyError, TypeError):
                    continue
            fatiga = fatiga or dict(FATIGA_RELATIVA_DOC)
        else:
            fatiga = dict(FATIGA_RELATIVA_DOC)
            origen += " + curva de fatiga documentada"
        return cls(conv24, conv72, fatiga, origen)

    def scores(self, ficha, tabla_valor):
        out = {}
        for prod in CATALOGO_DEMO:
            s = ficha["decision"]["senales_por_nudge"][prod]
            momento = s["momento"]
            if momento == "on_time":
                p_int = self.conv24.get(prod, 0.0)
            elif momento == "warm":
                # La masa que llega DESPUÉS de las primeras 24 h. Usar p72 tal
                # cual compararía una probabilidad acumulada a 72 h contra una a
                # 24 h y una señal tibia acabaría ganándole a una fresca.
                p_int = max(0.0, self.conv72.get(prod, 0.0) - self.conv24.get(prod, 0.0))
            else:
                p_int = 0.0
            exp = int(s["exposure_no_siguiente"])
            rel = self.fatiga.get(exp, 0.0)
            p_eng = TASA_ENGANCHE_POR_MOMENTO.get(momento, 0.0) * rel
            v = float(tabla_valor[prod]["V"]) if prod in tabla_valor else 0.0
            out[prod] = {
                "p_intencion": round(p_int, 4),
                "p_enganche": round(p_eng, 4),
                "V": round(v, 4),
                "score": round(p_int * p_eng * v, 6),
                "confianza": round(p_int * p_eng, 4),
                "explicacion": "regla",
            }
        return out


# ==========================================================================
# Nivel 1 · Los modelos entrenados
# ==========================================================================
class ModeloEntrenado:
    """Modelo X (intención) × Modelo Y (momento) × tabla de valor.

    El contrato de los `.pkl` lo produce analítica (BA-5). Se acepta cualquiera
    de las formas razonables y, si ninguna encaja, se declara el nivel caído con
    el motivo escrito en vez de inventar un score.

    **Una foto de features por corte, elegida por el `asof` de la petición.**
    Servir siempre la tabla del corte del demo era fuga temporal en caliente: el
    caso `multi_senal` se decide el 2026-06-09 y su `p_intencion` salía de una
    foto tomada 7 días después de la decisión que se enseña en pantalla. Ahora
    se toma la tabla del corte exacto y, si no lo hay, la más reciente
    **anterior o igual**; nunca una posterior. Si no existe ninguna válida el
    nivel se declara no disponible para esa petición y la escalera baja, con el
    motivo escrito y publicado en `/health`.

    Las tablas se leen **en el arranque**, todas de una vez: por petición no se
    toca el disco (docs/arquitectura.md).
    """

    nombre = "v1"

    def __init__(self, intencion, momento, umbrales, tablas, columnas, meta,
                 corte_defecto=CORTE_DEMO):
        self.intencion = intencion
        self.momento = momento
        self.umbrales = umbrales
        self.tablas = tablas                 # {corte: DataFrame indexado por cliente}
        self.columnas = columnas
        self.meta = meta
        self.corte_defecto = corte_defecto

    # -- compatibilidad: la tabla del corte del demo sigue siendo `.features` --
    @property
    def features(self):
        return self.tablas[self.corte_defecto]

    @property
    def cortes(self):
        return sorted(self.tablas)

    @classmethod
    def cargar(cls, corte=CORTE_DEMO):
        try:
            import joblib
        except ImportError as e:                       # pragma: no cover
            raise NivelNoDisponible(f"joblib no disponible: {e}")

        meta = _leer_json("metadata")
        corte_meta = meta.get("corte")
        if corte_meta != corte:
            raise NivelNoDisponible(
                f"metadata.json declara corte {corte_meta!r}, el demo corre en {corte!r}")

        for k in ("modelo_intencion", "modelo_momento"):
            p = os.path.join(ARTIFACTS, ARTEFACTOS[k])
            if not os.path.exists(p):
                raise NivelNoDisponible(f"falta {ARTEFACTOS[k]}")
        intencion = joblib.load(os.path.join(ARTIFACTS, ARTEFACTOS["modelo_intencion"]))
        momento = joblib.load(os.path.join(ARTIFACTS, ARTEFACTOS["modelo_momento"]))
        umbrales = _leer_json("umbrales")

        disponibles = cortes_disponibles()
        if corte not in disponibles:
            raise NivelNoDisponible(f"falta features_asof_{corte}.parquet")

        import pandas as pd
        declaradas = intencion.get("features") if isinstance(intencion, dict) else None
        tablas, columnas = {}, None
        for c in disponibles:
            t = pd.read_parquet(
                os.path.join(ARTIFACTS, f"features_asof_{c}.parquet")).set_index("customer_id")
            if declaradas:
                faltan = [col for col in declaradas if col not in t.columns]
                if faltan:
                    if c != corte:
                        # una foto vieja e incompleta no tumba el nivel: se
                        # descarta y se dice en /health por su ausencia.
                        continue
                    raise NivelNoDisponible(
                        f"la tabla de features no trae {len(faltan)} columnas del modelo: "
                        f"{', '.join(faltan[:5])}")
                cols = list(declaradas)      # el orden lo manda el artefacto
            else:
                cols = [col for col in t.columns if not str(col).startswith("customer_id")]
            if columnas is None:
                columnas = cols
            tablas[c] = t

        cabezas = cls._cabezas(intencion)
        faltan = [p for p in CATALOGO_DEMO if PRODUCTO_A_ACCION[p] not in cabezas]
        if faltan:
            raise NivelNoDisponible(
                f"modelo_intencion.pkl no trae cabeza para: {', '.join(faltan)}")
        return cls(intencion, momento, umbrales, tablas, columnas, meta, corte)

    # ----------------------------------------------------------------------
    def corte_para(self, asof):
        """El corte que se usará para `asof`. Nunca uno posterior."""
        return corte_vigente(asof, self.cortes)

    def tabla_para(self, asof):
        """(corte, tabla) para el `asof` pedido, o `NivelNoDisponible` con motivo."""
        fecha = fecha_de(asof)
        if fecha is None:
            raise NivelNoDisponible(
                "la ficha no trae `asof`: sin corte no se puede elegir foto de features")
        c = corte_vigente(fecha, self.cortes)
        if c is None:
            raise NivelNoDisponible(
                f"no hay tabla de features en {fecha} ni antes "
                f"(la más antigua es {self.cortes[0]}): usar una posterior sería fuga temporal")
        return c, self.tablas[c]

    @staticmethod
    def _cabezas(objeto):
        """Localiza el diccionario accion -> estimador dentro del artefacto."""
        if isinstance(objeto, dict):
            for clave in ("arbol", "cabezas", "heads", "modelos", "models"):
                if clave in objeto and isinstance(objeto[clave], dict):
                    return objeto[clave]
            if any(hasattr(v, "predict_proba") for v in objeto.values()):
                return {k: v for k, v in objeto.items() if hasattr(v, "predict_proba")}
        return {}

    def scores(self, ficha, tabla_valor):
        cid = ficha["perfil"]["customer_id"]
        corte, feats = self.tabla_para(ficha.get("decision", {}).get("asof"))
        if cid not in feats.index:
            raise NivelNoDisponible(
                f"el cliente {cid} no está en la tabla de features de {corte}")
        x = feats.loc[[cid], self.columnas]
        cabezas = self._cabezas(self.intencion)
        out = {}
        for prod in CATALOGO_DEMO:
            accion = PRODUCTO_A_ACCION[prod]
            p_int = float(cabezas[accion].predict_proba(x)[0][1])
            p_eng = self._p_enganche(ficha, prod)
            v = float(tabla_valor[prod]["V"]) if prod in tabla_valor else 0.0
            out[prod] = {
                "p_intencion": round(p_int, 4),
                "p_enganche": round(p_eng, 4),
                "V": round(v, 4),
                "score": round(p_int * p_eng * v, 6),
                "confianza": round(p_int * p_eng, 4),
                "explicacion": "modelo",
                "corte_features": corte,
            }
        return out

    def _p_enganche(self, ficha, prod):
        """Modelo Y · 2 variables: estado de señal y número de exposición."""
        import pandas as pd
        s = ficha["decision"]["senales_por_nudge"][prod]
        # El orden ordinal es el de pipeline/features.py: cuanto más bajo, más fresca.
        estado = {"on_time": 0, "warm": 1, "cold": 2, "never": 3}[s["momento"]]
        variables = (self.momento.get("variables") if isinstance(self.momento, dict)
                     else None) or ["senal", "exposure_no"]
        valores = {"senal": estado, "exposure_no": int(s["exposure_no_siguiente"])}
        x = pd.DataFrame([[float(valores[v]) for v in variables]], columns=variables)
        modelo = self.momento
        if isinstance(modelo, dict):
            modelo = (modelo.get("pipeline") or modelo.get("modelo")
                      or modelo.get("model") or modelo.get("momento"))
        if modelo is None or not hasattr(modelo, "predict_proba"):
            raise NivelNoDisponible("modelo_momento.pkl no expone predict_proba")
        return float(modelo.predict_proba(x)[0][1])


# ==========================================================================
# Nivel 3 · Paquete precalculado
# ==========================================================================
class PaquetePrecalculado:
    """`demo_pack.json`, indexado por la pareja **(customer_id, asof)**.

    Indexar solo por cliente hacía que el nivel 3 mintiera: el paquete se
    construyó a un único corte y el caso `multi_senal` se decide el 2026-06-09,
    así que el fallback devolvía los números de otro día —la misma oferta con
    otros scores—. Ahora cada corte tiene su propio bloque.

    Retrocompatible: un `customer_id` con un `asof` que el paquete no conoce
    (o un paquete viejo, plano) resuelve al corte del demo.
    """

    nombre = "demo_pack"

    def __init__(self, pack):
        self.pack = pack
        self.corte_defecto = pack.get("corte") or CORTE_DEMO
        self.por_corte = pack.get("clientes_por_corte") or {}
        # el bloque plano `clientes` es el del corte por defecto
        self.planos = pack.get("clientes") or pack.get("customers") or {}

    @classmethod
    def cargar(cls):
        return cls(_leer_json("demo_pack"))

    @property
    def cortes(self):
        return sorted(set(self.por_corte) | ({self.corte_defecto} if self.planos else set()))

    def _bloque(self, corte):
        if corte in self.por_corte:
            return self.por_corte[corte]
        return self.planos if corte == self.corte_defecto else {}

    def entrada(self, cid, asof):
        """(entrada, corte) para (cliente, asof). `asof` desconocido → corte del demo."""
        pedido = fecha_de(asof)
        corte = pedido if pedido in set(self.cortes) else self.corte_defecto
        entrada = self._bloque(corte).get(str(cid))
        if entrada is None:
            raise NivelNoDisponible(
                f"el cliente {cid} no está en demo_pack.json para el corte {corte}")
        return entrada, corte

    def scores(self, ficha, tabla_valor):
        cid = str(ficha["perfil"]["customer_id"])
        entrada, corte = self.entrada(cid, ficha.get("decision", {}).get("asof"))
        crudos = entrada.get("scores", entrada)
        out = {}
        for prod in CATALOGO_DEMO:
            v = float(tabla_valor[prod]["V"]) if prod in tabla_valor else 0.0
            s = crudos.get(prod)
            if isinstance(s, dict):
                out[prod] = {**s, "V": round(v, 4), "explicacion": "paquete",
                             "corte_features": corte}
                out[prod].setdefault("score", 0.0)
                out[prod].setdefault("confianza", out[prod]["score"])
            else:
                sc = float(s or 0.0)
                out[prod] = {"p_intencion": None, "p_enganche": None, "V": round(v, 4),
                             "score": sc, "confianza": sc, "explicacion": "paquete",
                             "corte_features": corte}
        return out


# ==========================================================================
class Escalera:
    """Los tres niveles montados al arranque, en orden, con sus motivos."""

    def __init__(self, niveles, motivos, tabla_valor, origen_tabla_valor, lmbda,
                 tope=None):
        self.niveles = niveles              # lista [(nombre, objeto)]
        self.motivos = motivos              # {nivel: por qué no está}
        self.tabla_valor = tabla_valor
        self.origen_tabla_valor = origen_tabla_valor
        self.lmbda = lmbda
        self.tope = tope                    # NU_MOMENTS_NIVEL_MAX, si lo hay
        self.descensos = {}                 # {nivel: por qué bajó en la última petición}

    @property
    def nivel_activo(self):
        return self.niveles[0][0] if self.niveles else "degradado"

    @classmethod
    def cargar(cls, store, corte=CORTE_DEMO, lmbda=LAMBDA_DEFECTO):
        t0 = time.perf_counter()

        # tabla de valor: artefacto si existe; si no, la aritmética determinista
        # sobre los datos. Las dos son medidas, ninguna es un valor por defecto.
        try:
            bruto = _leer_json("tabla_valor")
            tabla = _normalizar_tabla_valor(bruto, lmbda)
            origen_tv = f"artefacto {ARTEFACTOS['tabla_valor']}"
        except NivelNoDisponible as e:
            tabla = store.tabla_valor(lmbda=lmbda)
            origen_tv = f"calculada de data/ ({e}); λ={lmbda}"

        # Degradación a propósito: `NU_MOMENTS_NIVEL_MAX=demo_pack` apaga los
        # niveles por encima del que se nombra. Es la única forma comprobable de
        # ensayar el nivel 3 sin corromper un artefacto (ING-4).
        tope = nivel_max()
        desde = ORDEN_NIVELES.index(tope) if tope else 0

        niveles, motivos = [], {}
        for i, clase in enumerate((ModeloEntrenado, ReglaVeinticuatroHoras,
                                   PaquetePrecalculado)):
            if i < desde:
                motivos[clase.nombre] = f"apagado por {VAR_NIVEL_MAX}={tope}"
                continue
            try:
                if clase is ModeloEntrenado:
                    niveles.append((clase.nombre, clase.cargar(corte=corte)))
                else:
                    niveles.append((clase.nombre, clase.cargar()))
            except NivelNoDisponible as e:
                motivos[clase.nombre] = str(e)
            except Exception as e:                        # pragma: no cover
                motivos[clase.nombre] = f"{type(e).__name__}: {e}"

        esc = cls(niveles, motivos, tabla, origen_tv, lmbda, tope)
        from pipeline.ingesta import registrar_evidencia
        registrar_evidencia("scoring.escalera", len(niveles) + len(motivos), len(niveles), t0,
                            nivel_activo=esc.nivel_activo, motivos=motivos,
                            origen_tabla_valor=origen_tv, tope=tope)
        return esc

    def puntuar(self, ficha):
        """Devuelve (scores, nombre_del_nivel). Baja de nivel al primer fallo.

        Un nivel puede caerse **en la petición** y no en el arranque: es lo que
        pasa cuando no hay tabla de features vigente para el `asof` pedido. Ese
        motivo se guarda en `descensos` para que `/health` lo publique en vez de
        perderse en el camino.
        """
        errores = []
        for nombre, nivel in self.niveles:
            try:
                scores = nivel.scores(ficha, self.tabla_valor)
            except Exception as e:
                motivo = f"{type(e).__name__}: {e}"
                errores.append(f"{nombre}: {motivo}")
                self.descensos[nombre] = motivo
                continue
            self.descensos.pop(nombre, None)
            return scores, nombre
        raise NivelNoDisponible("ningún nivel pudo puntuar · " + " | ".join(errores)
                                + " | ".join(f"{k}: {v}" for k, v in self.motivos.items()))

    def estado(self):
        v1 = next((nv for n, nv in self.niveles if n == "v1"), None)
        pack = next((nv for n, nv in self.niveles if n == "demo_pack"), None)
        return {
            "nivel_activo": self.nivel_activo,
            "niveles_montados": [n for n, _ in self.niveles],
            "niveles_caidos": self.motivos,
            "tabla_valor_origen": self.origen_tabla_valor,
            "lambda": self.lmbda,
            "detalle_regla_24h": next(
                (nv.origen for n, nv in self.niveles if n == "regla_24h"), None),
            # Qué fotos as-of hay cargadas y con cuál se sirve cada corte.
            "cortes_features": v1.cortes if v1 else [],
            "corte_features_defecto": v1.corte_defecto if v1 else None,
            "cortes_demo_pack": pack.cortes if pack else [],
            # Por qué un nivel bajó en la última petición (p. ej. un `asof`
            # anterior a la foto más antigua). No se pierde: se publica.
            "descensos_en_peticion": dict(self.descensos),
            "nivel_max": self.tope,
        }
