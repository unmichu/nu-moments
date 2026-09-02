"""ING-9 · paso 3 · Los 9 escenarios curados, uno por uno.

«Con una cobertura de señal del 11.4 %, que un escenario se rompa al cambiar
algo no es hipotético.» Esto es ese paso, automatizado: si un cambio en la
política, en el scoring o en los artefactos mueve una decisión del guion, esta
suite lo dice antes que el público.

El `asof` de cada caso es el que quedó **registrado en su ficha**, no una hora
inventada: con otra hora la señal envejece y el escenario deja de cuadrar.
"""
from __future__ import annotations

import pytest

import comun


@pytest.fixture(scope="module")
def api():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


def _casos():
    return [(c["clave"], c) for c in comun.casos_curados()]


@pytest.mark.parametrize("clave,caso", _casos(), ids=[c[0] for c in _casos()])
def test_cada_escenario_da_la_decision_que_promete_el_guion(api, clave, caso):
    r = api.post("/api/decidir", json={"customer_id": caso["customer_id"],
                                       "asof": comun.asof_del_caso(caso)})
    assert r.status_code == 200
    d = r.json()

    esperado = caso["decision"]
    ofertado = d["ofertas"][0]["producto"] if d["ofertas"] else None
    assert ofertado == esperado.get("nudge_type"), (
        f"{clave}: el guion promete {esperado.get('nudge_type')!r} y salió {ofertado!r}")

    if esperado.get("enviar"):
        assert d["decision"] in ("oferta", "sustitucion")
        assert d["ofertas"][0]["razon"], "una oferta sin leyenda no se puede presentar"
    else:
        assert d["decision"] == "silencio"
        assert d["encabezado"]["titulo"] and d["encabezado"]["texto"]
        assert d["puerta_reportada"], "un silencio sin puerta reportada no es auditable"


def test_la_sustitucion_ofrece_la_alternativa_sana(api):
    """`fragil_sustituye` · el veto no es censura, es sustitución."""
    caso = next(c for c in comun.casos_curados() if c["clave"] == "fragil_sustituye")
    d = api.post("/api/decidir", json={"customer_id": caso["customer_id"],
                                       "asof": comun.asof_del_caso(caso)}).json()
    assert d["decision"] == "sustitucion"
    assert d["sustituye_a"] == "limit_increase"
    assert d["ofertas"][0]["producto"] == "bill_reminder"
    assert comun.silencio_de(d, "limit_increase")["puerta"] == "S3_fragilidad"


def test_el_caso_estrella_no_reporta_un_silencio_generico(api):
    """`fragil_silencio` · frágil, señal fresca de línea y **cupo libre**.

    S1 cierra tres productos y se evalúa antes que S3; si se reportara la
    primera puerta que se dispara, la demo diría «no hay señal» —que es falso y
    aburrido— en vez de «detectamos que la querías y decidimos no dártela».
    """
    caso = next(c for c in comun.casos_curados() if c["clave"] == "fragil_silencio")
    d = api.post("/api/decidir", json={"customer_id": caso["customer_id"],
                                       "asof": comun.asof_del_caso(caso)}).json()

    assert d["puerta_reportada"] == "S3_fragilidad"
    assert comun.traza_de(d, "S1_sin_senal")["resultado"] == "cierra"
    assert comun.traza_de(d, "S2_cupo")["resultado"] == "pasa", "el cupo está libre"
    assert comun.silencio_de(d, "limit_increase")["puerta"] == "S3_fragilidad"
    # y el cliente sí reveló la intención: el silencio es una decisión, no un vacío
    assert d["senales"]["limit_increase"]["momento"] == "on_time"


def test_todos_los_escenarios_corren_con_el_mismo_nivel_de_modelo(api):
    niveles = set()
    for c in comun.casos_curados():
        d = api.post("/api/decidir", json={"customer_id": c["customer_id"],
                                           "asof": comun.asof_del_caso(c)}).json()
        niveles.add(d["modelo"])
    assert len(niveles) == 1, f"la demo mezcla niveles de la escalera: {niveles}"
    assert "degradado" not in niveles
