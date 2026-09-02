"""BA-9 · Cobertura, embudo y sesiones. Los números medidos son la referencia."""
import pytest

from analytics.metricas import _tabla_avisos, cobertura, curva_fatiga, embudo, por_producto
from analytics.sesiones import intervalos, sesionizar
from pipeline.mapas import CATALOGO_DEMO, CORTE_DEMO


@pytest.fixture(scope="module")
def avisos(con):
    return _tabla_avisos(con)


def test_cobertura_14_pct_con_el_catalogo_de_4(con):
    pct, _ = cobertura(CORTE_DEMO, CATALOGO_DEMO, con=con)
    assert abs(pct - 14.0) <= 0.1, pct


def test_silencio_86_pct(con):
    pct, _ = cobertura(CORTE_DEMO, CATALOGO_DEMO, con=con)
    assert abs((100 - pct) - 86.0) <= 0.1


def test_payroll_no_esta_en_el_catalogo():
    """Su pantalla acoplada es la de inicio: cualquiera que abra la app 'tiene
    señal' y se lleva el 10.5 % de las ofertas por trivialidad."""
    assert "payroll_portability" not in CATALOGO_DEMO
    assert len(CATALOGO_DEMO) == 4


def test_embudo_m1_m5(con, avisos):
    pct, _ = cobertura(CORTE_DEMO, CATALOGO_DEMO, con=con)
    e = embudo(avisos, pct).set_index("#")
    for k, esp, tol in (("M1", 14.0, 0.1), ("M2", 10.98, 0.05), ("M3", 4.47, 0.05),
                        ("M4", 0.41, 0.01), ("M5", 3.47, 0.05)):
        assert abs(e.loc[k, "obtenido"] - esp) <= tol, (k, e.loc[k, "obtenido"], esp)


def test_denominadores_del_clic(avisos):
    """10.98 % sobre los 237,603 con acción acoplada; 11.45 % sobre los 285,000."""
    assert int(avisos.tiene_accion_acoplada.sum()) == 237603
    assert len(avisos) == 285000
    assert abs(100 * avisos.engaged.mean() - 11.45) < 0.01


def test_curva_de_fatiga(avisos):
    cf = curva_fatiga(avisos)
    assert list(cf["enganche_%"]) == [15.68, 7.83, 3.51, 1.75, 0.70, 0.00]
    assert list(cf["baja_%"]) == [0.279, 1.270, 2.531, 3.308, 4.502, 6.112]


def test_limit_increase_primero_en_clic_y_ultimo_en_eficiencia(avisos):
    p = por_producto(avisos)
    assert p["clic_%"].idxmax() == "limit_increase"
    assert p["eficiencia"].idxmin() == "limit_increase"


def test_no_hay_sesiones_en_estos_datos(con):
    g = intervalos(con)
    assert abs(g.median() / 60 - 58) < 1.0, g.median() / 60
    assert abs(100 * (g <= 30).mean() - 1.09) < 0.05
    s = sesionizar(con, 30)
    assert abs(s.n_eventos.mean() - 1.01) < 0.01
