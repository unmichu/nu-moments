"""ING-6 · El panorama: la población detrás de cada número de la pantalla.

Un score de `0.03007` no dice nada. Este módulo calcula, **al arranque y una vez
por corte**, la población contra la que ese número se compara:

* la **cobertura** (`politica.cobertura`) — cuánta gente recibe aviso ese día;
* la **tasa base observada** de cada acción en ese corte, leída de
  `labels_intent.parquet` (la fracción de los 38,000 que efectivamente hizo la
  acción en la ventana de etiqueta). No es una estimación: es el conteo;
* la **tasa base de enganche** de cada tipo de aviso, leída de `nudges` con
  corte estricto `shown_ts < asof`;
* la **distribución completa** de `p_intencion` y de `score` sobre los 38,000
  clientes, para poder decir en qué percentil cae uno concreto **y para dibujar
  el histograma con la posición del cliente marcada**;
* la **curva de fatiga** de ese corte —enganche y bajas por número de
  exposición— contada sobre `nudges` con corte estricto `shown_ts < asof`;
* qué **ofrecería el sistema a cada cliente** (o por qué se callaría), que es lo
  que hace posible filtrar el selector por tipo de oferta.

Nada de esto se escribe a mano. Si un insumo falta, la vista se declara caída
con el motivo escrito y `/health` lo publica; nunca se sustituye en silencio.

Coste medido: ~0.2 s por corte (5 cortes ≈ 1 s), todo dentro del `lifespan`.
"""
from __future__ import annotations

import os
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__ in (None, ""):                                   # pragma: no cover
    import sys
    sys.path.insert(0, RAIZ)

from pipeline import politica                                    # noqa: E402
from pipeline.mapas import (                                     # noqa: E402
    CATALOGO_DEMO,
    PRODUCTO_A_ACCION,
)

ARTIFACTS = os.path.join(RAIZ, "pipeline", "artifacts")
LABELS_INTENCION = os.path.join(ARTIFACTS, "labels_intent.parquet")

HORA_PANORAMA = "T12:00:00"

# El código con el que se etiqueta a quien no recibe nada. No es una puerta:
# es la ausencia de oferta, y por eso lleva nombre propio.
SILENCIO = "silencio"

# Cubos del histograma de la distribución. 22 caben en 320 px de ancho con
# barras de 3 px y 1 px de hueco, que es el móvil más estrecho que soportamos.
BINS_DISTRIBUCION = 22

# La curva de fatiga solo publica las exposiciones con base suficiente para no
# leer ruido. El umbral es explícito y viaja en la respuesta.
MIN_AVISOS_POR_EXPOSICION = 200


class PanoramaNoDisponible(Exception):
    """Falta un insumo para construir la vista. Trae el motivo, que va a /health."""


def _percentil(ordenado, valor):
    """Qué porcentaje de la población queda **estrictamente por debajo**.

    Es la lectura que se le enseña al usuario ("supera al XX.XX % de los
    clientes evaluados a este corte"), así que se define una sola vez aquí.
    """
    import numpy as np

    if valor is None or ordenado is None or len(ordenado) == 0:
        return None
    pos = int(np.searchsorted(ordenado, float(valor), side="left"))
    return round(100.0 * pos / len(ordenado), 2)


def _posicion(ordenado, valor):
    """El percentil **y los dos conteos** que lo respaldan.

    El percentil solo es creíble si se puede decir cuánta gente hay a cada
    lado: «percentil 99.52 %» y «182 de 38 000 tienen un valor más alto» son la
    misma frase, pero la segunda se puede comprobar contando.

    `valor` tiene que ser el valor **sin redondear** del cliente. Con el valor
    redondeado el conteo se descuadra por uno: el propio cliente vive en
    `ordenado` con todos sus decimales, así que si se le redondea hacia abajo
    (0.38691688 → 0.3869) él mismo pasa a estar «por encima» de sí mismo y
    `n_encima` sale 623 donde hay 622. Por eso las vistas resuelven el valor
    exacto del cliente en la población antes de llamar aquí.
    """
    import numpy as np

    if valor is None or ordenado is None or len(ordenado) == 0:
        return None
    n = int(len(ordenado))
    debajo = int(np.searchsorted(ordenado, float(valor), side="left"))
    encima = int(n - np.searchsorted(ordenado, float(valor), side="right"))
    return {"percentil": round(100.0 * debajo / n, 2),
            "n_total": n, "n_debajo": debajo, "n_encima": encima}


def _mismo_numero(exacto, publicado, minimo_decimales=4):
    """¿`publicado` es `exacto` redondeado para la pantalla, o es otra cifra?

    `publicado` llega redondeado (4 decimales en `p_intencion`, 6 en el
    `score`); la comparación se hace con los decimales que ese número traiga,
    nunca con menos de `minimo_decimales`.
    """
    import decimal

    try:
        dec = -decimal.Decimal(repr(float(publicado))).as_tuple().exponent
    except (ValueError, ArithmeticError):                      # pragma: no cover
        dec = minimo_decimales
    dec = max(int(dec), minimo_decimales)
    return round(float(exacto), dec) == round(float(publicado), dec)


def _histograma_log(ordenado, valor, marcas=None, bins=BINS_DISTRIBUCION):
    """El histograma de la población en escala **logarítmica**, con marcas.

    La escala es logarítmica porque la distribución lo exige, no por gusto: en
    `savings_goal` la mediana de `p_intencion` es 3.19 % y el máximo 87.54 %, así
    que con cubos de ancho constante el 97 % de los 38,000 cae en el primero y
    el dibujo no dice nada. En log10 la misma población ocupa todo el eje y se
    ve de verdad dónde está el cliente.

    Devuelve los cubos con su altura relativa, el cubo del cliente y la posición
    (0–100 sobre el eje) de cada marca de referencia que se pida —la mediana, la
    tasa base, el propio cliente—, para que la plantilla no tenga que calcular.
    """
    import numpy as np

    if ordenado is None or len(ordenado) == 0:
        return None
    positivos = ordenado[ordenado > 0]
    if not len(positivos):
        return None
    piso, techo = float(positivos[0]), float(ordenado[-1])
    if techo <= piso:
        return None
    a, b = float(np.log10(piso)), float(np.log10(techo))

    bordes = np.logspace(a, b, bins + 1)
    # El primer cubo recoge también los ceros exactos; el último, el máximo.
    bordes[0] = min(float(ordenado[0]), piso)
    bordes[-1] = techo * (1.0 + 1e-9)
    cuentas, _ = np.histogram(ordenado, bins=bordes)
    alto = int(cuentas.max()) or 1

    def eje(v):
        """Dónde cae un valor en el eje, en porcentaje de 0 a 100."""
        if v is None:
            return None
        x = max(min(float(v), techo), piso)
        return round(100.0 * (float(np.log10(x)) - a) / (b - a), 2)

    cubos = [{"desde": round(float(bordes[i]), 6),
              "hasta": round(float(bordes[i + 1]), 6),
              "n": int(cuentas[i]),
              "alto_pct": round(100.0 * int(cuentas[i]) / alto, 2)}
             for i in range(bins)]

    cubo_cliente = None
    if valor is not None:
        cubo_cliente = int(np.clip(np.searchsorted(bordes, float(valor), side="right") - 1,
                                   0, bins - 1))

    mediana = round(float(np.median(ordenado)), 6)
    # La mediana siempre se marca: sin ella el eje no tiene punto de apoyo.
    referencias = {"mediana": mediana}
    referencias.update(marcas or {})

    return {
        "escala": "log10",
        "bins": cubos,
        "n_bins": bins,
        "bin_cliente": cubo_cliente,
        "minimo": round(float(ordenado[0]), 6),
        "maximo": round(techo, 6),
        "mediana": mediana,
        "n_total": int(len(ordenado)),
        "marcas": [{"clave": k, "valor": v, "pos_pct": eje(v)}
                   for k, v in referencias.items() if v is not None],
    }


# ==========================================================================
class VistaCorte:
    """Todo lo que se sabe de la población de los 38,000 en **un** corte."""

    def __init__(self, corte, asof, cobertura, idx, oferta, puerta,
                 p_intencion, score, tasa_base_intencion, tasa_base_enganche,
                 origen_orden, curva_fatiga=None,
                 p_intencion_por_cliente=None, score_por_cliente=None):
        self.corte = corte
        self.asof = asof
        self.cobertura = cobertura
        self.idx = idx
        self.oferta = oferta                 # array objeto: producto | SILENCIO
        self.puerta = puerta                 # array objeto: código de puerta | None
        self.p_intencion = p_intencion       # {producto: array ordenado}
        self.score = score                   # {producto: array ordenado}
        # Los mismos valores **sin ordenar y sin redondear**, alineados con
        # `idx`: son los que permiten contar contra el valor exacto de un
        # cliente en vez de contra el que se publica ya redondeado.
        self.p_intencion_por_cliente = p_intencion_por_cliente or {}
        self.score_por_cliente = score_por_cliente or {}
        self._fila_por_id = None
        self.tasa_base_intencion = tasa_base_intencion
        self.tasa_base_enganche = tasa_base_enganche
        self.origen_orden = origen_orden
        self.curva_fatiga = curva_fatiga or []

    # ------------------------------------------------- el valor exacto de uno
    def _fila(self, customer_id):
        """La fila que ocupa un cliente en los arrays sin ordenar, o `None`."""
        if customer_id is None:
            return None
        if self._fila_por_id is None:
            self._fila_por_id = {int(c): i for i, c in enumerate(self.idx)}
        return self._fila_por_id.get(int(customer_id))

    def _exacto(self, tabla, producto, customer_id):
        fila = self._fila(customer_id)
        arr = tabla.get(producto)
        if fila is None or arr is None or fila >= len(arr):
            return None
        return float(arr[fila])

    def valor_intencion(self, producto, customer_id):
        """La `p_intencion` de ese cliente **con todos sus decimales**."""
        return self._exacto(self.p_intencion_por_cliente, producto, customer_id)

    def valor_score(self, producto, customer_id):
        """El `score` de ese cliente **con todos sus decimales**."""
        return self._exacto(self.score_por_cliente, producto, customer_id)

    # -------------------------------------------------------- comparaciones
    # `customer_id` es opcional pero es lo que hace exacto el conteo: la
    # pantalla trabaja con el valor ya redondeado y ese redondeo desplaza el
    # corte de `searchsorted` (ver `_posicion`). Si el cliente está en la
    # población, se usa su valor exacto; si no, se cae al valor recibido.
    #
    # El exacto solo sustituye al publicado si **son el mismo número**. No
    # siempre lo son: la vista se construye a las 12:00 del corte y una petición
    # puede pedir otro `asof` del mismo día, con lo que el estado de la señal
    # —y por tanto `p_enganche` y el `score`— cambian. Cuando eso pasa, el
    # número de la pantalla no es el que la población tiene guardado para ese
    # cliente, y sustituirlo sería rankear una cifra distinta de la que se
    # enseña. En ese caso se cuenta contra lo publicado, como siempre.
    def _valor(self, tabla, producto, valor, customer_id):
        exacto = self._exacto(tabla, producto, customer_id)
        if exacto is None or valor is None:
            return valor
        return exacto if _mismo_numero(exacto, valor) else valor

    def percentil_intencion(self, producto, valor, customer_id=None):
        return _percentil(self.p_intencion.get(producto),
                          self._valor(self.p_intencion_por_cliente, producto,
                                      valor, customer_id))

    def percentil_score(self, producto, valor, customer_id=None):
        return _percentil(self.score.get(producto),
                          self._valor(self.score_por_cliente, producto,
                                      valor, customer_id))

    def posicion_intencion(self, producto, valor, customer_id=None):
        return _posicion(self.p_intencion.get(producto),
                         self._valor(self.p_intencion_por_cliente, producto,
                                     valor, customer_id))

    def posicion_score(self, producto, valor, customer_id=None):
        return _posicion(self.score.get(producto),
                         self._valor(self.score_por_cliente, producto,
                                     valor, customer_id))

    def histograma_intencion(self, producto, valor):
        """El histograma de `p_intencion` de ese producto, con las tres marcas.

        Las marcas son las que hacen legible el dibujo: la mediana de los
        38,000, la tasa base observada de la acción y el propio cliente.
        """
        return _histograma_log(self.p_intencion.get(producto), valor, marcas={
            "tasa_base": self.tasa_base_intencion.get(producto), "cliente": valor})

    def histograma_score(self, producto, valor):
        return _histograma_log(self.score.get(producto), valor,
                               marcas={"cliente": valor})

    def veces_sobre_base(self, producto, valor):
        """`p_intencion` dividida entre la tasa base observada de esa acción."""
        base = self.tasa_base_intencion.get(producto)
        if not base or valor is None:
            return None
        return round(float(valor) / float(base), 2)

    def veces_sobre_base_enganche(self, producto, valor):
        base = self.tasa_base_enganche.get(producto)
        if not base or valor is None:
            return None
        return round(float(valor) / float(base), 2)

    # ------------------------------------------------------------- selector
    def conteo_por_oferta(self):
        """Cuántos de los 38,000 reciben cada tipo de oferta o se quedan en silencio."""
        import numpy as np

        vals, cuentas = np.unique(self.oferta.astype(str), return_counts=True)
        return {str(v): int(c) for v, c in zip(vals, cuentas)}

    def conteo_por_razon(self):
        """De los que se quedan en silencio, por qué puerta se les cerró."""
        import numpy as np

        m = self.oferta == SILENCIO
        if not m.any():
            return {}
        vals, cuentas = np.unique(self.puerta[m].astype(str), return_counts=True)
        return {str(v): int(c) for v, c in zip(vals, cuentas)}

    def clientes(self, tipo=None, razon=None):
        """Ids que cumplen el filtro. `tipo` es un producto o `"silencio"`."""
        import numpy as np

        m = np.ones(len(self.idx), dtype=bool)
        if tipo:
            m &= self.oferta == tipo
        if razon:
            m &= self.puerta == razon
        return self.idx[m]

    def estado(self):
        """Lo que `/health` publica de esta vista. Sin arrays."""
        return {
            "corte": self.corte,
            "asof": self.asof,
            "cobertura": self.cobertura,
            "tasa_base_intencion": self.tasa_base_intencion,
            "tasa_base_enganche": self.tasa_base_enganche,
            "conteo_por_oferta": self.conteo_por_oferta(),
            "conteo_por_razon": self.conteo_por_razon(),
            "curva_fatiga": self.curva_fatiga,
            "origen_orden": self.origen_orden,
        }


# ==========================================================================
def _tasa_base_intencion(corte):
    """Fracción observada de clientes que hizo cada acción en ese corte.

    Sale de `labels_intent.parquet`, que es la etiqueta con la que se entrenó y
    evaluó el modelo de intención. Si el corte no está tabulado, se dice; no se
    interpola.
    """
    import pandas as pd

    if not os.path.exists(LABELS_INTENCION):
        raise PanoramaNoDisponible("falta labels_intent.parquet: sin él no hay tasa base")
    t = pd.read_parquet(LABELS_INTENCION)
    sub = t[t["asof"].astype(str) == corte]
    if not len(sub):
        raise PanoramaNoDisponible(f"labels_intent.parquet no trae el corte {corte}")
    out = {}
    for producto in CATALOGO_DEMO:
        col = f"y_{PRODUCTO_A_ACCION[producto]}"
        if col not in sub.columns:
            raise PanoramaNoDisponible(f"labels_intent.parquet no trae {col}")
        out[producto] = round(float(sub[col].mean()), 6)
    return out


def _tasa_base_enganche(store, asof):
    """Fracción de avisos enganchados por tipo, con corte estricto `shown_ts < asof`."""
    import pandas as pd

    nu = store.nu.reset_index()
    nu = nu[nu.shown_ts < pd.Timestamp(asof)]
    g = nu.groupby("nudge_type", observed=True).engaged.mean()
    return {p: (round(float(g[p]), 6) if p in g.index else None) for p in CATALOGO_DEMO}


def _curva_fatiga(store, asof):
    """Enganche y bajas por número de exposición, contados antes del corte.

    Es la evidencia del cap de 2 exposiciones dibujada: en la primera engancha
    ~15.72 % y se da de baja el 0.28 %; en la tercera engancha 3.50 % y se da de
    baja el 2.57 %. No es la estimación de un modelo, es el conteo de `nudges`
    con corte estricto `shown_ts < asof`.

    Solo se publican las exposiciones con al menos `MIN_AVISOS_POR_EXPOSICION`
    avisos: por encima de la sexta quedan decenas de casos y la tasa sería ruido.
    """
    import pandas as pd

    nu = store.nu.reset_index()
    nu = nu[nu.shown_ts < pd.Timestamp(asof)]
    if not len(nu):
        return []
    g = nu.groupby("exposure_no", observed=True).agg(
        n=("engaged", "size"), enganche=("engaged", "mean"),
        baja=("opted_out_after", "mean")).sort_index()
    g = g[g["n"] >= MIN_AVISOS_POR_EXPOSICION]
    return [{"exposure_no": int(i),
             "n": int(f.n),
             "enganche": round(float(f.enganche), 6),
             "baja": round(float(f.baja), 6)}
            for i, f in zip(g.index, g.itertuples())]


def _matriz_intencion(modelo, corte):
    """`p_intencion` de los 38,000 para los 4 productos, en una sola pasada.

    Usa la **misma** foto de features y las **mismas** cabezas que sirven una
    petición: si divergieran, el percentil que se enseña no sería el del cliente.
    """
    tabla = modelo.tablas.get(corte)
    if tabla is None:
        raise PanoramaNoDisponible(f"el nivel v1 no tiene la foto de features de {corte}")
    x = tabla[modelo.columnas]
    cabezas = modelo._cabezas(modelo.intencion)
    out = {}
    for producto in CATALOGO_DEMO:
        accion = PRODUCTO_A_ACCION[producto]
        if accion not in cabezas:
            raise PanoramaNoDisponible(f"modelo_intencion.pkl no trae cabeza para {accion}")
        out[producto] = cabezas[accion].predict_proba(x)[:, 1]
    return tabla.index, out


def _matriz_enganche(modelo, masas):
    """`p_enganche` de los 38,000, con las dos variables del modelo de momento.

    Las variables son las mismas que en el camino de una petición: el estado de
    la señal (ordinal) y el número de exposición que tocaría.
    """
    import pandas as pd

    variables = (modelo.momento.get("variables") if isinstance(modelo.momento, dict)
                 else None) or ["senal", "exposure_no"]
    m = modelo.momento
    if isinstance(m, dict):
        m = m.get("pipeline") or m.get("modelo") or m.get("model") or m.get("momento")
    if m is None or not hasattr(m, "predict_proba"):
        raise PanoramaNoDisponible("modelo_momento.pkl no expone predict_proba")

    out = {}
    for producto in CATALOGO_DEMO:
        d = masas["por_producto"][producto]
        valores = {"senal": d["momento"].astype("float64"),
                   "exposure_no": (d["exposiciones"] + 1).astype("float64")}
        x = pd.DataFrame({v: valores[v] for v in variables})
        out[producto] = m.predict_proba(x)[:, 1]
    return out


# --------------------------------------------------------------------------
def vista_de_corte(store, escalera, corte, modelo=None):
    """Construye la `VistaCorte` de un corte. Lanza `PanoramaNoDisponible`."""
    import numpy as np

    asof = corte + HORA_PANORAMA
    tabla_valor = escalera.tabla_valor
    cobertura = politica.cobertura(store, asof, tabla_valor)
    masas = politica.evaluar_masivo(store, asof, tabla_valor)
    if "por_producto" not in masas:
        raise PanoramaNoDisponible(
            f"el corte {corte} cae en zona contaminada ({masas.get('motivo')})")

    idx = masas["idx"]
    n = masas["n"]

    if modelo is not None:
        indice, p_int = _matriz_intencion(modelo, corte)
        if list(indice) != list(idx):
            # reordenar la foto de features al orden de `customers`
            posicion = indice.get_indexer(idx)
            if (posicion < 0).any():
                raise PanoramaNoDisponible(
                    f"la foto de features de {corte} no cubre a los {n} clientes")
            p_int = {p: v[posicion] for p, v in p_int.items()}
        p_eng = _matriz_enganche(modelo, masas)
        origen_orden = "score = p_intencion × p_enganche × V (modelo v1)"
    else:
        p_int, p_eng, origen_orden = {}, {}, "prioridad de salud (el nivel v1 no está montado)"

    # ---- qué se le ofrece a cada cliente ---------------------------------
    # Mismo criterio que `politica.armar_respuesta`: score descendente y, a
    # igualdad, la prioridad de salud financiera.
    oferta = np.full(n, SILENCIO, dtype=object)
    puerta = np.full(n, None, dtype=object)
    mejor = np.full(n, -np.inf)
    scores = {}
    for producto in CATALOGO_DEMO:
        d = masas["por_producto"][producto]
        v = float(tabla_valor.get(producto, {}).get("V", 0.0))
        if p_int and p_eng:
            s = p_int[producto] * p_eng[producto] * v
        else:
            # sin modelo no hay score: se ordena solo por prioridad de salud
            s = np.full(n, -float(politica._prioridad_salud(producto)))
        scores[producto] = s
        gana = d["pasa"] & (s > mejor)
        mejor = np.where(gana, s, mejor)
        oferta = np.where(gana, producto, oferta)

    # ---- por qué se calla, para quien no recibe nada ---------------------
    # La puerta de mayor PRIORIDAD DE REPORTE entre las que le cerraron.
    en_silencio = oferta == SILENCIO
    rango = np.full(n, len(politica.PRIORIDAD_REPORTE), dtype="int16")
    for producto in CATALOGO_DEMO:
        cierra = masas["por_producto"][producto]["cierra"]
        for codigo in politica.PRIORIDAD_REPORTE:
            m = en_silencio & (cierra == codigo)
            if not m.any():
                continue
            r = politica.PRIORIDAD_REPORTE.index(codigo)
            mejora = m & (r < rango)
            rango = np.where(mejora, r, rango)
            puerta = np.where(mejora, codigo, puerta)

    return VistaCorte(
        corte=corte, asof=asof, cobertura=cobertura, idx=idx,
        oferta=oferta, puerta=puerta,
        p_intencion={p: np.sort(v) for p, v in p_int.items()},
        score={p: np.sort(v) for p, v in scores.items()},
        # sin ordenar: la fila i es la del cliente idx[i]
        p_intencion_por_cliente=dict(p_int),
        score_por_cliente=dict(scores),
        tasa_base_intencion=_tasa_base_intencion(corte),
        tasa_base_enganche=_tasa_base_enganche(store, asof),
        curva_fatiga=_curva_fatiga(store, asof),
        origen_orden=origen_orden)


# ==========================================================================
class Panorama:
    """Las vistas de todos los cortes disponibles, montadas en el `lifespan`."""

    def __init__(self, vistas, motivos, corte_defecto):
        self.vistas = vistas                # {corte: VistaCorte}
        self.motivos = motivos              # {corte: por qué no está}
        self.corte_defecto = corte_defecto

    @property
    def cortes(self):
        return sorted(self.vistas)

    def de(self, corte):
        """La vista de un corte, o `None`. Nunca la de otro día disfrazada."""
        return self.vistas.get(corte)

    def cobertura(self, corte):
        v = self.de(corte)
        return v.cobertura if v else None

    @classmethod
    def cargar(cls, store, escalera, cortes):
        t0 = time.perf_counter()
        modelo = next((nv for n, nv in escalera.niveles if n == "v1"), None)
        vistas, motivos = {}, {}
        for corte in cortes:
            try:
                vistas[corte] = vista_de_corte(store, escalera, corte, modelo)
            except PanoramaNoDisponible as e:
                motivos[corte] = str(e)
            except Exception as e:                             # pragma: no cover
                motivos[corte] = f"{type(e).__name__}: {e}"
        defecto = max(vistas) if vistas else None
        from pipeline.ingesta import registrar_evidencia
        registrar_evidencia("panorama.cargar", len(cortes), len(vistas), t0,
                            cortes=sorted(vistas), motivos=motivos,
                            con_modelo=modelo is not None)
        return cls(vistas, motivos, defecto)

    def estado(self):
        return {"cortes": self.cortes,
                "cortes_caidos": self.motivos,
                "corte_defecto": self.corte_defecto,
                "por_corte": {c: v.estado() for c, v in sorted(self.vistas.items())}}
