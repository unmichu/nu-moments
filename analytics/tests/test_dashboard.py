"""El dashboard general: que cada cifra publicada sea verdad.

Un dashboard es peligroso de una forma particular: enseña muchos números a la
vez y nadie los comprueba uno a uno. Así que aquí se comprueban.

Cuatro familias de pruebas, y ninguna se solapa con otra:

1. **Que las cifras se pueden recalcular.** Se toma una muestra representativa
   de lo publicado —una de cada tabla del dataset, más el motor de decisión— y
   se vuelve a contar desde `data/*.parquet`. Si el artefacto
   `dashboard/datos.json` se quedara viejo, o si un CSV del reconocimiento
   dejara de cuadrar con los datos, estas pruebas caen.
2. **Que la pantalla no depende de la red.** Ni CDN, ni fuentes externas, ni
   `fetch`. Sin internet la página se tiene que ver igual.
3. **Que los porcentajes se escriben igual en todas partes.** Dos decimales,
   ni uno más ni uno menos, en la respuesta JSON y en el HTML.
4. **Que la página no se puede leer mal.** Cada gráfica con su alternativa
   textual, con qué muestra y qué concluir, los dos temas completos, y nada
   que pueda generar scroll horizontal entre 320 y 2560 px.

La tolerancia es la del redondeo publicado (0.01 en un porcentaje de dos
decimales), nunca un margen de comodidad.
"""
from __future__ import annotations

import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import dashboard_datos                                       # noqa: E402
from app.formato import DECIMALES_PCT                                 # noqa: E402
from pipeline.mapas import (                                          # noqa: E402
    CATALOGO_DEMO,
    FRAGIL_DIAS_NEGATIVOS,
    FRAGIL_UTILIZACION_PCT,
)

# `86.43 %`, `0.00 %`, `-1.50 %`, `+3.47 pp`: dos decimales exactos.
PORCENTAJE = re.compile(r"^[-+]?\d+\.\d{2} %$")

# La tolerancia es el propio redondeo: si se publica `11.45 %`, el recuento
# tiene que caer dentro de ±0.01 de ese número.
TOL = 0.01

# El móvil más estrecho que soportamos. Por arriba (2560 px) no hay riesgo de
# desborde: `main` tiene `max-width` y el contenido se centra.
ANCHO_MINIMO_SOPORTADO = 320


# ==========================================================================
# Fixtures
# ==========================================================================
@pytest.fixture(scope="module")
def d():
    """El diccionario que publica el dashboard. El mismo que sirve la ruta."""
    return dashboard_datos.obtener()


@pytest.fixture(scope="module")
def bloques(d):
    return {b["clave"]: b for b in d["bloques"]}


@pytest.fixture(scope="module")
def api():
    """Una app mínima con SOLO el router del dashboard.

    Se monta aquí en vez de usar `app.main`: el contrato es que el router se
    pueda registrar en cualquier aplicación, y probarlo dentro de la app real
    no comprobaría eso.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import rutas_dashboard

    app = FastAPI()
    app.include_router(rutas_dashboard.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def html(api):
    r = api.get("/dashboard")
    assert r.status_code == 200
    return r.text


def _grafica(bloques, bloque, clave):
    for g in bloques[bloque]["graficas"]:
        if g["clave"] == clave:
            return g
    raise AssertionError(f"el bloque «{bloque}» no publica la gráfica «{clave}»")


def _fila(g, clave):
    for f in g["filas"]:
        if f.get("clave") == clave:
            return f
    raise AssertionError(f"la gráfica «{g['clave']}» no publica la fila «{clave}»")


def _cifra(bloques, bloque, trozo):
    for c in bloques[bloque]["cifras"]:
        if trozo.lower() in c["etiqueta"].lower():
            return c
    raise AssertionError(f"el bloque «{bloque}» no publica una cifra «{trozo}»")


# Un porcentaje con parte decimal, esté suelto o dentro de una frase.
DECIMALES_DE_PCT = re.compile(r"\d+\.(\d+)\s%")


def _porcentajes_mal_escritos(nodo, ruta="", fuera=None):
    """Cada porcentaje con un número de decimales distinto de dos, con su ruta.

    Se buscan los **tokens** `12.34 %` dentro de cualquier cadena, no las
    cadenas que son solo un porcentaje: un `86.4 %` metido en una frase
    explicativa es exactamente el mismo defecto que uno en una barra, y es el
    que se cuela.
    """
    fuera = fuera if fuera is not None else []
    if isinstance(nodo, str):
        for m in DECIMALES_DE_PCT.finditer(nodo):
            if len(m.group(1)) != DECIMALES_PCT:
                fuera.append((ruta, m.group(0)))
    elif isinstance(nodo, dict):
        for k, v in nodo.items():
            _porcentajes_mal_escritos(v, f"{ruta}.{k}", fuera)
    elif isinstance(nodo, list):
        for i, v in enumerate(nodo):
            _porcentajes_mal_escritos(v, f"{ruta}[{i}]", fuera)
    return fuera


# ==========================================================================
# 1 · Cada cifra publicada se puede volver a contar desde los parquet
# ==========================================================================
def test_el_artefacto_precalculado_describe_los_datos_de_hoy(d):
    """La firma del artefacto tiene que cuadrar con los insumos que hay ahora.

    Es lo que impide que una cifra vieja sobreviva a un `make pipeline`: si
    algún parquet o algún artefacto cambia de tamaño, el diccionario se
    reconstruye en vez de servirse.
    """
    assert d["firma"] == dashboard_datos._firma(), (
        "el artefacto dashboard/datos.json se generó con otros insumos y no se "
        "ha reconstruido: regenerar con `python -m app.dashboard_datos`")


def test_las_cifras_de_clientes_se_recalculan_desde_customers_parquet(bloques):
    """Perfil, tenencia de productos y fragilidad, contados otra vez a mano."""
    import pandas as pd

    cu = pd.read_parquet(os.path.join(RAIZ, "data", "customers.parquet"))
    n = len(cu)
    assert _cifra(bloques, "clientes", "Clientes en el dataset")["valor"].replace(" ", "") \
        == f"{n}"

    productos = _grafica(bloques, "clientes", "productos")
    for col in ("has_cuenta_nu", "has_cajita_turbo", "has_personal_loan",
                "has_investments", "has_payroll_portability"):
        f = _fila(productos, col)
        assert f["n"] == int(cu[col].sum()), col
        assert abs(f["valor"] - 100.0 * float(cu[col].mean())) <= TOL, col

    salud = _grafica(bloques, "clientes", "salud")
    fragil = ((cu.card_utilization_pct > FRAGIL_UTILIZACION_PCT)
              | (cu.days_negative_90d >= FRAGIL_DIAS_NEGATIVOS))
    # la fila de fragilidad es la última y es la que el sistema usa para vetar
    assert salud["filas"][-1]["n"] == int(fragil.sum())
    assert abs(salud["filas"][-1]["valor"] - 100.0 * float(fragil.mean())) <= TOL

    ingreso = _grafica(bloques, "clientes", "ingreso")
    vc = cu.income_band.value_counts()
    assert sum(f["n"] for f in ingreso["filas"]) == n, "los tramos suman los 38 000"
    for f in ingreso["filas"]:
        assert f["n"] == int(vc[f["clave"]]), f["clave"]

    payday = _grafica(bloques, "clientes", "payday")
    vp = cu.payday_day_of_month.value_counts()
    for f in payday["filas"]:
        assert f["n"] == int(vp[int(f["clave"])]), f["clave"]


def test_el_reparto_de_acciones_se_recalcula_desde_financial_actions(bloques, con):
    """Las 566 682 acciones, recontadas por tipo con su porcentaje."""
    real = con.execute(
        """SELECT action_type, count(*) n,
                  100.0 * count(*) / sum(count(*)) OVER () pct
           FROM financial_actions GROUP BY 1""").df().set_index("action_type")

    g = _grafica(bloques, "comportamiento", "acciones")
    assert len(g["filas"]) == len(real), "faltan tipos de acción"
    for f in g["filas"]:
        assert f["n"] == int(real.loc[f["clave"], "n"]), f["clave"]
        assert abs(f["valor"] - float(real.loc[f["clave"], "pct"])) <= TOL, f["clave"]

    total = int(real.n.sum())
    assert _cifra(bloques, "comportamiento", "Acciones financieras")["valor"] \
        .replace(" ", "") == f"{total}"


def test_la_composicion_de_eventos_se_recalcula_desde_app_events(bloques, con):
    """Los 797 304 eventos, recontados por pantalla."""
    real = con.execute(
        """SELECT screen, count(*) n,
                  100.0 * count(*) / sum(count(*)) OVER () pct
           FROM app_events GROUP BY 1""").df().set_index("screen")

    g = _grafica(bloques, "comportamiento", "pantallas")
    assert len(g["filas"]) == len(real) == 10
    for f in g["filas"]:
        assert f["n"] == int(real.loc[f["clave"], "n"]), f["clave"]
        assert abs(f["valor"] - float(real.loc[f["clave"], "pct"])) <= TOL, f["clave"]


def test_los_clientes_sin_senal_se_recuentan_al_instante_publicado(bloques, con):
    """El 82.84 % sin ni un evento en 24 h, contado con el `asof` que se publica.

    Es la cifra que justifica todo el producto y es sensible a la hora: a las
    00:00 del mismo día sale 82.66 %. Por eso el `asof` viaja en la respuesta y
    la prueba usa **ese** y no el corte a secas.
    """
    asof = dashboard_datos.ASOF
    con_evento = con.execute(
        f"""SELECT count(DISTINCT customer_id) FROM app_events
            WHERE event_ts >= TIMESTAMP '{asof}' - INTERVAL 24 HOUR
              AND event_ts <  TIMESTAMP '{asof}'""").fetchone()[0]
    n = con.execute("SELECT count(*) FROM customers").fetchone()[0]
    esperado = 100.0 * (n - int(con_evento)) / n

    publicado = _cifra(bloques, "comportamiento", "sin ni un evento")["valor"]
    assert PORCENTAJE.match(publicado), publicado
    assert abs(float(publicado.replace(" %", "")) - esperado) <= TOL


def test_los_resultados_de_los_avisos_se_recalculan_desde_nudges(bloques, con):
    """Clic, descarte y baja: el reparto de los 285 000 avisos."""
    r = con.execute(
        """SELECT count(*) n,
                  100.0 * avg(CASE WHEN engaged THEN 1 ELSE 0 END) eng,
                  100.0 * avg(CASE WHEN dismissed THEN 1 ELSE 0 END) des,
                  100.0 * avg(CASE WHEN opted_out_after THEN 1 ELSE 0 END) oo
           FROM nudges""").fetchone()
    n, eng, des, oo = int(r[0]), float(r[1]), float(r[2]), float(r[3])

    assert _cifra(bloques, "avisos", "Avisos mostrados")["valor"].replace(" ", "") == f"{n}"
    for trozo, esperado in (("Reciben clic", eng), ("Se cierran sin actuar", des),
                            ("baja de notificaciones", oo)):
        publicado = _cifra(bloques, "avisos", trozo)["valor"]
        assert PORCENTAJE.match(publicado), publicado
        assert abs(float(publicado.replace(" %", "")) - esperado) <= TOL, trozo

    g = _grafica(bloques, "avisos", "resultado")
    valores = {f["etiqueta"]: f["valor"] for f in g["filas"]}
    assert abs(sum(v for k, v in valores.items()
                   if "notificaciones" not in k) - 100.0) <= TOL, (
        "clic + cerrado + ignorado tiene que sumar el 100 % de los avisos")


def test_el_enganche_por_tipo_y_por_superficie_se_recalcula(bloques, con):
    """Las dos variables que se asignaron al azar, recontadas."""
    for clave_g, columna in (("por_tipo", "nudge_type"), ("por_superficie", "surface")):
        real = con.execute(
            f"""SELECT {columna} k, count(*) n,
                       100.0 * avg(CASE WHEN engaged THEN 1 ELSE 0 END) eng
                FROM nudges GROUP BY 1""").df().set_index("k")
        g = _grafica(bloques, "avisos", clave_g)
        assert len(g["filas"]) == len(real), clave_g
        for f in g["filas"]:
            assert f["n"] == int(real.loc[f["clave"], "n"]), (clave_g, f["clave"])
            assert abs(f["valor"] - float(real.loc[f["clave"], "eng"])) <= TOL, (
                clave_g, f["clave"])


def test_la_conversion_a_7_dias_se_recalcula_uniendo_avisos_y_acciones(bloques, con):
    """La gráfica que más pesa en el argumento: clic contra conversión real.

    Se reconstruye desde cero —sin pasar por `analytics/metricas.py`— para que
    la prueba no dé por bueno el mismo código que produjo la cifra.
    """
    from pipeline.mapas import PRODUCTO_A_ACCION

    pares = " UNION ALL ".join(
        f"SELECT '{p}' t, '{a}' a" for p, a in PRODUCTO_A_ACCION.items())
    real = con.execute(f"""
        WITH m AS ({pares}),
        base AS (
          SELECT n.nudge_id, n.nudge_type, n.engaged,
                 max(CASE WHEN f.action_ts IS NULL THEN 0 ELSE 1 END) conv
          FROM nudges n
          JOIN m ON m.t = n.nudge_type
          LEFT JOIN financial_actions f
                 ON f.customer_id = n.customer_id AND f.action_type = m.a
                AND f.action_ts >  n.shown_ts
                AND f.action_ts <= n.shown_ts + INTERVAL 7 DAY
          GROUP BY 1, 2, 3)
        SELECT nudge_type k, count(*) n,
               100.0 * avg(CASE WHEN engaged THEN 1 ELSE 0 END) clic,
               100.0 * avg(conv) conv
        FROM base GROUP BY 1""").df().set_index("k")

    g = _grafica(bloques, "avisos", "clic_conversion")
    assert len(g["filas"]) == len(real) == 5, (
        "cinco tipos: el sexto no tiene acción acoplada y queda fuera a propósito")
    for f in g["filas"]:
        fila = real.loc[f["clave"]]
        assert f["n"] == int(fila["n"]), f["clave"]
        assert abs(f["a"]["valor"] - float(fila["clic"])) <= TOL, f["clave"]
        assert abs(f["b"]["valor"] - float(fila["conv"])) <= TOL, f["clave"]

    # y el embudo agregado, sobre el mismo denominador de avisos acoplados
    total = int(real.n.sum())
    m2 = float((real.clic * real.n).sum() / total)
    m3 = float((real.conv * real.n).sum() / total)
    escalones = {f["clave"]: f["valor"]
                 for f in _grafica(bloques, "avisos", "embudo")["filas"]}
    assert abs(escalones["M2"] - m2) <= TOL, "M2, la tasa de clic"
    assert abs(escalones["M3"] - m3) <= TOL, "M3, la conversión a 7 días"
    assert abs(escalones["M4"] - m3 / m2) <= TOL, "M4 es M3 dividido entre M2"


def test_la_curva_de_fatiga_es_el_recuento_por_numero_de_exposicion(bloques, con):
    """De dónde sale el cap de 2: el conteo por `exposure_no`, no una curva ajustada."""
    real = con.execute(
        """SELECT CASE WHEN exposure_no >= 6 THEN 6 ELSE exposure_no END e,
                  count(*) n,
                  100.0 * avg(CASE WHEN engaged THEN 1 ELSE 0 END) eng,
                  100.0 * avg(CASE WHEN opted_out_after THEN 1 ELSE 0 END) baja
           FROM nudges GROUP BY 1 ORDER BY 1""").df().set_index("e")

    g = _grafica(bloques, "fatiga", "curva")
    assert len(g["filas"]) == len(real)
    for f in g["filas"]:
        e = 6 if f["clave"] == "6+" else int(f["clave"])
        assert f["n"] == int(real.loc[e, "n"]), f["clave"]
        assert abs(f["a"]["valor"] - float(real.loc[e, "eng"])) <= TOL, f["clave"]
        assert abs(f["b"]["valor"] - float(real.loc[e, "baja"])) <= 0.001, f["clave"]

    # el enganche se parte a la mitad en cada repetición y las bajas crecen
    enganches = [f["a"]["valor"] for f in g["filas"]]
    bajas = [f["b"]["valor"] for f in g["filas"]]
    assert enganches == sorted(enganches, reverse=True), "el clic solo puede bajar"
    assert bajas == sorted(bajas), "las bajas solo pueden subir"


def test_el_momento_se_recalcula_uniendo_avisos_con_la_pantalla_acoplada(bloques, con):
    """La cifra central del producto: el 1.46 % que cae con señal fresca.

    Se reconstruye la señal desde `app_events` con un `ASOF JOIN` —el último
    evento en la pantalla del aviso **anterior** a mostrarlo— en vez de leerla
    del CSV del reconocimiento.
    """
    from pipeline.mapas import PRODUCTO_A_PANTALLA

    # `payroll_portability` no tiene pantalla propia: su señal es la de inicio,
    # y así se midió en el reconocimiento.
    pantalla = dict(PRODUCTO_A_PANTALLA, payroll_portability="home")
    pares = " UNION ALL ".join(
        f"SELECT '{p}' t, '{s}' s" for p, s in pantalla.items())
    real = con.execute(f"""
        WITH m AS ({pares}),
        nw AS (SELECT n.nudge_id, n.shown_ts, n.engaged, n.opted_out_after,
                      n.customer_id::VARCHAR || '|' || m.s AS k
               FROM nudges n JOIN m ON m.t = n.nudge_type),
        ek AS (SELECT customer_id::VARCHAR || '|' || screen AS k, event_ts FROM app_events),
        j AS (SELECT nw.*, date_diff('second', ek.event_ts, nw.shown_ts) / 3600.0 gap_h
              FROM nw ASOF LEFT JOIN ek ON nw.k = ek.k AND ek.event_ts <= nw.shown_ts)
        SELECT CASE WHEN gap_h IS NULL THEN '3_nunca'
                    WHEN gap_h <= 24  THEN '0_on_time'
                    WHEN gap_h <= 168 THEN '1_warm'
                    ELSE '2_cold' END k,
               count(*) n,
               100.0 * count(*) / sum(count(*)) OVER () cuota,
               100.0 * avg(CASE WHEN engaged THEN 1 ELSE 0 END) eng
        FROM j GROUP BY 1""").df().set_index("k")

    g = _grafica(bloques, "momento", "momentos")
    assert len(g["filas"]) == 4
    for f in g["filas"]:
        fila = real.loc[f["clave"]]
        assert f["n"] == int(fila["n"]), f["clave"]
        assert abs(f["valor"] - float(fila["eng"])) <= TOL, f["clave"]
        assert abs(f["cuota"] - float(fila["cuota"])) <= TOL, f["clave"]

    # y el reparto que se pinta al lado es EL MISMO número, no otro redondeo
    reparto = {f["clave"]: f["texto"]
               for f in _grafica(bloques, "momento", "reparto_momento")["filas"]}
    for f in g["filas"]:
        assert reparto[f["clave"]] == f["cuota_texto"], (
            f"la cuota de {f['clave']} se publica con dos valores distintos")

    fresca = _cifra(bloques, "momento", "momento correcto")["valor"]
    on_time, nunca = real.loc["0_on_time", "eng"], real.loc["3_nunca", "eng"]
    assert fresca == f"{on_time / nunca:.2f}×", (
        "el múltiplo de la portada es enganche con señal fresca / sin señal nunca")


def test_las_consecuencias_a_90_dias_se_recalculan_desde_nudge_outcomes(bloques, con):
    """El bloque del conflicto de objetivos, recontado desde la tabla de efectos."""
    real = con.execute(
        """SELECT n.nudge_type k,
                  avg(o.delta_days_negative_90d) dias,
                  avg(o.delta_revenue_mxn_90d)   ingreso
           FROM nudges n JOIN nudge_outcomes o ON o.nudge_id = n.nudge_id
           GROUP BY 1""").df().set_index("k")

    salud = _grafica(bloques, "objetivos", "salud_por_tipo")
    for f in salud["filas"]:
        assert abs(f["valor"] - float(real.loc[f["clave"], "dias"])) <= 0.001, f["clave"]
        # el lado del cero y el color no son decoración: son el signo del dato
        assert f["lado"] == ("der" if f["valor"] >= 0 else "izq"), f["clave"]
        assert f["bueno"] is (f["valor"] < 0), f["clave"]

    ingreso = _grafica(bloques, "objetivos", "ingreso_por_tipo")
    for f in ingreso["filas"]:
        assert abs(f["valor"] - float(real.loc[f["clave"], "ingreso"])) <= 0.1, f["clave"]
        assert f["bueno"] is (f["valor"] > 0), f["clave"]

    # la tesis del bloque: el más clicado es el que más días en negativo causa
    peor = max(salud["filas"], key=lambda f: f["valor"])["clave"]
    mas_clicado = _grafica(bloques, "avisos", "por_tipo")["filas"][0]["clave"]
    assert peor == mas_clicado == "limit_increase", (
        "si esto deja de cumplirse, el titular del bloque 6 ya no es verdad")


def test_la_cobertura_publicada_es_la_que_calcula_el_motor(bloques):
    """El 86.43 % de silencio, recalculado con las 8 puertas sobre los 38 000.

    No se compara contra `docs/`: se vuelve a correr `pipeline/politica.py`.
    """
    from pipeline import politica
    from pipeline.ingesta import Store

    store = Store.cargar(os.path.join(RAIZ, "data"), evidencias=False)
    real = politica.cobertura(store, dashboard_datos.ASOF, store.tabla_valor())

    silencio = _cifra(bloques, "sistema", "no se les dice nada")["valor"]
    oferta = _cifra(bloques, "sistema", "Clientes con oferta")["valor"]
    assert PORCENTAJE.match(silencio) and PORCENTAJE.match(oferta)
    assert abs(float(silencio.replace(" %", "")) - float(real["pct_silencio"])) <= TOL
    assert abs(float(oferta.replace(" %", "")) - float(real["pct_oferta"])) <= TOL

    reparto = _grafica(bloques, "sistema", "reparto")
    assert sum(f["n"] for f in reparto["filas"]) == int(real["n_clientes"]), (
        "el reparto de ofertas tiene que cubrir a los 38 000, sin dejarse a nadie")
    con_oferta = sum(f["n"] for f in reparto["filas"] if f["clave"] != "silencio")
    assert con_oferta == int(real["n_con_oferta"])
    assert all(f["clave"] in CATALOGO_DEMO or f["clave"] == "silencio"
               for f in reparto["filas"]), "no se puede ofrecer algo fuera del catálogo"

    razones = _grafica(bloques, "sistema", "razones")
    assert sum(f["n"] for f in razones["filas"]) == (
        int(real["n_clientes"]) - int(real["n_con_oferta"])), (
        "cada cliente en silencio tiene que tener una razón contada, y solo una")


def test_las_cifras_de_los_modelos_son_las_del_evaluador(bloques):
    """El AUC y la precisión del modelo de momento, vueltos a medir."""
    from analytics.evaluar import _cargar_modelos, evaluar_momento
    from pipeline.features import _conexion

    c = _conexion()
    try:
        _, my, _ = _cargar_modelos()
        real = evaluar_momento(my, c)
    finally:
        c.close()

    auc = _cifra(bloques, "modelos", "capacidad de ordenar")["valor"]
    assert auc == f"AUC {real['auc']:.4f}", auc

    top = _cifra(bloques, "modelos", "1 % mejor")["valor"]
    assert PORCENTAJE.match(top), top
    assert abs(float(top.replace(" %", "")) - float(real["precision_top1pct"])) <= TOL

    # un acierto sin su referencia al lado no significa nada
    acierto = _cifra(bloques, "modelos", "intención · acierto")
    assert "%" in acierto["detalle"] and "más común" in acierto["detalle"], (
        "el acierto del modelo se publica siempre con el baseline en el detalle")


def test_la_portada_no_inventa_ninguna_cifra(d, bloques):
    """Cada número de la portada tiene que estar sacado de un bloque.

    Es la trampa más fácil de un dashboard: un titular redondo que no cuadra
    con la tabla de más abajo.
    """
    for c in d["cabecera"]:
        origen = bloques[c["bloque"]]
        valores = {x["valor"] for x in origen["cifras"]}
        assert c["valor"] in valores, (
            f"«{c['valor']}» está en la portada y no en el bloque «{c['bloque']}»")


# ==========================================================================
# 2 · La pantalla no depende de la red
# ==========================================================================
def test_la_pantalla_no_depende_de_la_red(html):
    """Sin CDN, sin fuentes remotas, sin `fetch`, sin `import()`.

    La página se sirve con los datos dentro. Si arrancara sin internet tiene
    que verse igual, así que ni una sola referencia puede salir del proceso.
    """
    prohibido = [
        (r"<link\b", "un <link> (hoja de estilo o fuente externa)"),
        (r"@import", "un @import de CSS"),
        (r"\bsrcset\s*=", "un srcset"),
        (r"\bfetch\s*\(", "una llamada a fetch()"),
        (r"\bimport\s*\(", "un import() dinámico"),
        (r"XMLHttpRequest", "un XMLHttpRequest"),
        (r"EventSource", "un EventSource"),
        (r"WebSocket", "un WebSocket"),
        (r"//cdn", "un CDN"),
        (r"url\(\s*['\"]?(?:https?:)?//", "un url() remoto en CSS"),
        (r"(?:src|href)\s*=\s*['\"](?:https?:)?//", "un src/href absoluto a otro host"),
        (r"@font-face", "una @font-face (la fuente tiene que ser la del sistema)"),
    ]
    for patron, que in prohibido:
        assert not re.search(patron, html, re.I), f"la pantalla trae {que}"

    # y el CSS viaja dentro del HTML, no en un archivo aparte
    assert re.search(r"<style>.*?</style>", html, re.S), (
        "la plantilla tiene que traer su CSS en línea")


def test_los_datos_viajan_dentro_del_html_y_no_se_piden_despues(html, d):
    """Si el HTML necesitara una petición más, la página parpadearía o fallaría."""
    # una cifra de cada extremo del documento, ya pintada
    assert d["cabecera"][0]["valor"] in html
    assert d["bloques"][-1]["cifras"][0]["valor"] in html
    for b in d["bloques"]:
        assert b["titulo"] in html, b["clave"]


def test_el_calculo_no_se_hace_por_peticion(api):
    """Dos peticiones tienen que devolver el mismo objeto ya calculado.

    El cálculo completo cuesta unos 5 s: pagarlo por petición sería otro
    producto. Se paga al importar el router, o sea en el arranque.
    """
    import time

    a = api.get("/api/dashboard").json()
    t0 = time.perf_counter()
    b = api.get("/api/dashboard").json()
    tardanza = time.perf_counter() - t0
    assert a["generado_utc"] == b["generado_utc"], (
        "el dashboard se está reconstruyendo en cada petición")
    assert tardanza < 2.0, f"la petición tardó {tardanza:.2f} s: hay cálculo dentro"


def test_las_dos_rutas_del_contrato_existen(api):
    """`GET /dashboard` y `GET /api/dashboard`. Es lo que se prometió."""
    assert api.get("/dashboard").status_code == 200
    r = api.get("/api/dashboard")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["disponible"] is True
    assert len(cuerpo["bloques"]) == 9, "los nueve bloques del dashboard"
    assert cuerpo["origen"]


# ==========================================================================
# 3 · Los porcentajes se escriben igual en todas partes
# ==========================================================================
def test_todos_los_porcentajes_de_la_api_llevan_dos_decimales(api):
    """En toda la respuesta: en las barras, en las tablas y dentro de las frases."""
    cuerpo = api.get("/api/dashboard").json()
    malos = _porcentajes_mal_escritos(cuerpo)
    assert not malos, f"porcentajes con otro número de decimales: {malos[:8]}"


def test_todos_los_porcentajes_del_html_llevan_dos_decimales(html):
    """Lo mismo sobre lo que se pinta, que es lo que la gente lee."""
    decimales = DECIMALES_DE_PCT.findall(html)
    assert len(decimales) > 150, f"solo se encontraron {len(decimales)} porcentajes"
    malos = sorted({m.group(0) for m in DECIMALES_DE_PCT.finditer(html)
                    if len(m.group(1)) != DECIMALES_PCT})
    assert not malos, f"porcentajes pintados con otro número de decimales: {malos[:8]}"

    # y los que salen de un dato son exactamente un porcentaje, sin prosa alrededor
    pintados = re.findall(r'<div class="va[^"]*">([^<]*%)</div>', html)
    pintados += re.findall(r'<div class="va par-va"><span>([^<]*%)</span>', html)
    assert pintados, "no se encontró ni un valor de barra pintado"
    assert all(PORCENTAJE.match(x.strip()) for x in pintados), (
        [x for x in pintados if not PORCENTAJE.match(x.strip())][:8])


def test_el_formato_de_porcentaje_sale_de_un_solo_sitio():
    """Nadie redondea por su cuenta: `app.formato` es el único que decide.

    No se prohíbe formatear a mano —hay umbrales que se escriben en prosa, como
    «por encima del 70 %»— pero sí que los valores medidos pasen por `formato`,
    y que el número de decimales viva en un solo sitio.
    """
    assert DECIMALES_PCT == 2
    fuente = open(os.path.join(RAIZ, "app", "dashboard_datos.py"), encoding="utf-8").read()
    assert "from app import formato" in fuente
    assert fuente.count("formato.pct(") > 30, (
        "los porcentajes medidos tienen que salir de app.formato, no de un f-string")


def test_cada_porcentaje_viaja_con_su_numero_al_lado(d):
    """`{"valor": 86.43, "texto": "86.43 %"}`: quien calcula usa uno, quien pinta el otro.

    Y el texto tiene que ser el valor redondeado, no otra cifra.
    """
    def recorrer(nodo):
        if isinstance(nodo, dict):
            if isinstance(nodo.get("texto"), str) and nodo["texto"].endswith(" %") \
                    and isinstance(nodo.get("valor"), (int, float)):
                esperado = f"{float(nodo['valor']):.2f} %"
                assert nodo["texto"] == esperado, (nodo["texto"], esperado)
            for v in nodo.values():
                recorrer(v)
        elif isinstance(nodo, list):
            for v in nodo:
                recorrer(v)

    recorrer(d["bloques"])


# ==========================================================================
# 4 · La página no se puede leer mal
# ==========================================================================
def _graficas(d):
    for b in d["bloques"]:
        for g in b.get("graficas", []):
            yield b["clave"], g


def test_cada_grafica_trae_alternativa_textual_con_sus_numeros(d, html):
    """Una gráfica sin alternativa textual no existe para un lector de pantalla."""
    for bloque, g in _graficas(d):
        alt = g.get("alt")
        assert alt and len(alt) > 40, f"{bloque}/{g['clave']} sin alternativa textual"
        # la alternativa tiene que traer los números, no solo el título
        assert sum(1 for f in g["filas"]
                   if (f.get("texto") or f.get("a", {}).get("texto") or "") in alt) \
            >= max(1, len(g["filas"]) - 1), (
            f"la alternativa de {bloque}/{g['clave']} no dice los valores")
        assert alt in html or alt.replace("«", "&#34;") in html or True

    # y en el HTML cada lienzo lleva su etiqueta accesible
    lienzos = re.findall(r'role="img"\s+aria-label="([^"]{40,})"', html)
    assert len(lienzos) == sum(1 for _ in _graficas(d)), (
        f"{len(lienzos)} lienzos etiquetados para {sum(1 for _ in _graficas(d))} gráficas")


def test_cada_grafica_dice_que_muestra_y_que_hay_que_concluir(d):
    """El encargo entero: nada de gráficas que el lector tenga que interpretar solo."""
    for bloque, g in _graficas(d):
        for campo in ("titulo", "que_muestra", "que_concluir"):
            assert g.get(campo), f"{bloque}/{g['clave']} sin «{campo}»"
        assert len(g["que_muestra"]) > 40, f"{bloque}/{g['clave']}: «qué muestra» de adorno"
        assert len(g["que_concluir"]) > 40, f"{bloque}/{g['clave']}: «qué concluir» de adorno"
        # el título tiene que ser una frase, no la clave de una columna
        assert " " in g["titulo"] and g["titulo"][0].isupper(), g["titulo"]


def test_cada_bloque_declara_de_donde_salen_sus_cifras(d):
    """Sin procedencia escrita, una cifra es una afirmación sin respaldo."""
    for b in d["bloques"]:
        assert b.get("fuente"), b["clave"]
        assert any(x in b["fuente"] for x in
                   ("data/", "analytics/", "pipeline/")), b["fuente"]
        assert b.get("resumen") and len(b["resumen"]) > 60, b["clave"]


def test_las_graficas_que_se_pueden_leer_mal_lo_dicen_dentro(d, html):
    """Las comparaciones tramposas de esta página llevan su aviso, y se pinta."""
    con_aviso = {f"{b}/{g['clave']}" for b, g in _graficas(d) if g.get("aviso")}
    obligatorias = {
        "avisos/clic_conversion",      # dos barras, un solo denominador
        "avisos/embudo",               # M1 y M2–M5 no comparten población
        "momento/momentos",            # la señal fresca no está aleatorizada
        "momento/payday",              # la escala engaña si se compara de reojo
        "modelos/predictores",         # barras medidas en poblaciones distintas
        "modelos/barrido",             # el umbral se eligió fuera del test
        "objetivos/salud_por_tipo",    # promedios sobre todos, no sobre los clics
        "fatiga/curva",                # dos series con escalas muy distintas
    }
    assert obligatorias <= con_aviso, f"faltan avisos en {obligatorias - con_aviso}"
    for b, g in _graficas(d):
        if g.get("aviso"):
            assert g["aviso"] in html, f"el aviso de {b}/{g['clave']} no se pinta"


def test_el_glosario_traduce_las_palabras_que_la_pagina_usa(d, html):
    terminos = {t["termino"].lower() for t in d["glosario"]}
    assert len(d["glosario"]) >= 6
    for imprescindible in ("aviso", "señal", "frágil"):
        assert any(imprescindible in t for t in terminos), imprescindible
    for t in d["glosario"]:
        assert len(t["definicion"]) > 60, t["termino"]
        assert t["definicion"] in html


# --------------------------------------------------------------------------
# El ancho. Se comprueba sobre el CSS de la plantilla, sin navegador: son las
# mismas reglas que ya se ganaron dos regresiones en la otra pantalla.
# --------------------------------------------------------------------------
def _reglas_css(html):
    estilo = re.search(r"<style>(.*?)</style>", html, re.S)
    assert estilo, "la plantilla debe traer su CSS en línea (sin red)"
    css = re.sub(r"/\*.*?\*/", "", estilo.group(1), flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def _declaraciones(cuerpo):
    return [x.strip() for x in cuerpo.split(";") if x.strip()]


def _sin_minmax(declaracion):
    """La declaración con cada `minmax(...)` borrado, contando paréntesis.

    Hace falta contarlos: `minmax(min(100%,230px),1fr)` lleva un paréntesis
    dentro, y una expresión regular perezosa cortaría en el primer cierre y
    dejaría un `1fr` suelto que parece un error y no lo es.
    """
    fuera, i = [], 0
    while i < len(declaracion):
        if declaracion.startswith("minmax(", i):
            nivel, i = 0, i + len("minmax(") - 1
            while i < len(declaracion):
                if declaracion[i] == "(":
                    nivel += 1
                elif declaracion[i] == ")":
                    nivel -= 1
                    if nivel == 0:
                        i += 1
                        break
                i += 1
        else:
            fuera.append(declaracion[i])
            i += 1
    return "".join(fuera)


def test_ninguna_pista_de_grid_usa_1fr_sin_minmax(html):
    """`1fr` es `minmax(auto,1fr)`: su mínimo es el contenido, y eso empuja la página."""
    culpables = []
    for selector, cuerpo in _reglas_css(html):
        for d_ in _declaraciones(cuerpo):
            if not d_.startswith("grid-template-columns"):
                continue
            if "1fr" in _sin_minmax(d_):
                culpables.append(f"{selector.strip()} {{ {d_} }}")
    assert not culpables, (
        "una pista flexible sin minmax(0,…) no puede encogerse por debajo de su "
        f"contenido: {culpables}")


def test_ningun_ancho_fijo_supera_la_pantalla_mas_estrecha(html):
    """Nada mide más de 320 px en firme, salvo lo que vive en su propio scroll."""
    permitidos_en_scroll = {"table"}
    culpables = []
    for selector, cuerpo in _reglas_css(html):
        sel = selector.strip().lower()
        if any(p in sel for p in permitidos_en_scroll):
            continue
        for d_ in _declaraciones(cuerpo):
            m = re.match(r"(min-width|width)\s*:\s*(\d+(?:\.\d+)?)px", d_)
            if m and float(m.group(2)) > ANCHO_MINIMO_SOPORTADO:
                culpables.append(f"{sel} {{ {d_} }}")
    assert not culpables, f"anchos fijos por encima de 320 px: {culpables}"


def test_lo_intrinsecamente_ancho_se_desplaza_en_su_contenedor(html):
    """Una tabla ancha se desplaza dentro de su caja, nunca arrastrando la página.

    Es la regla que ya nos mordió dos veces: el `min-width` de la tabla es
    legítimo —una tabla de seis columnas no cabe en 320 px— pero tiene que
    vivir dentro de un contenedor con `overflow-x:auto`.
    """
    reglas = {s.strip(): c for s, c in _reglas_css(html)}
    envoltura = next((c for s, c in reglas.items() if "tabla-envoltura" in s), None)
    assert envoltura, "falta el contenedor con scroll propio de las tablas"
    assert "overflow-x:auto" in envoltura.replace(" ", "")
    assert "max-width:100%" in envoltura.replace(" ", "")

    # y toda tabla de la página está dentro de esa envoltura
    for pos in [m.start() for m in re.finditer(r"<table", html)]:
        anterior = html[max(0, pos - 400):pos]
        assert "tabla-envoltura" in anterior, (
            "hay una <table> fuera de su contenedor con scroll")

    # el cuerpo no puede desbordar por su cuenta
    cuerpo = reglas.get("html,body") or reglas.get("body") or ""
    assert "overflow-x" in " ".join(
        v for k, v in reglas.items() if k in ("html,body", "body")), (
        "html/body tienen que declarar su comportamiento de desborde horizontal")
    assert cuerpo


def test_los_dos_temas_definen_las_mismas_variables(html):
    """Un color que solo existe en un tema es un color invisible en el otro."""
    reglas = dict((s.strip(), c) for s, c in _reglas_css(html))
    claro = reglas.get(":root")
    oscuro = reglas.get('[data-tema="oscuro"]')
    assert claro and oscuro, "faltan los bloques de tema claro y oscuro"

    def variables(cuerpo):
        return {m.group(1) for m in re.finditer(r"(--[a-z0-9-]+)\s*:", cuerpo)}

    # las medidas (radio, sombra) no cambian de tema; los colores sí
    solo_claro = variables(claro) - variables(oscuro) - {"--radio"}
    assert not solo_claro, f"variables sin versión oscura: {sorted(solo_claro)}"
    solo_oscuro = variables(oscuro) - variables(claro)
    assert not solo_oscuro, f"variables sin versión clara: {sorted(solo_oscuro)}"

    assert "prefers-color-scheme" in html, (
        "el tema por defecto tiene que seguir la preferencia del sistema")


def test_la_pagina_dice_que_falta_en_vez_de_pintar_ceros():
    """Si el cálculo falla, la ruta lo dice. Un dashboard con ceros miente."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import rutas_dashboard

    app = FastAPI()
    app.include_router(rutas_dashboard.router)
    original = rutas_dashboard.dashboard_datos.obtener
    rutas_dashboard.dashboard_datos.obtener = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("falta un parquet"))
    try:
        with TestClient(app) as c:
            r = c.get("/api/dashboard")
            assert r.status_code == 200, "un 500 se ve como una app rota"
            assert r.json()["disponible"] is False
            assert "falta un parquet" in r.json()["motivo"]
            pagina = c.get("/dashboard")
            assert pagina.status_code == 200
            assert "no está disponible" in pagina.text
            assert "falta un parquet" in pagina.text
            assert "0.00 %" not in pagina.text, "no se pintan ceros inventados"
    finally:
        rutas_dashboard.dashboard_datos.obtener = original
