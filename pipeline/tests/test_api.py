"""ING-4 · Los cuatro endpoints y el contrato de `app/fixture.json`.

Tres cosas se comprueban aquí y no en otro sitio:

1. Los cuatro endpoints responden y el POST trae **exactamente** la forma que
   el fixture publicó antes de que existiera el backend (ING-2).
2. Una excepción interna devuelve **HTTP 200 con silencio**, nunca un 500.
3. El contador del silencio sale del artefacto calculado al arranque y **no**
   está escrito a mano en el HTML (ING-6).
"""
from __future__ import annotations

import re

import pytest

import comun
from comun import ASOF, CLIENTE_AHORRO, CLIENTE_ESTRELLA


@pytest.fixture(scope="module")
def api():
    """La app real con su `lifespan`: los artefactos se cargan una sola vez."""
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


# ==========================================================================
# 1 · GET /api/clientes
# ==========================================================================
def test_listar_clientes_pone_los_curados_al_frente(api):
    r = api.get("/api/clientes")
    assert r.status_code == 200
    d = r.json()
    assert d["n_curados"] == 9, "son 9 escenarios verificados"
    curados = [c for c in d["clientes"] if c["curado"]]
    # el selector NO es aleatorio: los curados van primero, en bloque
    assert d["clientes"][:9] == curados
    for c in curados:
        assert {"customer_id", "clave", "titulo", "asof", "esperado"} <= set(c)
    assert CLIENTE_ESTRELLA in [c["customer_id"] for c in curados]


def test_busqueda_libre_como_secundaria(api):
    r = api.get(f"/api/clientes?q={CLIENTE_AHORRO}")
    assert r.status_code == 200
    d = r.json()
    assert CLIENTE_AHORRO in [c["customer_id"] for c in d["clientes"]]


# ==========================================================================
# 2 · GET /api/clientes/{id}?asof=
# ==========================================================================
def test_ficha_trae_perfil_movimientos_navegacion_e_historial(api):
    r = api.get(f"/api/clientes/{CLIENTE_ESTRELLA}?asof={ASOF}")
    assert r.status_code == 200
    f = r.json()
    assert {"perfil", "movimientos", "navegacion", "nudges", "decision"} <= set(f)
    assert f["perfil"]["customer_id"] == CLIENTE_ESTRELLA
    assert f["asof"] == ASOF
    assert f["caso_curado"]["clave"] == "fragil_silencio"


def test_ficha_de_un_cliente_inexistente_es_404_no_500(api):
    r = api.get("/api/clientes/1?asof=" + ASOF)
    assert r.status_code == 404
    assert "no existe" in r.json()["error"]


def test_la_ficha_respeta_el_corte_estricto(api):
    """Nada de lo que se muestra puede ser posterior al `asof`."""
    r = api.get(f"/api/clientes/{CLIENTE_AHORRO}?asof={ASOF}")
    f = r.json()
    for e in f["linea_tiempo"]:
        assert e["ts"] < ASOF.replace("T", " "), e


# ==========================================================================
# 3 · POST /api/decidir · el contrato de app/fixture.json
# ==========================================================================
def test_el_post_cumple_el_esquema_del_fixture(api):
    contrato = comun.contrato()
    r = api.post("/api/decidir", json={"customer_id": CLIENTE_ESTRELLA, "asof": ASOF})
    assert r.status_code == 200
    d = r.json()

    for clave in contrato:
        assert clave in d, f"el POST no trae {clave!r}, que el fixture publicó"
        assert type(d[clave]) is type(contrato[clave]) or d[clave] is None, clave

    assert d["decision"] in ("oferta", "sustitucion", "silencio")
    assert len(d["traza"]) == 8
    for fila in d["traza"]:
        assert {"puerta", "resultado"} <= set(fila)
        assert fila["resultado"] in ("pasa", "cierra", "no_activa")
    for s in d["silencios"]:
        assert {"producto", "puerta", "razon"} <= set(s)
        assert s["razon"] and s["razon"] != "Sin razón registrada."
    assert {"pct_silencio", "pct_oferta"} <= set(d["cobertura"])


def test_una_oferta_trae_titulo_score_superficie_y_razon(api, casos=None):
    r = api.post("/api/decidir", json={"customer_id": comun.CLIENTE_SUSTITUCION,
                                       "asof": "2026-06-16T00:00:00"})
    d = r.json()
    assert d["ofertas"], "el caso de sustitución debe ofrecer algo"
    o = d["ofertas"][0]
    assert {"producto", "score", "surface", "titulo", "razon", "etiqueta_boton"} <= set(o)
    # la explicación viaja DENTRO del POST: no puede divergir de la decisión
    assert isinstance(o["razon"], str) and len(o["razon"]) > 20


def test_el_asof_es_opcional_y_vuelve_resuelto(api):
    r = api.post("/api/decidir", json={"customer_id": CLIENTE_ESTRELLA})
    assert r.status_code == 200
    assert r.json()["asof"] == ASOF


def test_el_caso_estrella_reporta_la_puerta_de_fragilidad(api):
    """Frágil, con señal fresca de aumento de línea y cupo libre."""
    r = api.post("/api/decidir", json={"customer_id": CLIENTE_ESTRELLA, "asof": ASOF})
    d = r.json()
    assert d["decision"] == "silencio"
    assert d["puerta_reportada"] == "S3_fragilidad", (
        "un frágil con cupo libre debe reportar el veto por daño, no un silencio genérico")
    assert d["encabezado"]["titulo"] and d["encabezado"]["texto"]
    # la pantalla de silencio es una pantalla diseñada: razón en lenguaje natural
    assert "línea" in d["encabezado"]["texto"] or "crédito" in d["encabezado"]["texto"]


# ==========================================================================
# 4 · Una excepción interna devuelve HTTP 200 con silencio
# ==========================================================================
def test_una_excepcion_interna_devuelve_200_con_silencio(api, monkeypatch):
    from pipeline import politica

    def revienta(*a, **k):
        raise RuntimeError("fallo inyectado a propósito")

    monkeypatch.setattr(politica, "decide", revienta)
    r = api.post("/api/decidir", json={"customer_id": CLIENTE_ESTRELLA, "asof": ASOF})
    assert r.status_code == 200, "nunca un 500: el modo degradado es una decisión"
    d = r.json()
    assert d["decision"] == "silencio"
    assert d["modelo"] == "degradado"
    assert d["razon_silencio"]
    assert d["ofertas"] == []
    assert "fallo inyectado" in d["detalle_tecnico"], "el motivo se registra, no se oculta"


def test_el_servicio_se_recupera_despues_del_fallo(api):
    """El monkeypatch anterior se deshizo: la siguiente petición vuelve a decidir."""
    r = api.post("/api/decidir", json={"customer_id": CLIENTE_ESTRELLA, "asof": ASOF})
    assert r.json()["modelo"] != "degradado"


def test_un_cuerpo_invalido_no_es_un_500(api):
    r = api.post("/api/decidir", json={"customer_id": "no-soy-un-entero"})
    assert r.status_code == 422, "validación de entrada, no error de servidor"


# ==========================================================================
# 5 · GET /health
# ==========================================================================
def test_health_dice_si_corre_en_modelo_o_en_fallback(api):
    h = api.get("/health").json()
    assert h["estado"] == "ok"
    assert h["en_modelo"] is (h["modelo"] == "v1")
    assert h["en_fallback"] is not h["en_modelo"]
    assert h["corte_demo"] == "2026-06-16"
    # nada de valores por defecto silenciosos: si un nivel no está, dice por qué
    if not h["en_modelo"]:
        assert h["escalera"]["niveles_caidos"], "cae al fallback sin decir por qué"


def test_health_publica_el_inventario_de_artefactos(api):
    h = api.get("/health").json()
    inv = h["artefactos"]
    for nombre in ("modelo_intencion.pkl", "modelo_momento.pkl", "umbrales.json",
                   "tabla_valor.json", "razones.json", "metadata.json", "demo_pack.json",
                   "features_asof_2026-06-16.parquet"):
        assert nombre in inv, f"{nombre} no aparece en /health"
        assert "presente" in inv[nombre]


def test_health_trae_el_contador_de_cobertura_del_arranque(api):
    h = api.get("/health").json()
    cob = h["cobertura"]
    assert cob["n_clientes"] == 38000
    assert 0 < cob["pct_silencio"] < 100
    assert round(cob["pct_silencio"] + cob["pct_oferta"], 2) == 100.0
    assert cob["pct_silencio"] > 80, "el silencio es el estado más frecuente"


# ==========================================================================
# 6 · La pantalla
# ==========================================================================
def test_el_html_no_trae_el_contador_escrito_a_mano(api):
    """ING-6 · el contador se lee del artefacto, nunca del HTML."""
    cob = api.get("/health").json()["cobertura"]
    html = api.get("/").text
    assert api.get("/").status_code == 200
    assert str(cob["pct_silencio"]) not in html, (
        "el porcentaje de silencio está escrito a mano en la plantilla")
    assert "cobertura?.pct_silencio" in html, "el contador debe leerse de la respuesta"


def test_la_pantalla_no_depende_de_la_red(api):
    """Sin CDN: el demo nunca depende de la red.

    Lo que se prohíbe es una **petición**, no la cadena `http://`. La versión
    anterior buscaba el literal y por eso marcaba
    `xmlns="http://www.w3.org/2000/svg"`, que es el identificador del espacio de
    nombres de SVG: un nombre, no una URL que el navegador visite. Ese falso
    positivo dejaba la pantalla sin poder dibujar un SVG en línea.

    Ahora se comprueba lo que de verdad saldría a la red: `src`/`href` externos,
    `@import`, `url()` apuntando fuera, un `fetch` absoluto, un `<link>` a otro
    dominio y las URL sin esquema (`//cdn…`). Los espacios de nombres de XML
    —`xmlns`, `xmlns:xlink`, `xlink:href` a un `#id` local— quedan permitidos
    explícitamente porque nunca provocan una descarga.
    """
    html = api.get("/").text

    # Espacios de nombres: se quitan del texto ANTES de buscar peticiones, para
    # que la comprobación siguiente sea sobre lo que puede viajar por la red.
    sin_ns = re.sub(r'xmlns(:\w+)?="[^"]*"', "", html)

    prohibidos = [
        (r'\b(?:src|srcset|href|action|data|poster|formaction)\s*=\s*["\']?(?:https?:)?//',
         "un recurso apuntando a otro origen"),
        (r'@import\b', "un @import de CSS"),
        (r'url\(\s*["\']?(?:https?:)?//', "un url() externo en CSS"),
        (r'(?:fetch|XMLHttpRequest|WebSocket|EventSource|importScripts|import)\s*\(\s*'
         r'["\`\']?(?:https?:)?//', "una petición absoluta desde JavaScript"),
        (r'<link\b[^>]*\bhref\s*=\s*["\']?(?:https?:)?//', "un <link> externo"),
        (r'integrity\s*=', "un subrecurso de CDN (integrity solo se usa con CDN)"),
    ]
    for patron, motivo in prohibidos:
        encontrado = re.search(patron, sin_ns, re.I)
        assert not encontrado, (
            f"la pantalla dependería de la red: {motivo} "
            f"→ {sin_ns[max(0, encontrado.start() - 40):encontrado.end() + 40]!r}")

    # Y lo único que sí se carga, vendorizado y servido por este mismo proceso.
    assert "/static/alpine.min.js" in html
    assert api.get("/static/alpine.min.js").status_code == 200


def test_el_svg_en_linea_solo_declara_espacios_de_nombres(api):
    """La contracara del test anterior: que `http` solo aparezca en un `xmlns`.

    Si mañana alguien mete un `https://cdn…` la prueba de arriba lo caza; esta
    fija el motivo por el que la cadena `http` está permitida, para que no se
    convierta en una puerta abierta.
    """
    html = api.get("/").text
    for m in re.finditer(r'https?://[^"\'\s>)]*', html):
        contexto = html[max(0, m.start() - 30):m.start()]
        assert "xmlns" in contexto, (
            f"la única URL admitida en la plantilla es el espacio de nombres de SVG; "
            f"esta no lo es: {m.group(0)!r}")
        assert m.group(0).startswith("http://www.w3.org/"), m.group(0)
