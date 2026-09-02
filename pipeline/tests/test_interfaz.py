"""ING-6 · Lo que la pantalla enseña tiene que ser verdad.

Cuatro riesgos que solo se ven aquí, y ninguno revienta por su cuenta:

1. **El selector de corte no recalcula.** La cobertura cambia con el corte
   (83.96 % … 89.26 %). Dejarla fija sería enseñar el número de otro día.
2. **Los porcentajes salen con distinto formato** según quién los pinte.
3. **El filtro por tipo de oferta miente.** Se resuelve vectorizado sobre los
   38,000; si divergiera de `POST /api/decidir`, el selector enseñaría clientes
   que no reciben lo que el filtro promete.
4. **La línea del tiempo se fuga.** Un solo evento posterior al corte y el
   dibujo estaría enseñando lo que el sistema no puede ver.
"""
from __future__ import annotations

import re

import pytest

import comun
from comun import ASOF, CLIENTE_AHORRO, CLIENTE_ESTRELLA, CLIENTE_FATIGADO

# `86.43 %`, `0.00 %`, `-1.50 %`: dos decimales, ni uno más ni uno menos.
PORCENTAJE = re.compile(r"^-?\d+\.\d{2} %$")

CORTES = ["2026-05-23", "2026-05-30", "2026-06-09", "2026-06-14", "2026-06-16"]


@pytest.fixture(scope="module")
def api():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


def _textos_de_porcentaje(nodo, ruta="", fuera=None):
    """Todos los `*_texto` que son porcentajes, con su ruta, para poder señalarlos."""
    fuera = fuera if fuera is not None else []
    if isinstance(nodo, dict):
        for k, v in nodo.items():
            if isinstance(v, str) and v.endswith(" %"):
                fuera.append((f"{ruta}.{k}", v))
            else:
                _textos_de_porcentaje(v, f"{ruta}.{k}", fuera)
    elif isinstance(nodo, list):
        for i, v in enumerate(nodo):
            _textos_de_porcentaje(v, f"{ruta}[{i}]", fuera)
    return fuera


# ==========================================================================
# 1 · El selector de corte recalcula la cobertura
# ==========================================================================
def test_contexto_publica_los_cinco_cortes_con_su_cobertura(api):
    ctx = api.get("/api/contexto").json()
    cortes = {c["corte"]: c for c in ctx["cortes"]}
    assert sorted(cortes) == CORTES, "las 5 fotos as-of de pipeline/artifacts/"
    for corte, c in cortes.items():
        cob = c["cobertura"]
        assert cob["n_clientes"] == 38000
        assert 0 < cob["pct_silencio"] < 100
        assert round(cob["pct_silencio"] + cob["pct_oferta"], 2) == 100.0
        assert cob["asof"] == corte, "la cobertura de un corte se mide en ese corte"


def test_la_cobertura_cambia_con_el_corte(api):
    """Si fuera la misma en los 5, estaría fija en vez de recalculada."""
    ctx = api.get("/api/contexto").json()
    valores = {c["corte"]: c["cobertura"]["pct_silencio"] for c in ctx["cortes"]}
    assert len(set(valores.values())) == len(CORTES), (
        f"la cobertura no se está recalculando por corte: {valores}")


def test_decidir_en_otro_corte_devuelve_la_cobertura_de_ese_corte(api):
    """El contador que acompaña a la decisión es el del día que se decide."""
    a = api.post("/api/decidir", json={"customer_id": CLIENTE_ESTRELLA,
                                       "asof": "2026-06-16T12:00:00"}).json()
    b = api.post("/api/decidir", json={"customer_id": CLIENTE_ESTRELLA,
                                       "asof": "2026-05-23T12:00:00"}).json()
    assert a["cobertura"]["asof"] == "2026-06-16"
    assert b["cobertura"]["asof"] == "2026-05-23"
    assert a["cobertura"]["pct_silencio"] != b["cobertura"]["pct_silencio"]


def test_health_publica_la_cobertura_de_cada_corte(api):
    h = api.get("/health").json()
    assert sorted(h["cortes_features"]) == CORTES
    for corte in CORTES:
        assert h["coberturas_por_corte"][corte]["asof"] == corte


def test_el_selector_de_corte_esta_en_la_pantalla_y_no_escrito_a_mano(api):
    html = api.get("/").text
    assert 'id="sel-corte"' in html, "no hay selector de corte"
    for corte in CORTES:
        assert corte not in html, (
            f"el corte {corte} está escrito a mano en la plantilla: la lista sale de "
            f"/api/contexto, que la lee del disco")


# ==========================================================================
# 2 · Todo porcentaje con exactamente dos decimales
# ==========================================================================
@pytest.mark.parametrize("entrada,esperado", [
    (86.4321, "86.43 %"), (14.0, "14.00 %"), (0, "0.00 %"), (100, "100.00 %"),
    (None, "—"),
])
def test_formato_pct(entrada, esperado):
    from app.formato import pct
    assert pct(entrada) == esperado


def test_formato_pct_desde_fraccion():
    from app.formato import pct
    assert pct(0.059184, de_fraccion=True) == "5.92 %"


@pytest.mark.parametrize("ruta", ["/health", "/api/contexto", "/api/clientes"])
def test_los_porcentajes_de_la_api_llevan_dos_decimales(api, ruta):
    for clave, valor in _textos_de_porcentaje(api.get(ruta).json()):
        assert PORCENTAJE.match(valor), f"{ruta}{clave} = {valor!r}"


def test_los_porcentajes_del_post_llevan_dos_decimales(api):
    d = api.post("/api/decidir", json={"customer_id": CLIENTE_AHORRO, "asof": ASOF}).json()
    encontrados = _textos_de_porcentaje(d)
    assert encontrados, "el POST no publica ni un porcentaje formateado"
    for clave, valor in encontrados:
        assert PORCENTAJE.match(valor), f"{clave} = {valor!r}"


def test_la_pantalla_formatea_los_porcentajes_en_un_solo_sitio(api):
    html = api.get("/").text
    assert "toFixed(2) + ' %'" in html, (
        "la plantilla debe tener un único formateador de porcentaje")


# ==========================================================================
# 3 · El número ambiguo, desarmado en sus tres factores
# ==========================================================================
def test_la_oferta_trae_los_tres_factores_en_sus_unidades(api):
    d = api.post("/api/decidir", json={"customer_id": CLIENTE_AHORRO, "asof": ASOF}).json()
    o = d["ofertas"][0]
    ex = o["explicacion"]
    claves = [f["clave"] for f in ex["factores"]]
    assert claves == ["p_intencion", "p_enganche", "valor"], (
        "los tres factores del score, por separado y en este orden")

    p_int, p_eng, valor = ex["factores"]
    assert p_int["unidad"] == "porcentaje" and PORCENTAJE.match(p_int["texto"])
    assert p_eng["unidad"] == "porcentaje" and PORCENTAJE.match(p_eng["texto"])
    assert valor["unidad"] == "dias" and valor["texto"].endswith(" días"), (
        "el valor está en días de descubierto evitados, no en un número suelto")

    # cada número dice qué mide, sobre qué población y cómo se lee
    for f in ex["factores"]:
        assert f["que_mide"], f["clave"]
        assert f["como_se_lee"], f["clave"]
    assert ex["resultado"]["formula"] == "score = p_intencion × p_enganche × V"


def test_el_score_es_de_verdad_el_producto_de_los_tres(api):
    d = api.post("/api/decidir", json={"customer_id": CLIENTE_AHORRO, "asof": ASOF}).json()
    o = d["ofertas"][0]
    # Los tres factores viajan redondeados a 4 decimales y el score a 6: la
    # tolerancia es la del redondeo publicado, no un margen de comodidad.
    assert o["score"] == pytest.approx(
        o["p_intencion"] * o["p_enganche"] * o["V"], abs=1e-4)


def test_la_referencia_esta_calculada_no_estimada(api):
    """`veces sobre la base` y `percentil` tienen que cuadrar con los datos."""
    from app.main import app

    d = api.post("/api/decidir", json={"customer_id": CLIENTE_AHORRO, "asof": ASOF}).json()
    o = d["ofertas"][0]
    ref = o["explicacion"]["factores"][0]["referencia"]
    vista = app.state.panorama.de(o["corte_features"])

    # la tasa base es el conteo observado de labels_intent.parquet en ese corte
    assert ref["tasa_base"] == vista.tasa_base_intencion[o["producto"]]
    assert ref["veces"] == pytest.approx(o["p_intencion"] / ref["tasa_base"], abs=0.01)

    # el percentil es la posición real dentro de la distribución de los 38,000
    dist = vista.p_intencion[o["producto"]]
    esperado = round(100.0 * (dist < o["p_intencion"]).sum() / len(dist), 2)
    assert ref["percentil"] == pytest.approx(esperado, abs=0.01)
    assert 0.0 <= ref["percentil"] <= 100.0


def test_el_valor_usa_lambda_266(api):
    """λ por defecto es 266, no 165."""
    h = api.get("/health").json()
    assert h["escalera"]["lambda"] == 266.0
    d = api.post("/api/decidir", json={"customer_id": CLIENTE_AHORRO, "asof": ASOF}).json()
    assert "266" in d["ofertas"][0]["explicacion"]["factores"][2]["que_mide"]


def test_la_explicacion_no_se_atribuye_al_modelo_lo_que_no_es(api):
    """El motor de razones explica con el hecho del cliente, no con contribuciones."""
    d = api.post("/api/decidir", json={"customer_id": CLIENTE_AHORRO, "asof": ASOF}).json()
    razon = d["ofertas"][0]["razon"].lower()
    assert "contribución" not in razon and "regresión" not in razon


# ==========================================================================
# 4 · La traza y los silencios, en lenguaje llano
# ==========================================================================
def test_cada_puerta_de_la_traza_trae_nombre_llano_y_que_comprueba(api):
    d = api.post("/api/decidir", json={"customer_id": CLIENTE_ESTRELLA, "asof": ASOF}).json()
    assert len(d["traza"]) == 8
    for i, t in enumerate(d["traza"], start=1):
        assert t["orden"] == i, "la traza se lee en orden de evaluación"
        assert t["puerta_nombre"] and t["puerta_nombre"] != t["puerta"]
        assert t["puerta_comprueba"] and t["puerta_cierra_si"]
        assert t["resultado_etiqueta"] and t["resultado_texto"]


def test_no_activa_se_explica_como_alcance_y_no_como_fallo(api):
    d = api.post("/api/decidir", json={"customer_id": CLIENTE_ESTRELLA, "asof": ASOF}).json()
    no_activas = [t for t in d["traza"] if t["resultado"] == "no_activa"]
    assert {t["puerta"] for t in no_activas} == {"S5_descartes", "S7_confianza"}
    for t in no_activas:
        assert t["puerta_activa"] is False
        assert "no cierra a nadie" in t["resultado_texto"]
        assert "fallo" in t["resultado_texto"], (
            "hay que decir explícitamente que no activa no es un error")


def test_los_silencios_traen_la_puerta_en_lenguaje_llano(api):
    d = api.post("/api/decidir", json={"customer_id": CLIENTE_FATIGADO, "asof": ASOF}).json()
    assert d["silencios"]
    for s in d["silencios"]:
        assert s["producto_titulo"] and s["puerta_nombre"] and s["puerta_comprueba"]
        assert s["razon"] and s["razon"] != "Sin razón registrada."


def test_la_senal_explica_el_estado_y_el_cupo(api):
    d = api.post("/api/decidir", json={"customer_id": CLIENTE_FATIGADO, "asof": ASOF}).json()
    for producto in d["catalogo"]:
        s = d["senales"][producto]
        assert s["momento_etiqueta"] and s["momento_texto"]
        assert s["cupo"] == 2
        assert s["cupo_texto"] == f"{s['exposiciones']} de 2"
        assert s["cupo_restante"] == max(0, 2 - s["exposiciones"])


def test_el_glosario_explica_el_cupo_con_la_cifra_de_los_datos(api):
    g = api.get("/api/contexto").json()["glosario"]
    # 04_fatigue_curve.csv: en la 3ª exposición 3.51 % de enganche y 2.53 % de baja
    assert "0.72 bajas" in g["cupo"]["texto"]
    assert "3.51 %" in g["cupo"]["texto"] and "2.53 %" in g["cupo"]["texto"]
    for clave in ("corte", "silencio", "p_intencion", "p_enganche", "valor",
                  "score", "tasa_base", "percentil", "senal", "traza"):
        assert g[clave]["titulo"] and g[clave]["texto"], clave


# ==========================================================================
# 5 · El filtro por tipo de oferta
# ==========================================================================
@pytest.mark.parametrize("tipo", ["savings_goal", "loan_offer", "bill_reminder"])
def test_el_filtro_devuelve_solo_a_quien_recibiria_ese_aviso(api, tipo):
    d = api.get(f"/api/clientes?oferta={tipo}&corte=2026-06-16&limite=8").json()
    libres = [c for c in d["clientes"] if not c["curado"]]
    assert libres, f"el filtro de {tipo} no devuelve a nadie"
    for c in libres:
        assert c["oferta_prevista"] == tipo
        # y de verdad: se vuelve a decidir cliente a cliente
        r = api.post("/api/decidir", json={"customer_id": c["customer_id"],
                                           "asof": "2026-06-16T12:00:00"}).json()
        assert r["ofertas"] and r["ofertas"][0]["producto"] == tipo, (
            f"el filtro promete {tipo} y la decisión real da otra cosa "
            f"para {c['customer_id']}")


def test_el_filtro_de_silencio_y_su_razon(api):
    d = api.get("/api/clientes?oferta=silencio&razon=S2_cupo&corte=2026-06-16"
                "&limite=5").json()
    libres = [c for c in d["clientes"] if not c["curado"]]
    assert libres
    for c in libres:
        assert c["oferta_prevista"] == "silencio"
        assert c["razon_silencio"] == "S2_cupo"
        r = api.post("/api/decidir", json={"customer_id": c["customer_id"],
                                           "asof": "2026-06-16T12:00:00"}).json()
        assert r["decision"] == "silencio"
        assert r["puerta_reportada"] == "S2_cupo"


def test_los_conteos_del_filtro_cuadran_con_la_cobertura(api):
    """Los que reciben algún aviso son exactamente los que la cobertura cuenta."""
    d = api.get("/api/clientes?corte=2026-06-16&limite=1").json()
    conteo = d["conteo_por_oferta"]
    con_oferta = sum(n for k, n in conteo.items() if k != "silencio")
    ctx = api.get("/api/contexto").json()
    cob = next(c for c in ctx["cortes"] if c["corte"] == "2026-06-16")["cobertura"]
    assert con_oferta == cob["n_con_oferta"]
    assert sum(conteo.values()) == cob["n_clientes"] == 38000


def test_limit_increase_nunca_se_ofrece_porque_su_valor_es_negativo(api):
    """V(línea,266) = −0.077: la puerta S4 lo cierra para todo el mundo."""
    d = api.get("/api/clientes?corte=2026-06-16&limite=1").json()
    assert d["conteo_por_oferta"].get("limit_increase", 0) == 0


def test_un_filtro_sin_panorama_lo_dice_en_vez_de_inventar(api):
    d = api.get("/api/clientes?oferta=savings_goal&corte=2020-01-01&limite=5").json()
    assert [c for c in d["clientes"] if not c["curado"]] == []
    assert d["filtro"]["motivo"], "si no hay panorama hay que decir por qué"


# ==========================================================================
# 6 · La línea del tiempo no puede mirar más allá del corte
# ==========================================================================
def test_la_linea_de_tiempo_no_trae_nada_posterior_al_corte(api):
    for cid in (CLIENTE_AHORRO, CLIENTE_ESTRELLA, CLIENTE_FATIGADO):
        d = api.get(f"/api/clientes/{cid}/linea-tiempo?asof={ASOF}").json()
        corte = ASOF.replace("T", " ")
        for e in d["navegacion"] + d["avisos"]:
            assert e["ts"] < corte, f"{cid}: {e['ts']} es posterior al corte {corte}"
            assert e["horas_antes_del_corte"] > 0
            assert e["pos_pct"] <= d["corte_pos_pct"] + 1e-6
        assert d["n_posteriores_al_corte"] == 0


def test_la_linea_de_tiempo_no_se_mueve_con_eventos_del_futuro(api):
    """Prueba negativa: mover el `asof` hacia atrás solo puede quitar marcas."""
    tarde = api.get(f"/api/clientes/{CLIENTE_AHORRO}/linea-tiempo?asof={ASOF}").json()
    pronto = api.get(f"/api/clientes/{CLIENTE_AHORRO}/linea-tiempo"
                     f"?asof=2026-06-15T12:00:00").json()
    tardios = {e["ts"] for e in tarde["navegacion"]}
    assert {e["ts"] for e in pronto["navegacion"]} <= tardios


def test_la_linea_de_tiempo_marca_el_corte_y_deja_la_zona_ciega(api):
    d = api.get(f"/api/clientes/{CLIENTE_AHORRO}/linea-tiempo?asof={ASOF}").json()
    assert 0 < d["corte_pos_pct"] < 100, "el corte tiene que caer dentro del eje"
    assert d["zona_ciega"]["desde_pct"] == d["corte_pos_pct"]
    assert d["fin"] > d["asof"].replace("T", " "), (
        "el eje sigue después del corte: la zona ciega se dibuja vacía a propósito")
    assert d["inicio"] < d["asof"].replace("T", " ")


def test_los_dos_carriles_comparten_eje(api):
    d = api.get(f"/api/clientes/{CLIENTE_FATIGADO}/linea-tiempo?asof={ASOF}").json()
    assert d["n_avisos"] > 0, "este cliente tiene el cupo agotado: algo se le mostró"
    for a in d["avisos"]:
        assert a["carril"] == "aviso" and {"tipo", "exposure_no", "enganchado"} <= set(a)
    for e in d["navegacion"]:
        assert e["carril"] == "navegacion" and {"pantalla", "accion"} <= set(e)


def test_la_linea_de_tiempo_de_un_cliente_inexistente_es_404(api):
    assert api.get("/api/clientes/1/linea-tiempo").status_code == 404


# ==========================================================================
# 7 · La barra superior
# ==========================================================================
def test_el_lema_es_el_nuevo(api):
    html = api.get("/").text
    assert "tu asistente que sabe cuándo actuar" in html
    assert "sabe cuándo callarse" not in html


def test_hay_interruptor_de_tema_y_recuerda_la_eleccion(api):
    html = api.get("/").text
    assert "data-tema" in html and "localStorage" in html
    assert 'setItem(\'nu-moments-tema\'' in html
    assert '[data-tema="oscuro"]' in html, "hace falta la paleta del modo oscuro"


def test_las_ayudas_son_alcanzables_con_el_teclado(api):
    html = api.get("/").text
    assert html.count('class="ay-b"') >= 10, "cada número necesita su explicación"
    # se abren al enfocar, no solo al pasar el ratón, y se cierran con Escape
    assert '@focus="abrir()"' in html and '@keydown.escape.window="cerrar()"' in html
    assert 'role="tooltip"' in html


def test_el_contexto_trae_las_ocho_puertas_en_lenguaje_llano(api):
    ctx = api.get("/api/contexto").json()
    assert len(ctx["puertas"]) == 8
    for p in ctx["puertas"]:
        assert p["puerta_nombre"] and p["puerta_comprueba"]
    assert {"pasa", "cierra", "no_activa"} <= set(ctx["resultados"])
    assert set(ctx["momentos"]) == {"on_time", "warm", "cold", "never"}


# ==========================================================================
# 8 · La pantalla no se desplaza de lado
# ==========================================================================
# El bug era este: `.factor.res` compartía clase con la insignia de la traza,
# `.res`, que trae `white-space:nowrap`. El texto «Percentil 99.52 % frente a
# los demás en este corte» se volvía indivisible, ese ancho pasaba a ser el
# mínimo de la columna del grid, y el mínimo empujaba `.factores` → `.oferta`
# → `main` → `body`. Con 1440 px de ventana el `scrollWidth` era 1508.
#
# Se comprueba sin navegador: son reglas sobre el CSS de la plantilla, no sobre
# el renderizado. Cada una habría cazado el fallo original.
# --------------------------------------------------------------------------
ANCHO_MINIMO_SOPORTADO = 320       # el móvil más estrecho que soportamos


def _reglas_css(html):
    """Los bloques `selector{declaraciones}` del `<style>` de la plantilla."""
    estilo = re.search(r"<style>(.*?)</style>", html, re.S)
    assert estilo, "la plantilla debe traer su CSS en línea (sin red)"
    css = re.sub(r"/\*.*?\*/", "", estilo.group(1), flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def _declaraciones(cuerpo):
    return [d.strip() for d in cuerpo.split(";") if d.strip()]


def test_ninguna_pista_de_grid_usa_1fr_sin_minmax(api):
    """`1fr` es `minmax(auto,1fr)`: su mínimo es el contenido, y ese fue el bug.

    Cualquier pista flexible tiene que ser `minmax(0,1fr)` para poder encogerse
    por debajo de su contenido en vez de empujar la página.
    """
    culpables = []
    for selector, cuerpo in _reglas_css(api.get("/").text):
        for d in _declaraciones(cuerpo):
            if not d.startswith("grid-template-columns"):
                continue
            valor = d.split(":", 1)[1]
            # `minmax(0,1fr)` y `repeat(n,minmax(0,1fr))` sí valen; `1fr` suelto no.
            limpio = re.sub(r"minmax\(\s*0\s*,\s*1fr\s*\)", "OK", valor)
            # `minmax(min(100%,Npx),1fr)` es la forma segura de una pista que
            # quiere N px «si caben»: el `min(100%,…)` acota el suelo al ancho
            # del contenedor, así que la pista cede cuando no cabe. Un
            # `minmax(Npx,1fr)` a secas —admitido en la línea de abajo— es un
            # suelo duro: a 320 px una pista de 260 px dentro de un contenedor
            # de 218 px se sale por la derecha. Por eso esta forma se reconoce
            # primero y es la que hay que preferir al escribir rejillas nuevas.
            limpio = re.sub(
                r"minmax\(\s*min\(\s*100%\s*,\s*\d+(?:\.\d+)?px\s*\)\s*,\s*1fr\s*\)",
                "OK", limpio)
            limpio = re.sub(r"minmax\(\s*\d+px\s*,\s*1fr\s*\)", "OK", limpio)
            if "1fr" in limpio:
                culpables.append(f"{selector.strip()} {{ {d} }}")
    assert not culpables, (
        "estas pistas pueden reventar el ancho de la página; usa minmax(0,1fr):\n  "
        + "\n  ".join(culpables))


def test_ningun_ancho_fijo_supera_la_pantalla_mas_estrecha(api):
    """Un `width` o `min-width` en píxeles mayor que 320 px no puede encogerse.

    Solo se admite si el elemento vive dentro de un contenedor con `overflow-x`
    propio: eso es exactamente lo que pide la regla —que lo intrínsecamente
    ancho se desplace dentro de su caja, nunca arrastrando al `body`—. Cada
    excepción se declara aquí con su envoltorio, y el test de abajo comprueba
    que ese envoltorio existe de verdad y tiene el scroll.
    """
    # {selector ancho: envoltorio que lo desplaza}
    excepciones = {".tl": ".tl-scroll", "table.t8": ".tabla-scroll"}

    culpables = []
    for selector, cuerpo in _reglas_css(api.get("/").text):
        limpio = selector.strip()
        for d in _declaraciones(cuerpo):
            m = re.match(r"(min-width|width)\s*:\s*(\d+(?:\.\d+)?)px$", d)
            if not m or float(m.group(2)) <= ANCHO_MINIMO_SOPORTADO:
                continue
            if limpio in excepciones:
                continue
            culpables.append(f"{limpio} {{ {d} }}")
    assert not culpables, (
        f"anchos fijos por encima de {ANCHO_MINIMO_SOPORTADO} px sin contenedor "
        f"con overflow propio:\n  " + "\n  ".join(culpables))


def test_lo_intrinsecamente_ancho_se_desplaza_en_su_contenedor(api):
    """La línea del tiempo y la tabla ancha: `min-width` + envoltorio con scroll."""
    html = api.get("/").text
    for envoltorio, dentro in (("tl-scroll", "tl"), ("tabla-scroll", "t8")):
        assert f'class="{envoltorio}"' in html, (
            f"falta el contenedor {envoltorio}: lo ancho tiene que desplazarse dentro")
        regla = next((c for s, c in _reglas_css(html)
                      if s.strip().startswith("." + envoltorio)), None)
        assert regla and "overflow-x:auto" in regla.replace(" ", ""), envoltorio
        cuerpo = next((c for s, c in _reglas_css(html)
                       if s.strip() in (f".{dentro}", f"table.{dentro}")), "")
        assert "min-width" in cuerpo, (
            f"{dentro} necesita un ancho mínimo legible dentro de {envoltorio}")


# --------------------------------------------------------------------------
# 8.b · …tampoco con una burbuja de ayuda abierta
# --------------------------------------------------------------------------
# El estado que se escapó de la batería anterior. Una supervisión midió con
# Chrome sin cabeza 42 combinaciones (320–2560 px, claro y oscuro, panel
# abierto, `<details>` desplegados) y dio exceso 0 en todas **en reposo**;
# abriendo las burbujas de una en una, la de «Cómo se lee el histograma»
# desbordaba 70 px a 768 y 38 px a 800 —banda medida 701–830 px—.
#
# La causa es geométrica: `.ay-p` es `position:absolute` con
# `width:min(320px,78vw)` centrada sobre su botón, así que si el botón queda a
# menos de media burbuja del borde, la burbuja sale de la pantalla y arrastra
# el `scrollWidth`. Lo único que la sujeta es el anclaje al viewport, y ese
# anclaje vivía solo bajo 700 px: entre 701 y 1020 no había nada.
#
# Se comprueba sin navegador, como el resto de esta sección: son reglas sobre
# el CSS. La batería recorre los anchos y exige que en todos los de la banda
# medida la burbuja esté anclada, que el anclaje llegue hasta donde `main` pasa
# a una columna, y que el anclaje de verdad neutralice el ancho.
ANCHOS_DE_PRUEBA = [320, 360, 390, 414, 480, 560, 640, 700, 701, 720, 768, 800,
                    830, 900, 1000, 1020, 1024, 1280, 1440, 1920, 2560]

# El techo de la banda en la que la supervisión midió desbordamiento real.
BANDA_MEDIDA_HASTA = 830


def _bloques_media(html):
    """`[(condición, css interno)]` de cada `@media` de la plantilla."""
    estilo = re.search(r"<style>(.*?)</style>", html, re.S)
    assert estilo
    css = re.sub(r"/\*.*?\*/", "", estilo.group(1), flags=re.S)
    fuera = []
    for m in re.finditer(r"@media([^{]+)\{", css):
        i, prof = m.end(), 1
        while i < len(css) and prof:
            prof += 1 if css[i] == "{" else -1 if css[i] == "}" else 0
            i += 1
        fuera.append((m.group(1).strip(), css[m.end():i - 1]))
    return fuera


def _max_width(condicion):
    m = re.search(r"max-width\s*:\s*(\d+)px", condicion)
    return int(m.group(1)) if m else None


def _anclaje_de_la_burbuja(html):
    """`(ancho máximo del anclaje, declaraciones del bloque anclado)`."""
    for condicion, cuerpo in _bloques_media(html):
        for selector, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", cuerpo):
            if ".ay-p" in selector and "position:fixed" in decl.replace(" ", ""):
                return _max_width(condicion), decl.replace(" ", "")
    return None, ""


def _breakpoint_de_una_columna(html):
    """El ancho al que `main` deja de tener dos columnas."""
    for condicion, cuerpo in _bloques_media(html):
        for selector, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", cuerpo):
            if selector.strip() == "main" and "grid-template-columns" in decl:
                if "340px" not in decl:
                    return _max_width(condicion)
    return None


def test_la_burbuja_de_ayuda_no_puede_desbordar_por_si_sola(api):
    """`width:min(320px,78vw)`: nunca más ancha que la pantalla, ni a 320 px."""
    reglas = {s.strip(): c.replace(" ", "") for s, c in _reglas_css(api.get("/").text)}
    assert ".ay-p" in reglas, "la burbuja de ayuda debe tener su regla propia"
    ancho = re.search(r"width:min\((\d+)px,(\d+)vw\)", reglas[".ay-p"])
    assert ancho, f"`.ay-p` necesita un ancho acotado por vw: {reglas['.ay-p']}"
    tope_vw = int(ancho.group(2))
    assert tope_vw <= 100, "un vw mayor que 100 desborda por sí solo"
    for w in ANCHOS_DE_PRUEBA:
        assert min(int(ancho.group(1)), tope_vw * w / 100) <= w


def test_la_burbuja_de_ayuda_esta_anclada_hasta_una_columna(api):
    """El anclaje tiene que llegar hasta el breakpoint de `main`, no a 700 px.

    Si los dos números se separan vuelve a abrirse la banda huérfana en la que
    la burbuja es absoluta pero la página ya es estrecha.
    """
    html = api.get("/").text
    anclaje, decl = _anclaje_de_la_burbuja(html)
    una_columna = _breakpoint_de_una_columna(html)

    assert anclaje, "no hay ningún @media que ancle `.ay-p` al viewport"
    assert una_columna, "no se encuentra el breakpoint de una columna de `main`"
    assert anclaje == una_columna, (
        f"el anclaje de la burbuja ({anclaje} px) y el paso a una columna "
        f"({una_columna} px) tienen que ser el mismo ancho")
    assert anclaje >= BANDA_MEDIDA_HASTA, (
        f"la banda 701–{BANDA_MEDIDA_HASTA} px desbordaba con la burbuja "
        f"abierta; el anclaje llega solo a {anclaje} px")

    # y el anclaje neutraliza de verdad el ancho de la burbuja
    for trozo in ("position:fixed", "left:10px", "right:10px", "width:auto",
                  "transform:none"):
        assert trozo in decl, f"al anclaje le falta {trozo}: {decl}"
    assert "max-width:none" in decl, "un max-width residual reintroduce el ancho fijo"


def test_bateria_de_anchos_con_una_burbuja_abierta(api):
    """El estado «burbuja abierta», ancho por ancho.

    Por debajo del anclaje el exceso es 0 **por construcción**: la burbuja es
    `position:fixed` entre `left:10px` y `right:10px`, así que su caja no puede
    salir del viewport pase lo que pase con el botón que la abre. Por encima,
    la burbuja vuelve a ser absoluta y el CSS ya no lo garantiza solo: ahí la
    medición con navegador sin cabeza dio exceso 0, y lo que este test fija es
    que no quede ni un ancho de la banda medida fuera del anclaje.
    """
    html = api.get("/").text
    anclaje, decl = _anclaje_de_la_burbuja(html)
    absolutos = []
    for w in ANCHOS_DE_PRUEBA:
        if w <= anclaje:
            # `fixed` + left + right ⇒ ancho usado = viewport − 20 px
            assert "position:fixed" in decl and "left:10px" in decl
            continue
        absolutos.append(w)
        assert w > BANDA_MEDIDA_HASTA, (
            f"a {w} px la burbuja sigue siendo absoluta y ese ancho está dentro "
            f"de la banda 701–{BANDA_MEDIDA_HASTA} px que se midió desbordando")
    assert absolutos, "la batería tiene que cubrir también anchos de escritorio"


def test_ningun_media_posterior_devuelve_la_burbuja_a_absoluta(api):
    """Una regla más específica más abajo podría deshacer el anclaje."""
    html = api.get("/").text
    anclaje, _ = _anclaje_de_la_burbuja(html)
    for condicion, cuerpo in _bloques_media(html):
        tope = _max_width(condicion)
        if tope is None or tope > anclaje:
            continue
        for selector, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", cuerpo):
            if ".ay-p" not in selector:
                continue
            plano = decl.replace(" ", "")
            assert "position:absolute" not in plano, (
                f"@media({condicion}) devuelve `.ay-p` a absolute: {decl}")


def test_el_resultado_del_score_no_comparte_clase_con_la_insignia_nowrap(api):
    """La regresión exacta: `.factor.res` heredaba `white-space:nowrap` de `.res`.

    El resultado del score es ahora `.factor.total`. Si alguien vuelve a
    llamarlo `res`, esto se rompe antes que la maqueta.
    """
    html = api.get("/").text
    assert 'class="factor total"' in html
    assert 'class="factor res"' not in html
    nowrap = {s.strip() for s, c in _reglas_css(html)
              if "white-space:nowrap" in c.replace(" ", "")}
    assert ".res" in nowrap, "la insignia de la traza sigue siendo nowrap, como debe"
    for selector, cuerpo in _reglas_css(html):
        if selector.strip() in (".factor", ".factor.total", ".factores"):
            assert "nowrap" not in cuerpo, (
                f"{selector} no puede ser nowrap: su contenido son frases largas")


# ==========================================================================
# 9 · Las gráficas del «por qué»: la misma cifra en otra forma
# ==========================================================================
# Una gráfica es la puerta de atrás por la que entra un número inventado: nadie
# recuenta un histograma a ojo. Aquí se recuenta todo contra los datos.
# --------------------------------------------------------------------------
def _graficas(api, cliente=CLIENTE_AHORRO, asof=ASOF):
    d = api.post("/api/decidir", json={"customer_id": cliente, "asof": asof}).json()
    o = d["ofertas"][0]
    return o, o["explicacion"]["graficas"]


def test_el_reparto_de_la_poblacion_cuadra_con_los_38000(api):
    """La barra apilada es `conteo_por_oferta`, no una estimación."""
    from app.main import app

    o, g = _graficas(api)
    vista = app.state.panorama.de(o["corte_features"])
    conteo = vista.conteo_por_oferta()

    p = g["poblacion"]
    assert p["n_total"] == 38000
    assert sum(s["n"] for s in p["segmentos"]) == 38000
    for s in p["segmentos"]:
        assert s["n"] == conteo[s["clave"]], s["clave"]
        assert PORCENTAJE.match(s["pct_texto"])
        assert s["pct"] == pytest.approx(100.0 * s["n"] / 38000, abs=0.01)

    # exactamente un segmento es el del cliente, y es el producto que se ofrece
    mios = [s for s in p["segmentos"] if s["es_del_cliente"]]
    assert len(mios) == 1 and mios[0]["clave"] == o["producto"]

    # y los silencios por puerta suman los que se quedan callados
    silencio = next(s["n"] for s in p["segmentos"] if s["clave"] == "silencio")
    assert sum(r["n"] for r in p["silencio_por_razon"]) == silencio


def test_el_histograma_reparte_a_los_38000_y_marca_el_cubo_del_cliente(api):
    o, g = _graficas(api)
    h = g["distribucion"]["histograma"]

    assert sum(b["n"] for b in h["bins"]) == h["n_total"] == 38000, (
        "el histograma tiene que contener a todos: si falta gente, el dibujo miente")
    assert len(h["bins"]) == h["n_bins"]

    # el cubo marcado es de verdad el que contiene el valor del cliente
    cubo = h["bins"][h["bin_cliente"]]
    assert cubo["desde"] <= o["p_intencion"] <= cubo["hasta"], (
        f"el cliente ({o['p_intencion']}) no cae en el cubo marcado {cubo}")
    assert cubo["n"] >= 1, "el cubo del cliente no puede estar vacío: él está dentro"

    # los cubos son contiguos y crecientes: ni huecos ni solapes
    for a, b in zip(h["bins"], h["bins"][1:]):
        assert a["hasta"] == b["desde"]

    # el alto de cada barra es su cuenta relativa al cubo más poblado
    tope = max(b["n"] for b in h["bins"])
    for b in h["bins"]:
        assert b["alto_pct"] == pytest.approx(100.0 * b["n"] / tope, abs=0.01)


def test_el_percentil_del_histograma_es_el_conteo_y_trae_los_dos_lados(api):
    """`percentil`, `n_encima` y la distribución tienen que decir lo mismo.

    El conteo se hace contra el valor **exacto** del cliente en la población,
    no contra el que se publica ya redondeado a 4 decimales: es la diferencia
    entre 622 y 623 (ver el test de abajo).
    """
    from app.main import app

    o, g = _graficas(api)
    vista = app.state.panorama.de(o["corte_features"])
    dist = vista.p_intencion[o["producto"]]
    exacto = vista.valor_intencion(o["producto"], CLIENTE_AHORRO)

    d = g["distribucion"]
    assert d["percentil"] == pytest.approx(
        100.0 * (dist < exacto).sum() / len(dist), abs=0.01)
    assert d["n_encima"] == int((dist > exacto).sum())
    assert d["n_total"] == len(dist) == 38000
    assert PORCENTAJE.match(d["percentil_texto"])
    # y la alternativa textual dice el mismo número que la barra
    assert d["percentil_texto"] in d["alternativa"]
    assert d["valor_texto"] in d["alternativa"]


def test_n_encima_es_el_conteo_directo_sobre_los_38000_y_no_cuenta_al_cliente(api):
    """La regresión exacta: «Solo 623 de 38 000» cuando eran 622.

    `p_intencion` se publica redondeada a 4 decimales (0.38691688 → 0.3869) y
    el percentil se calculaba con ese número contra el array **sin redondear**
    con `side="right"`. El propio cliente, que vive en el array con todos sus
    decimales, quedaba por encima de sí mismo y sumaba uno de más.

    Aquí se recuenta a mano sobre los 38 000 —`>` y `<` de numpy, sin
    `searchsorted`— y se comprueba además que el valor redondeado habría dado
    otra cifra: si alguien vuelve a contar con él, esto se rompe.
    """
    from app.main import app

    o, g = _graficas(api)
    vista = app.state.panorama.de(o["corte_features"])
    dist = vista.p_intencion[o["producto"]]
    exacto = vista.valor_intencion(o["producto"], CLIENTE_AHORRO)
    d = g["distribucion"]

    # el valor exacto del cliente está en la población y es el publicado
    assert exacto is not None
    assert round(exacto, 4) == o["p_intencion"]
    assert int((dist == exacto).sum()) == 1, "el cliente es uno de los 38 000"

    # el conteo directo, sin searchsorted
    n_encima = int((dist > exacto).sum())
    n_debajo = int((dist < exacto).sum())
    assert d["n_encima"] == n_encima == 622
    assert n_debajo + n_encima + 1 == 38000
    assert d["percentil"] == round(100.0 * n_debajo / 38000, 2) == 98.36
    assert d["n_encima_texto"] == "622"

    # y el número que producía el redondeo ya no se publica
    assert int((dist > o["p_intencion"]).sum()) == 623, (
        "si esto cambia, el escenario del bug dejó de existir y hay que "
        "revisar el test, no el código")
    assert d["n_encima"] != 623


def test_el_n_encima_del_score_tambien_cuenta_contra_el_valor_exacto(api):
    """El mismo patrón en el score: 181 publicados donde el conteo da 180."""
    from app.main import app

    o, _ = _graficas(api)
    vista = app.state.panorama.de(o["corte_features"])
    dist = vista.score[o["producto"]]
    exacto = vista.valor_score(o["producto"], CLIENTE_AHORRO)
    ref = o["explicacion"]["resultado"]["referencia"]

    assert exacto is not None and round(exacto, 6) == o["score"]
    assert ref["n_encima"] == int((dist > exacto).sum()) == 180
    assert int((dist > o["score"]).sum()) == 181, "el conteo con el redondeado"


def test_si_el_valor_publicado_no_es_el_de_la_poblacion_no_se_sustituye(api):
    """La salvaguarda: el exacto solo entra si es el mismo número.

    La vista se construye a las 12:00 del corte; una petición a otra hora del
    mismo día puede dar otro estado de señal y, con él, otro `p_enganche` y
    otro `score`. Cuando el `score` publicado y el de la población no son la
    misma cifra, el conteo tiene que seguir siendo el del número que se enseña
    —rankear otro sería enseñar el percentil de una cifra que no está en
    pantalla—.
    """
    from app.panorama import _mismo_numero

    assert _mismo_numero(0.38691688, 0.3869)
    assert _mismo_numero(0.10473516, 0.104735)
    assert _mismo_numero(0.49002032, 0.49), "menos decimales publicados, mismo número"
    assert not _mismo_numero(0.00909376, 0.013585), "señal distinta: otra cifra"

    from app.main import app

    # Y sobre los escenarios curados: cada `n_encima` es el conteo directo
    # contra la cifra que de verdad se enseña en pantalla.
    divergentes = 0
    for caso in api.get("/api/clientes").json()["clientes"][:9]:
        d = api.post("/api/decidir", json={"customer_id": caso["customer_id"],
                                           "asof": caso["asof"]}).json()
        for o in d.get("ofertas") or []:
            vista = app.state.panorama.de(o["corte_features"])
            ref = (o["explicacion"].get("resultado") or {}).get("referencia") or {}
            if vista is None or ref.get("n_encima") is None:
                continue
            dist = vista.score[o["producto"]]
            exacto = vista.valor_score(o["producto"], caso["customer_id"])
            if exacto is not None and _mismo_numero(exacto, o["score"]):
                assert ref["n_encima"] == int((dist > exacto).sum()), caso["clave"]
            else:
                divergentes += 1
                assert ref["n_encima"] == int((dist > o["score"]).sum()), (
                    f'{caso["clave"]}: se cuenta contra el score que se enseña')
    assert divergentes, (
        "ya no hay ningún caso con el score de la vista distinto del publicado: "
        "la salvaguarda dejó de tener sujeto y hay que revisarla")


def test_un_cubo_vacio_no_se_dibuja_como_uno_con_gente(api):
    """`Math.max(b.alto_pct, 1.8)` pintaba igual 0 clientes que 2.

    El suelo del 1.8 % existe para que un cubo de una o dos personas se vea;
    aplicado también al cubo vacío convertía «aquí no hay nadie» en «aquí hay
    poca gente». Y los cubos vacíos existen de verdad en estos datos.
    """
    from app.main import app
    from app.panorama import _histograma_log

    # 1 · el caso es real: mismo corte, mismo producto, cubos de 0 y de 1–3
    vista = app.state.panorama.de("2026-05-23")
    h = _histograma_log(vista.p_intencion["loan_offer"], None)
    vacios = [i for i, b in enumerate(h["bins"]) if b["n"] == 0]
    poquitos = [i for i, b in enumerate(h["bins"]) if 0 < b["n"] <= 3]
    assert vacios and poquitos, (
        "sin cubos vacíos y cubos casi vacíos a la vez este arreglo no tiene sujeto")

    # 2 · `alto_pct` no basta para separarlos: con miles de clientes en el cubo
    #     más poblado, un cubo de 1 y un cubo de 0 redondean los dos a 0.00 %.
    #     Por eso el dibujo tiene que mirar `n`, que sí distingue.
    for i in vacios + poquitos:
        assert h["bins"][i]["alto_pct"] < 1.8, (
            "estos son los que dependen del suelo del 1.8 % para verse")
    altos_vacios = {h["bins"][i]["alto_pct"] for i in vacios}
    altos_poquitos = {h["bins"][i]["alto_pct"] for i in poquitos}
    assert altos_vacios == {0.0}
    assert altos_vacios & altos_poquitos, (
        f"hay cubos con gente que publican el mismo alto que los vacíos "
        f"({sorted(altos_poquitos)}): el dibujo no puede fiarse del alto")

    # 3 · y la plantilla no le aplica el suelo al vacío
    html = api.get("/").text
    assert "b.n === 0 ? 0 : Math.max(b.alto_pct, 1.8)" in html, (
        "el suelo del 1.8 % no puede aplicarse a un cubo sin clientes")
    assert "vacio: b.n === 0" in html, "el cubo vacío necesita su propia clase"
    reglas = {sel.strip(): c.replace(" ", "") for sel, c in _reglas_css(html)}
    assert ".hist i.vacio" in reglas, "falta el dibujo del cubo vacío"
    assert "dotted" in reglas[".hist i.vacio"], (
        "el cubo vacío tiene que distinguirse por forma, no solo por alto")
    assert "background:transparent" in reglas[".hist i.vacio"]
    assert "min-height:0" in reglas[".hist i.vacio"], (
        "`.hist i` impone min-height:2px; el vacío tiene que soltarlo")


def test_las_dos_franjas_contiguas_no_se_leen_con_la_misma_escala(api):
    """El histograma es log10 y la regla de abajo es percentil lineal.

    En este cliente la marca cae al 85.80 % del ancho y su percentil es
    98.36 %: leer la primera franja como si fuera la segunda le quita 12 puntos
    de excepcionalidad. Las dos lecturas viajan juntas en la respuesta y la
    pantalla etiqueta cada eje con lo que mide.
    """
    o, g = _graficas(api)
    d = g["distribucion"]

    assert d["eje_es_percentil"] is False
    assert d["histograma"]["escala"] == "log10"
    assert d["pos_pct_cliente"] is not None
    marca = next(m for m in d["histograma"]["marcas"] if m["clave"] == "cliente")
    assert d["pos_pct_cliente"] == marca["pos_pct"], (
        "la posición publicada tiene que ser la de la marca que se dibuja")
    assert abs(d["pos_pct_cliente"] - d["percentil"]) > 1.0, (
        "en este cliente las dos escalas difieren; si dejaran de diferir habría "
        "que buscar otro caso, no borrar el aviso")

    # la nota dice los dos números, sin inventar ninguno
    assert d["pos_pct_cliente_texto"] in d["nota_escala"]
    assert d["percentil_texto"] in d["nota_escala"]
    assert "logarítmica" in d["nota_escala"]
    assert "no es el percentil" in d["alternativa"]

    # y la pantalla etiqueta las dos franjas y las separa
    html = api.get("/").text
    assert "probabilidad · escala log" in html
    assert "percentil · escala lineal" in html
    assert 'class="otra-escala"' in html, (
        "la regla del percentil necesita su propia caja: pegada al histograma "
        "se lee como una continuación del mismo eje")
    assert "nota_escala" in html, "la advertencia tiene que estar en la pantalla"


def test_las_marcas_del_histograma_son_la_mediana_la_base_y_el_cliente(api):
    import numpy as np

    from app.main import app

    o, g = _graficas(api)
    vista = app.state.panorama.de(o["corte_features"])
    dist = vista.p_intencion[o["producto"]]
    marcas = {m["clave"]: m for m in g["distribucion"]["histograma"]["marcas"]}

    assert set(marcas) == {"mediana", "tasa_base", "cliente"}
    assert marcas["mediana"]["valor"] == pytest.approx(float(np.median(dist)), abs=1e-6)
    assert marcas["tasa_base"]["valor"] == vista.tasa_base_intencion[o["producto"]]
    assert marcas["cliente"]["valor"] == o["p_intencion"]
    # cada marca cae dentro del eje, y la del cliente a su derecha si es mayor
    for m in marcas.values():
        assert 0.0 <= m["pos_pct"] <= 100.0
        assert PORCENTAJE.match(m["texto"])
    assert marcas["cliente"]["pos_pct"] > marcas["tasa_base"]["pos_pct"], (
        "este cliente está muy por encima de la tasa base: el dibujo debe decirlo")


def test_las_barras_contra_la_tasa_base_usan_la_tasa_base_real(api):
    from app.main import app

    o, g = _graficas(api)
    vista = app.state.panorama.de(o["corte_features"])
    bases = {"p_intencion": vista.tasa_base_intencion[o["producto"]],
             "p_enganche": vista.tasa_base_enganche[o["producto"]]}
    valores = {"p_intencion": o["p_intencion"], "p_enganche": o["p_enganche"]}

    barras = {b["clave"]: b for b in g["contra_base"]["barras"]}
    assert set(barras) == {"p_intencion", "p_enganche"}
    for clave, b in barras.items():
        assert b["poblacion"]["valor"] == bases[clave]
        assert b["cliente"]["valor"] == valores[clave]
        assert b["veces"] == pytest.approx(valores[clave] / bases[clave], abs=0.01)
        # el más alto ocupa la pista completa: los dos anchos comparten escala
        assert max(b["cliente"]["ancho_pct"], b["poblacion"]["ancho_pct"]) == 100.0
        tope = max(valores[clave], bases[clave])
        assert b["cliente"]["ancho_pct"] == pytest.approx(
            100.0 * valores[clave] / tope, abs=0.01)
        assert PORCENTAJE.match(b["cliente"]["texto"])
        assert PORCENTAJE.match(b["poblacion"]["texto"])
        assert b["veces_texto"] in b["alternativa"], "la alternativa textual repite el múltiplo"


def test_las_zonas_de_recencia_son_los_umbrales_de_la_politica(api):
    """El eje no se dibuja «bonito»: las zonas caen donde están los umbrales."""
    from pipeline.mapas import UMBRAL_ON_TIME_H, UMBRAL_WARM_H

    o, g = _graficas(api)
    r = g["recencia"]
    assert r["umbral_on_time_h"] == UMBRAL_ON_TIME_H == 24
    assert r["umbral_warm_h"] == UMBRAL_WARM_H == 168

    zonas = {z["clave"]: z for z in r["zonas"]}
    assert zonas["on_time"]["hasta_h"] == UMBRAL_ON_TIME_H
    assert zonas["warm"]["desde_h"] == UMBRAL_ON_TIME_H
    assert zonas["warm"]["hasta_h"] == UMBRAL_WARM_H
    assert zonas["cold"]["desde_h"] == UMBRAL_WARM_H
    assert sum(z["ancho_pct"] for z in r["zonas"]) == pytest.approx(100.0, abs=0.01)

    # la posición del marcador es la hora real de la señal sobre ese eje
    horas = o["senal"]["horas_desde_senal"]
    assert r["horas"] == horas
    assert r["pos_pct"] == pytest.approx(100.0 * horas / r["dominio_h"], abs=0.01)
    # y el estado que enseña es el que usó la política, no otro
    assert r["momento"] == o["senal"]["momento"]
    zona_del_marcador = next(z for z in r["zonas"]
                             if z["desde_h"] <= horas <= z["hasta_h"])
    assert zona_del_marcador["clave"] == r["momento"]


def test_la_curva_de_fatiga_es_el_conteo_de_nudges_antes_del_corte(api):
    """Se recuenta a mano: enganche por exposición con `shown_ts < asof`."""
    import pandas as pd

    o, g = _graficas(api)
    nu = comun.store().nu.reset_index()
    nu = nu[nu.shown_ts < pd.Timestamp(o["corte_features"] + "T12:00:00")]
    esperado = nu.groupby("exposure_no", observed=True).agg(
        n=("engaged", "size"), eng=("engaged", "mean"), baja=("opted_out_after", "mean"))

    curva = g["cupo"]["curva"]
    assert curva, "sin curva no hay evidencia del cupo"
    for p in curva:
        fila = esperado.loc[p["exposure_no"]]
        assert p["n"] == int(fila.n)
        assert p["enganche"] == pytest.approx(float(fila.eng), abs=1e-6)
        assert p["baja"] == pytest.approx(float(fila.baja), abs=1e-6)
        assert p["n"] >= g["cupo"]["min_avisos_por_exposicion"], (
            "una exposición con pocos avisos sería ruido dibujado como dato")
        assert PORCENTAJE.match(p["enganche_texto"])

    # la curva baja: es el argumento entero del cap de 2
    enganches = [p["enganche"] for p in curva]
    assert enganches == sorted(enganches, reverse=True)
    assert [p["baja"] for p in curva] == sorted(p["baja"] for p in curva)


def test_el_cupo_del_grafico_es_el_de_la_ficha(api):
    d = api.post("/api/decidir", json={"customer_id": CLIENTE_AHORRO, "asof": ASOF}).json()
    oferta = d["ofertas"][0]
    cupo = oferta["explicacion"]["graficas"]["cupo"]
    senal = d["senales"][oferta["producto"]]
    assert cupo["cap"] == 2 == senal["cupo"]
    assert cupo["exposiciones"] == senal["exposiciones"]
    assert cupo["restante"] == senal["cupo_restante"]
    assert len(cupo["casillas"]) == cupo["cap"]
    assert sum(1 for c in cupo["casillas"] if c["usada"]) == cupo["exposiciones"]
    assert cupo["siguiente"] == oferta["senal"]["exposure_no_siguiente"]


def test_toda_grafica_trae_alternativa_textual_para_lector_de_pantalla(api):
    """Una barra sin número al lado no es accesible."""
    o, g = _graficas(api)
    for clave in ("poblacion", "distribucion", "recencia", "cupo"):
        assert g[clave]["alternativa"], f"{clave} no trae alternativa textual"
        assert len(g[clave]["alternativa"]) > 30
    for b in g["contra_base"]["barras"]:
        assert b["alternativa"]


def test_sin_vista_poblacional_no_hay_graficas_inventadas(api):
    """Sin panorama del corte no se dibuja un eje falso: se dice por qué.

    Se prueba el camino de verdad —`_explicar_oferta` con `vista=None`— porque
    los 5 cortes del demo sí tienen panorama y un `skip` no probaría nada.
    """
    from app.main import _explicar_oferta, app

    d = api.post("/api/decidir", json={"customer_id": CLIENTE_AHORRO, "asof": ASOF}).json()
    oferta = {k: v for k, v in d["ofertas"][0].items() if k != "explicacion"}
    ficha = app.state.store.ficha(CLIENTE_AHORRO, ASOF)

    ex = _explicar_oferta(app.state, oferta, ficha, None, 38000)
    assert ex["graficas"] is None
    assert ex["corte_comparacion"] is None
    assert "inventar" in ex["motivo_sin_comparacion"]
    # y los tres factores siguen ahí, sin percentil en vez de con uno falso
    assert [f["clave"] for f in ex["factores"]] == ["p_intencion", "p_enganche", "valor"]
    assert ex["factores"][0]["referencia"]["percentil"] is None
    assert ex["resultado"]["referencia"]["percentil"] is None


# ==========================================================================
# 10 · La vista inicial es el banner, no el expediente
# ==========================================================================
def test_el_banner_solo_trae_titulo_frase_y_el_boton_del_porque(api):
    html = api.get("/").text
    # el banner: título y frase
    assert '<h3 x-text="o.titulo"></h3>' in html
    assert 'class="frase" x-text="o.razon"' in html
    # y un único botón, que abre el porqué
    assert "'Ocultar por qué' : 'Mostrar por qué'" in html
    assert 'alternarPorque(o.producto)' in html
    assert ':aria-controls="\'porque-\' + o.producto"' in html, (
        "el botón tiene que anunciar qué panel controla")


def test_el_detalle_esta_detras_del_boton(api):
    html = api.get("/").text
    # el panel del porqué está cerrado hasta que se pulsa
    assert 'x-show="porque === o.producto"' in html
    # y lo que era invasivo vive dentro: los tres factores y las gráficas
    inicio = html.index('class="porque"')
    fin = html.index('<!-- silencio: pantalla diseñada')
    panel = html[inicio:fin]
    for dentro in ('class="desglose"', 'class="factores"', 'class="apilada"',
                   'class="hist"', 'class="cb-fila"', 'class="rec"', 'class="fat"'):
        assert dentro in panel, f"{dentro} tendría que estar dentro del panel del porqué"
    # la traza y el expediente también, salvo en la pantalla de silencio
    assert html.count('x-show="verDetalle') >= 3
    assert 'get verDetalle(){ return !this.hayOferta || this.porque !== null; }' in html


def test_el_porque_es_alcanzable_con_el_teclado(api):
    html = api.get("/").text
    # es un <button>, no un div con @click: entra en el orden de tabulación
    assert 'type="button" class="boton" @click="alternarPorque' in html
    assert ':aria-expanded="porque === o.producto"' in html
    assert ":focus-visible{outline:3px solid" in html.replace("\n", "")
