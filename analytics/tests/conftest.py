"""Configuración común de las pruebas de analítica.

Pone la raíz del repo en `sys.path` para poder importar `pipeline.*` y
`analytics.*` sin instalar el paquete, y comparte una única conexión duckdb
entre todas las pruebas (abrirla por test cuesta más que el test).
"""
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from pipeline.features import _conexion  # noqa: E402


@pytest.fixture(scope="session")
def con():
    c = _conexion()
    yield c
    c.close()
