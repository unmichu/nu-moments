"""PRD-4.c · La pestaña «Cómo funciona» tiene que ser verdad, no folleto.

Una pestaña explicativa es el sitio más fácil del producto para mentir: nadie
recuenta una prosa. Cuatro riesgos, y ninguno revienta solo:

1. **Las pestañas no cambian de verdad**, o cambian con el ratón pero no con el
   teclado, o la activa solo se distingue por color.
2. **Las ocho puertas se cuentan mal o se cuentan a medias**: falta alguna, o
   las dos que no están activas se esconden para que el cuadro quede limpio.
3. **Los números se quedan desfasados.** El día que alguien escriba un `86.43 %`
   en la plantilla, la pestaña seguirá diciéndolo cuando cambie el corte. Aquí
   se confrontan con `/api/contexto`, corte por corte.
4. **La página se desplaza de lado.** Ya pasó dos veces; el CSS nuevo se somete
   a las mismas reglas que el viejo.
"""
from __future__ import annotations

import re

import pytest

from pipeline import politica
from pipeline.mapas import CATALOGO_DEMO, TODOS_LOS_PRODUCTOS

# `86.43 %`, `0.00 %`: dos decimales, ni uno más ni uno menos.
PORCENTAJE = re.compile(r"^-?\d+\.\d{2} %$")

# El móvil más estrecho que se soporta, igual que en `test_interfaz.py`.
ANCHO_MINIMO_SOPORTADO = 320


@pytest.fixture(scope="module")
def api():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def html(api):
    return api.get("/").text


@pytest.fixture(scope="module")
def ex(api):
    return api.get("/api/explicacion").json()


@pytest.fixture(scope="module")
def ctx(api):
    return api.get("/api/contexto").json()


def _reglas_css(html):
    """Los bloques `selector{declaraciones}` del `<style>` de la plantilla."""
    estilo = re.search(r"<style>(.*?)</style>", html, re.S)
    assert estilo, "la plantilla debe traer su CSS en línea (sin red)"
    css = re.sub(r"/\*.*?\*/", "", estilo.group(1), flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def _declaraciones(cuerpo):
    return [d.strip() for d in cuerpo.split(";") if d.strip()]


def _regla(html, selector):
    return next((c for s, c in _reglas_css(html) if s.strip() == selector), None)


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


# ==========================================================================
# 1 · Las tres pestañas existen, cambian y se manejan con el teclado
# ==========================================================================
def test_estan_las_tres_pestanas(html):
    """Decisión, Cómo funciona y Panorama. Ni una menos."""
    assert 'id="tab-decision"' in html and ">Decisión<" in html
    assert 'id="tab-como"' in html and ">Cómo funciona<" in html
    assert 'href="/dashboard"' in html and "Panorama" in html


def test_las_dos_pestanas_de_verdad_son_tabs_y_el_panorama_es_un_enlace(html):
    """`/dashboard` es otra página: un `role="tab"` que navega mentiría.

    El enlace tiene que quedar **fuera** del `tablist`, no solo parecerse a una
    pestaña por fuera.
    """
    botones = re.findall(r'<button[^>]*role="tab"', html)
    assert len(botones) == 2, "solo hay dos paneles conmutables"
    assert 'role="tablist"' in html

    lista = re.search(r'role="tablist"(.*?)</div>', html, re.S)
    assert lista, "el tablist tiene que ser un contenedor propio"
    assert 'href="/dashboard"' not in lista.group(1), (
        "el enlace al panorama no puede vivir dentro del tablist: navega fuera")


def test_cada_pestana_gobierna_su_panel(html):
    """Panel por pestaña, atado en los dos sentidos, y solo uno visible."""
    for tab, panel in (("tab-decision", "panel-decision"), ("tab-como", "panel-como")):
        assert f'aria-controls="{panel}"' in html
        assert f'id="{panel}"' in html
        assert f'aria-labelledby="{tab}"' in html
    assert html.count('role="tabpanel"') == 2
    for nombre in ("decision", "como"):
        assert f"x-show=\"pestana === '{nombre}'\"" in html, (
            f"el panel {nombre} no se muestra ni se oculta: no cambiaría nada")


def test_la_pestana_activa_se_nota_sin_depender_del_color(html):
    """`aria-selected` para quien no ve, y raya + peso para quien sí."""
    assert html.count(":aria-selected=\"pestana === '") == 2
    regla = _regla(html, '.pestana[aria-selected="true"]')
    assert regla, "la pestaña activa necesita su propia regla"
    plano = regla.replace(" ", "")
    assert "border-bottom-color" in plano, "sin raya inferior solo queda el color"
    assert "font-weight" in plano, "sin cambio de peso, la marca es solo cromática"


def test_las_pestanas_se_manejan_con_el_teclado(html):
    """Botones de verdad, flechas, Inicio y Fin, y foco itinerante."""
    tabs = re.findall(r'<button[^>]*role="tab".*?</button>', html, re.S)
    assert len(tabs) == 2
    for t in tabs:
        assert "keydown.arrow-right" in t and "keydown.arrow-left" in t, (
            "un tablist se recorre con las flechas")
        assert "keydown.home" in t and "keydown.end" in t
        assert ":tabindex=" in t, (
            "el foco tiene que entrar solo en la pestaña activa (tabindex itinerante)")
    # y el patrón mueve el foco además de cambiar de panel
    assert "irA('como', true)" in html and "irA('decision', true)" in html


def test_la_pestana_nueva_no_esconde_a_la_de_decision(html):
    """`x-cloak` solo en la pestaña nueva: la de decisión se ve sin esperar a Alpine."""
    panel = re.search(r'id="panel-decision"[^>]*>', html).group(0)
    assert "x-cloak" not in panel, (
        "con x-cloak, la pantalla de decisión parpadearía en blanco al cargar")
    assert "x-cloak" in re.search(r'id="panel-como"[^>]*>', html).group(0)


# ==========================================================================
# 2 · Las ocho puertas están descritas, incluidas las dos apagadas
# ==========================================================================
def test_estan_las_ocho_puertas_en_su_orden_de_ejecucion(ex):
    ocho = [p for p in ex["puertas"] if p["orden"]]
    assert [p["puerta"] for p in ocho] == politica.ORDEN_EVALUACION
    assert [p["orden"] for p in ocho] == list(range(1, 9))


def test_cada_puerta_dice_que_comprueba_a_quien_deja_fuera_y_por_que_es_bueno(ex):
    """Las tres cosas que pidió el encargo. Una frase vacía es una puerta sin explicar."""
    for p in ex["puertas"]:
        for campo in ("nombre", "comprueba", "deja_fuera", "bueno_porque"):
            assert p.get(campo), f"{p['puerta']} no dice `{campo}`"
            assert len(p[campo]) > 20, f"{p['puerta']}.{campo} no explica nada: {p[campo]!r}"


def test_las_dos_puertas_no_activas_se_declaran_y_no_se_esconden(ex):
    """S5 y S7 existen, se ejecutan y no cierran. Ocultarlas sería más limpio y peor."""
    apagadas = [p for p in ex["puertas"] if p["orden"] and not p["activa"]]
    assert {p["puerta"] for p in apagadas} == {
        c for c in politica.ORDEN_EVALUACION if not politica.PUERTAS_ACTIVAS[c]}
    assert len(apagadas) == 2
    for p in apagadas:
        assert p["n"] == 0, "una puerta no activa no puede cerrar a nadie"
        assert "no activa" in p["estado"]
        assert p["motivo_cero"] and "fallo" in p["motivo_cero"], (
            "hay que decir explícitamente que cerrar a 0 no es un fallo")
    assert set(ex["puertas_no_activas"]) == {p["puerta"] for p in apagadas}
    assert ex["nota_no_activas"] and "no es un fallo" in ex["nota_no_activas"].lower()


def test_el_fuera_de_catalogo_va_aparte_y_no_finge_ser_una_de_las_ocho(ex):
    """C0 cierra productos, no personas: contarlo como puerta inflaría el silencio."""
    c0 = next(p for p in ex["puertas"] if p["puerta"] == politica.C0)
    assert c0["orden"] is None and c0["n"] is None
    assert [x["producto"] for x in ex["catalogo"]] == list(CATALOGO_DEMO)
    assert ([x["producto"] for x in ex["fuera_de_catalogo"]]
            == [p for p in TODOS_LOS_PRODUCTOS if p not in CATALOGO_DEMO])


def test_los_conteos_de_las_ocho_puertas_suman_el_silencio_del_corte(ex):
    """Si sumaran de más, alguien se estaría contando dos veces."""
    n_silencio = ex["conteo_por_oferta"]["silencio"]
    assert sum(p["n"] for p in ex["puertas"] if p["orden"]) == n_silencio
    assert n_silencio + sum(
        n for clave, n in ex["conteo_por_oferta"].items() if clave != "silencio"
    ) == ex["n_clientes"]
    # y el matiz que lo hace cierto está escrito en la pantalla, no supuesto
    assert "varias puertas" in ex["nota_conteo_puertas"]


def test_la_pestana_describe_las_ocho_puertas_en_la_pantalla(html):
    """No basta con que la API las traiga: la plantilla tiene que pintarlas."""
    bloque = re.search(r'id="panel-como".*?</div>\s*</div>\s*<footer', html, re.S)
    assert bloque, "no se encuentra el panel de la pestaña nueva"
    texto = bloque.group(0)
    assert 'x-for="p in ex.puertas"' in texto, "las puertas se recorren, no se copian"
    for campo in ("p.comprueba", "p.deja_fuera", "p.bueno_porque", "p.estado",
                  "p.n_texto", "p.motivo_cero"):
        assert campo in texto, f"la pantalla no enseña {campo}"


# ==========================================================================
# 3 · Los números de la pestaña son los de `/api/contexto`
# ==========================================================================
def test_los_conteos_por_puerta_son_los_mismos_que_los_del_contexto(api, ctx):
    """Corte por corte. Dos fuentes para el mismo número son dos números."""
    for corte in ctx["cortes"]:
        if corte["conteo_por_razon"] is None:                    # pragma: no cover
            continue
        e = api.get(f"/api/explicacion?corte={corte['corte']}").json()
        publicado = {p["puerta"]: p["n"] for p in e["puertas"] if p["orden"] and p["n"]}
        assert publicado == corte["conteo_por_razon"], corte["corte"]
        assert e["conteo_por_oferta"] == corte["conteo_por_oferta"]
        assert e["cobertura"]["pct_silencio"] == corte["cobertura"]["pct_silencio"]
        assert e["n_clientes"] == ctx["n_clientes"]


def test_los_cuatro_resultados_cuadran_con_la_cobertura(ex, ctx):
    """Ofrecer + sustituir + callar son los 38 000, sin dobles ni huecos."""
    por_clave = {r["clave"]: r for r in ex["resultados"]}
    assert set(por_clave) == {"oferta", "sustitucion", "silencio", "callar"} - {"callar"} | {
        "fuera_de_catalogo"}
    suma = sum(por_clave[c]["n"] for c in ("oferta", "sustitucion", "silencio"))
    assert suma == ex["n_clientes"]
    assert por_clave["fuera_de_catalogo"]["n"] is None, (
        "el fuera de catálogo no es un conteo de personas y no puede fingir serlo")

    cob = next(c for c in ctx["cortes"] if c["corte"] == ex["corte"])["cobertura"]
    assert por_clave["silencio"]["pct"] == cob["pct_silencio"]
    assert (por_clave["oferta"]["pct"] + por_clave["sustitucion"]["pct"]
            == pytest.approx(cob["pct_oferta"], abs=0.01))


def test_la_sustitucion_se_cuenta_dentro_de_las_ofertas_y_se_dice(ex):
    por_clave = {r["clave"]: r for r in ex["resultados"]}
    assert por_clave["sustitucion"]["n"] == ex["n_sustituciones"] >= 0
    assert "dentro de las ofertas" in por_clave["sustitucion"]["nota"]


def test_callar_se_explica_como_resultado_y_no_como_fallo(ex):
    silencio = next(r for r in ex["resultados"] if r["clave"] == "silencio")
    assert "no es un fallo" in silencio["por_que"] or "no un fallo" in silencio["por_que"]
    assert ex["por_que_callar"] and len(ex["por_que_callar"]) > 60


def test_todos_los_porcentajes_de_la_pestana_llevan_dos_decimales(ex):
    """El contrato de formato vale también aquí: `XX.XX %`."""
    def recorrer(nodo, ruta=""):
        if isinstance(nodo, dict):
            for k, v in nodo.items():
                if isinstance(v, str) and v.endswith(" %"):
                    assert PORCENTAJE.match(v), f"{ruta}.{k} = {v!r}"
                else:
                    recorrer(v, f"{ruta}.{k}")
        elif isinstance(nodo, list):
            for i, v in enumerate(nodo):
                recorrer(v, f"{ruta}[{i}]")
    recorrer(ex)


def test_ni_una_cifra_de_la_pestana_esta_escrita_en_la_plantilla(html, ex):
    """El día que se escriba a mano, dejará de moverse al cambiar el corte."""
    bloque = re.search(r'id="panel-como".*?</div>\s*</div>\s*<footer', html, re.S).group(0)
    prohibidas = [ex["n_clientes_texto"], ex["corte"]]
    prohibidas += [p["n_texto"] for p in ex["puertas"] if p["n"]]
    prohibidas += [r["n_texto"] for r in ex["resultados"] if r["n"]]
    for cifra in prohibidas:
        assert cifra not in bloque, (
            f"«{cifra}» está escrita en la plantilla: se quedará desfasada")


# ==========================================================================
# 4 · Los modelos: cuál aprende y cuál no
# ==========================================================================
def test_los_tres_van_en_orden_y_el_tercero_no_se_vende_como_modelo(ex):
    assert [m["orden"] for m in ex["modelos"]] == [1, 2, 3]
    assert [m["clave"] for m in ex["modelos"]] == ["intencion", "momento", "valor"]
    ml = {m["clave"]: m["es_ml"] for m in ex["modelos"]}
    assert ml == {"intencion": True, "momento": True, "valor": False}
    valor = next(m for m in ex["modelos"] if m["clave"] == "valor")
    assert "No es aprendizaje automático" == valor["es_ml_texto"]
    assert "engañoso" in valor["como_aprende"], (
        "hay que decir por qué llamarla modelo sería engañoso, no solo que no lo es")
    assert ex["respaldo"]["es_ml"] is False
    assert "engañoso" in ex["aviso_sobre_el_tercero"]


def test_cada_modelo_dice_que_pregunta_responde_que_mira_y_que_devuelve(ex):
    for m in ex["modelos"] + [ex["respaldo"]]:
        for campo in ("nombre", "responde", "mira", "devuelve", "por_que_aqui"):
            assert m.get(campo) and len(m[campo]) > 20, f"{m['clave']}.{campo}"


def test_los_valores_de_los_productos_salen_del_artefacto(api, ex):
    """La tabla de valor de la pestaña es la que ejecuta la política, no una copia."""
    from app.main import app

    tabla = app.state.escalera.tabla_valor
    for p in ex["catalogo"]:
        assert p["V"] == pytest.approx(float(tabla[p["producto"]]["V"]))
    assert ex["lambda"] == app.state.escalera.lmbda
    assert ex["nivel_activo"] == app.state.escalera.nivel_activo


# ==========================================================================
# 5 · El glosario se reutiliza, no se duplica
# ==========================================================================
def test_el_glosario_de_la_decision_viaja_entero_y_sin_reescribir(ex, ctx):
    """Dos redacciones del mismo término son dos productos distintos."""
    for clave, entrada in ctx["glosario"].items():
        assert clave in ex["glosario"], f"falta {clave} en la pestaña"
        assert ex["glosario"][clave]["texto"] == entrada["texto"], (
            f"«{clave}» está reescrito en la pestaña en vez de reutilizado")
        assert ex["glosario"][clave]["origen"] == "pantalla de decisión"


def test_el_glosario_se_amplia_con_lo_que_alli_se_daba_por_sabido(ex, ctx):
    nuevos = set(ex["glosario"]) - set(ctx["glosario"])
    assert {"modelo_entrenado", "no_es_modelo", "puerta", "probabilidad"} <= nuevos
    for clave in nuevos:
        assert ex["glosario"][clave]["origen"] == "cómo funciona"
        assert len(ex["glosario"][clave]["texto"]) > 40


# ==========================================================================
# 6 · Los nueve ejemplos son los nueve clientes de verdad
# ==========================================================================
def test_los_nueve_ejemplos_dan_hoy_lo_que_promete_el_guion(ex, api):
    assert len(ex["ejemplos"]) == 9
    for caso in ex["ejemplos"]:
        assert caso["coincide_con_el_guion"], caso["clave"]
        assert caso["salida"] in ("oferta", "sustitucion", "silencio")
        assert caso["narrativa"]
        if caso["salida"] == "silencio":
            assert caso["puerta"] in politica.ORDEN_EVALUACION
        else:
            assert caso["producto"] in CATALOGO_DEMO
    assert {c["salida"] for c in ex["ejemplos"]} == {"oferta", "sustitucion", "silencio"}


def test_el_ejemplo_de_sustitucion_dice_que_producto_reemplaza(ex):
    sust = [c for c in ex["ejemplos"] if c["salida"] == "sustitucion"]
    assert sust, "sin un caso de sustitución la cuarta salida no se puede enseñar"
    for c in sust:
        assert c["sustituye_a"] and c["sustituye_a"] != c["producto"]
        assert c["sustituye_a_titulo"] and c["producto_titulo"]


# ==========================================================================
# 7 · La pestaña no desplaza la página de lado
# ==========================================================================
def test_el_css_nuevo_no_trae_anchos_fijos_por_encima_del_movil_mas_estrecho(html):
    """Mismo criterio que el resto de la plantilla, aplicado a lo nuevo."""
    culpables = []
    for selector, cuerpo in _reglas_css(html):
        limpio = selector.strip()
        if not (limpio.startswith(".ex-") or limpio.startswith(".pestana")
                or limpio.startswith(".explica")):
            continue
        for d in _declaraciones(cuerpo):
            m = re.match(r"(min-width|width)\s*:\s*(\d+(?:\.\d+)?)px$", d)
            if m and float(m.group(2)) > ANCHO_MINIMO_SOPORTADO:
                culpables.append(f"{limpio} {{ {d} }}")
    assert not culpables, "\n  ".join(culpables)


def test_ninguna_rejilla_nueva_usa_1fr_sin_minmax(html):
    """`1fr` es `minmax(auto,1fr)`: su mínimo es el contenido, y ese fue el bug."""
    culpables = []
    for selector, cuerpo in _reglas_css(html):
        limpio = selector.strip()
        if not (limpio.startswith(".ex-") or limpio.startswith(".pestana")
                or limpio.startswith(".explica")):
            continue
        for d in _declaraciones(cuerpo):
            if not d.startswith("grid-template-columns"):
                continue
            # `minmax(min(100%,Npx),1fr)`: el `min(100%,…)` acota el suelo de la
            # pista al ancho del contenedor, así que cede cuando no cabe. Es más
            # segura que el `minmax(Npx,1fr)` de la línea siguiente, cuyo suelo
            # es duro y a 320 px se sale del contenedor.
            valor = re.sub(
                r"minmax\(\s*min\(\s*100%\s*,\s*\d+(?:\.\d+)?px\s*\)\s*,\s*1fr\s*\)",
                "OK", d.split(":", 1)[1])
            valor = re.sub(r"minmax\(\s*\d+px\s*,\s*1fr\s*\)", "OK", valor)
            valor = re.sub(r"minmax\(\s*0\s*,\s*1fr\s*\)", "OK", valor)
            if "1fr" in valor:
                culpables.append(f"{limpio} {{ {d} }}")
    assert not culpables, "\n  ".join(culpables)


def test_las_pestanas_y_las_tarjetas_nuevas_se_reparten_en_varias_lineas(html):
    """Nada de lo nuevo puede quedarse en una sola fila que no quepa a 320 px."""
    for selector in (".pestanas", ".pestanas-in", ".ex-mapa"):
        regla = _regla(html, selector)
        assert regla and "flex-wrap:wrap" in regla.replace(" ", ""), selector
    for selector in (".ex-rejilla",):
        regla = _regla(html, selector)
        assert regla and "auto-fit" in regla.replace(" ", ""), (
            f"{selector} tiene que repartirse solo, no con un número fijo de columnas")


def test_nada_nuevo_es_nowrap(html):
    """Un `nowrap` olvidado convierte una frase larga en el ancho mínimo de la página."""
    for selector, cuerpo in _reglas_css(html):
        limpio = selector.strip()
        if limpio.startswith(".ex-") or limpio.startswith(".explica"):
            assert "nowrap" not in cuerpo, f"{limpio} no puede ser nowrap"
    # la pestaña sí lleva texto corto, pero tampoco: en móvil parte en dos líneas
    assert "white-space:normal" in (_regla(html, ".pestana") or "").replace(" ", "")


def test_la_burbuja_de_ayuda_sigue_anclada_despues_de_anadir_la_pestana(html):
    """El anclaje del `@media` no se puede haber roto al insertar CSS nuevo.

    Es el fallo que ya se coló dos veces: una burbuja abierta que se sale del
    viewport arrastra el `scrollWidth` de la página entera.
    """
    anclajes = []
    for condicion, cuerpo in _bloques_media(html):
        for selector, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", cuerpo):
            if ".ay-p" in selector and "position:fixed" in decl.replace(" ", ""):
                anclajes.append((_max_width(condicion), decl.replace(" ", "")))
    assert anclajes, "no hay ningún @media que ancle `.ay-p` al viewport"
    tope, decl = anclajes[0]
    assert tope and tope >= 1020, (
        f"el anclaje llega solo a {tope} px y la banda ancha vuelve a desbordar")
    for trozo in ("left:10px", "right:10px", "width:auto", "max-width:none"):
        assert trozo in decl, f"al anclaje le falta {trozo}"
