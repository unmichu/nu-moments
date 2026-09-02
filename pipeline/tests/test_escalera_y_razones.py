"""ING-4 · La escalera de fallback y el motor de razones.

Dos piezas, una prueba cada una:

* **La escalera** baja de nivel dejando escrito **por qué**. Nada de valores por
  defecto silenciosos: si falta un artefacto, se nota en `/health`.
* **Las razones** explican con el hecho del cliente, nunca con la probabilidad
  del modelo. Nadie quiere leer «tu probabilidad de intención es 0.34».
"""
from __future__ import annotations

import pytest

import comun
from app import scoring
from app.razones import PUERTA_ES, Razones
from pipeline.mapas import CATALOGO_DEMO
from pipeline.politica import C0, ORDEN_EVALUACION, S0, S1, S2, S3, S4, S5, S6, S7


# ==========================================================================
# La escalera
# ==========================================================================
def test_la_escalera_declara_su_nivel_activo_y_los_caidos():
    e = comun.escalera()
    estado = e.estado()
    assert estado["nivel_activo"] in ("v1", "regla_24h", "demo_pack")
    assert estado["nivel_activo"] == e.nivel_activo
    assert estado["tabla_valor_origen"], "debe decir de dónde salió la tabla de valor"
    for nivel, motivo in estado["niveles_caidos"].items():
        assert motivo, f"el nivel {nivel} cayó sin motivo escrito"


def test_puntuar_devuelve_los_cuatro_productos_del_catalogo():
    e = comun.escalera()
    ficha = comun.store().ficha(comun.CLIENTE_AHORRO, comun.ASOF)
    scores, nivel = e.puntuar(ficha)
    assert set(scores) == set(CATALOGO_DEMO)
    assert nivel == e.nivel_activo
    for prod, s in scores.items():
        assert {"p_intencion", "p_enganche", "V", "score", "confianza"} <= set(s)
        esperado = round(s["p_intencion"] * s["p_enganche"] * s["V"], 6)
        assert abs(s["score"] - esperado) < 1e-4, f"{prod}: el score no es p×p×V"


def test_sin_artefactos_la_escalera_baja_de_nivel_con_el_motivo(monkeypatch, tmp_path):
    """Si faltan los .pkl, el nivel 2 toma el relevo y dice qué pasó."""
    monkeypatch.setattr(scoring, "ARTIFACTS", str(tmp_path))
    e = scoring.Escalera.cargar(comun.store())
    assert e.nivel_activo == "regla_24h", "la regla de 24 h es el respaldo, no un error"
    assert "v1" in e.motivos and e.motivos["v1"]
    assert "demo_pack" in e.motivos
    assert "calculada de data/" in e.origen_tabla_valor


def test_la_regla_de_24h_prefiere_la_senal_fresca():
    """Nivel 2: `on_time` debe puntuar por encima de `warm`, y `cold` en cero."""
    regla = scoring.ReglaVeinticuatroHoras.cargar()
    tv = comun.tabla_valor()

    def score(momento, exposicion=1):
        f = comun.ficha_neutra()
        s = f["decision"]["senales_por_nudge"]["savings_goal"]
        s["momento"] = momento
        s["exposure_no_siguiente"] = exposicion
        return regla.scores(f, tv)["savings_goal"]

    assert score("on_time")["score"] > score("warm")["score"] > 0
    assert score("cold")["score"] == 0.0
    assert score("never")["score"] == 0.0
    # la fatiga pesa: la segunda exposición vale menos que la primera
    assert score("on_time", 2)["score"] < score("on_time", 1)["score"]


def test_un_cliente_inexistente_no_rompe_la_escalera_en_silencio():
    ficha = comun.store().ficha(comun.CLIENTE_AHORRO, comun.ASOF)
    ficha["perfil"]["customer_id"] = -1
    try:
        scores, nivel = comun.escalera().puntuar(ficha)
    except scoring.NivelNoDisponible as e:
        assert str(e), "si ningún nivel puede puntuar, el motivo viaja en la excepción"
    else:
        assert nivel in ("regla_24h", "demo_pack"), (
            "un cliente fuera de la tabla de features debe bajar de nivel, no inventar")


# ==========================================================================
# Las razones
# ==========================================================================
@pytest.mark.parametrize("puerta", [S0, S6, S1, S2, S5, S3, S7, S4, C0])
def test_cada_puerta_tiene_una_razon_en_lenguaje_natural(puerta):
    r = Razones()
    ficha = comun.ficha_neutra()
    hechos = {"motivo_fecha": "los primeros 3 días son un artefacto", "exposiciones": 2,
              "n_descartados": 3, "motivo_fragilidad": ["utilización 89.6 %"],
              "V": -0.077, "lambda": 266.0}
    texto = r.silencio(ficha, {"producto": "limit_increase", "puerta": puerta,
                               "hechos": hechos})
    assert texto and texto != "Sin razón registrada.", f"{puerta} no tiene razón"
    assert len(texto) > 15
    assert puerta in PUERTA_ES, f"{puerta} no tiene etiqueta humana para la traza"


def test_las_ocho_puertas_tienen_etiqueta_para_la_traza_plegada():
    for codigo in ORDEN_EVALUACION:
        assert PUERTA_ES.get(codigo), f"{codigo} saldría sin etiqueta en la UI"


def test_la_leyenda_habla_de_hechos_no_de_probabilidades():
    r = comun.decidir(comun.ficha_neutra())
    razones = Razones()
    ficha = comun.ficha_neutra()
    assert r["ofertas"], "la ficha neutra debería producir oferta"
    texto = razones.oferta(ficha, r["ofertas"][0])
    for prohibido in ("probabilidad", "p_intencion", "score", "AUC", "modelo"):
        assert prohibido not in texto, f"la leyenda menciona {prohibido!r}"


def test_el_encabezado_de_silencio_dice_que_el_sistema_decidio():
    """La pantalla de silencio no puede parecer que la app se rompió."""
    f = comun.ficha_neutra()
    f["nudges"]["opt_out"] = True
    r = comun.decidir(f)
    titulo, texto = Razones().encabezado_silencio(f, r)
    assert titulo and texto
    assert "error" not in titulo.lower() and "error" not in texto.lower()


def test_las_plantillas_dicen_de_donde_salieron():
    r = Razones.cargar()
    assert r.origen, "sin origen, /health no puede decir qué copy se está usando"
