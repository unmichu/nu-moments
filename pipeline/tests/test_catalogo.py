"""D15 · Los productos fuera de catálogo llevan su propio código.

Un silencio por «sin señal» que en realidad es «no lo vendemos» sería mentir en
la traza, y la traza es lo que hace auditable al sistema.
"""
from __future__ import annotations

import comun
from pipeline.mapas import CATALOGO_DEMO, TODOS_LOS_PRODUCTOS
from pipeline.politica import C0, S1


def test_los_dos_productos_fuera_de_catalogo_se_reportan_con_C0():
    fuera = [p for p in TODOS_LOS_PRODUCTOS if p not in CATALOGO_DEMO]
    assert fuera == ["invest_start", "payroll_portability"]

    r = comun.decidir(comun.ficha_neutra())
    for p in fuera:
        s = comun.silencio_de(r, p)
        assert s is not None, f"{p} no aparece en los silencios"
        assert s["puerta"] == C0, f"{p} se reporta como {s['puerta']}, no como fuera de catálogo"


def test_fuera_de_catalogo_nunca_es_sin_senal():
    """Aunque el cliente no tenga ninguna señal, el motivo sigue siendo C0."""
    f = comun.ficha_neutra()
    for p in TODOS_LOS_PRODUCTOS:
        f["decision"]["senales_por_nudge"][p]["momento"] = "never"
        f["decision"]["senales_por_nudge"][p]["horas_desde_senal"] = None

    r = comun.decidir(f)
    for p in ("invest_start", "payroll_portability"):
        assert comun.silencio_de(r, p)["puerta"] == C0
        assert comun.silencio_de(r, p)["puerta"] != S1


def test_un_producto_fuera_de_catalogo_nunca_se_ofrece():
    f = comun.ficha_neutra()
    r = comun.decidir(f)
    ofertados = comun.productos_ofertados(r)
    assert "invest_start" not in ofertados
    assert "payroll_portability" not in ofertados
    assert set(ofertados) <= set(CATALOGO_DEMO)


def test_C0_nunca_es_el_silencio_que_se_le_cuenta_al_usuario():
    """Un «no lo vendemos» no puede ser la razón principal de la pantalla."""
    f = comun.ficha_neutra()
    for p in TODOS_LOS_PRODUCTOS:
        f["decision"]["senales_por_nudge"][p]["momento"] = "never"
    r = comun.decidir(f)
    assert r["decision"] == "silencio"
    assert r["puerta_reportada"] != C0
    assert r["puerta_reportada"] == S1


def test_C0_va_al_final_del_orden_de_reporte():
    r = comun.decidir(comun.ficha_neutra())
    puertas = [s["puerta"] for s in r["silencios"]]
    primeros_c0 = puertas.index(C0)
    assert all(p == C0 for p in puertas[primeros_c0:]), (
        "los fuera de catálogo deben quedar al final de la lista de silencios")


def test_la_razon_de_C0_lo_dice_en_lenguaje_natural():
    from app.razones import Razones
    r = comun.decidir(comun.ficha_neutra())
    texto = Razones().silencio(comun.ficha_neutra(), comun.silencio_de(r, "invest_start"))
    assert "piloto" in texto.lower()
