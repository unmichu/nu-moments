"""El dashboard general: dos rutas y ninguna sorpresa.

    GET /dashboard        la página, con todo pintado desde el servidor
    GET /api/dashboard    los mismos datos, en JSON

Este módulo expone un `APIRouter` llamado `router`. Quien monte el servicio lo
registra con `app.include_router(rutas_dashboard.router)`; aquí no se toca la
aplicación.

Dos decisiones que conviene leer antes de cambiar nada:

**El cálculo no se hace por petición.** Al importar este módulo —o sea, en el
arranque del servicio, porque es cuando `main.py` lo importa— se llama a
`dashboard_datos.obtener()`, que lee el artefacto precalculado
`dashboard/datos.json` si su firma cuadra con los parquet de hoy y lo
reconstruye si no. Servir la página después es armar HTML con un diccionario
que ya está en memoria.

**La página no pide nada a la red.** No hay `fetch`, no hay CDN, no hay fuentes
externas ni imágenes remotas: el HTML llega con los datos dentro y las gráficas
son barras de CSS y un `<svg>` en línea. Si el servicio arranca sin internet, la
página se ve igual. `analytics/tests/test_dashboard.py` lo vigila.

Si el cálculo falla, la ruta **dice qué falta** en vez de enseñar una página con
ceros: HTTP 200 con el motivo escrito, igual que el modo degradado del resto del
servicio.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__ in (None, ""):                                   # pragma: no cover
    import sys
    sys.path.insert(0, RAIZ)

from app import dashboard_datos                                 # noqa: E402

RUTA_PLANTILLAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
plantillas = Jinja2Templates(directory=RUTA_PLANTILLAS)

router = APIRouter(tags=["dashboard"])

# Lo que se sirve si el cálculo no salió. No es un error 500: es la misma
# política que el resto del servicio —decir qué falta con HTTP 200— porque una
# página caída se lee como una app rota y un aviso escrito, no.
_MOTIVO_CAIDO = ("El dashboard no se pudo construir. No se enseña una página con "
                 "ceros: se dice qué falta.")


def _datos():
    """El diccionario del dashboard, o `(None, motivo)` si no se pudo armar."""
    try:
        return dashboard_datos.obtener(), None
    except Exception as e:                                      # pragma: no cover
        return None, f"{type(e).__name__}: {e}"


# El precalentado del arranque. Importar este módulo ya deja los datos en
# memoria; si falla, la excepción no tumba el servicio y la primera petición
# vuelve a intentarlo y publica el motivo.
try:                                                            # pragma: no cover
    dashboard_datos.obtener()
except Exception:                                               # pragma: no cover
    pass


@router.get("/api/dashboard")
def api_dashboard():
    """Todas las métricas del proyecto, tal cual las pinta la página."""
    datos, motivo = _datos()
    if datos is None:                                           # pragma: no cover
        return JSONResponse(status_code=200,
                            content={"disponible": False,
                                     "motivo": motivo,
                                     "explicacion": _MOTIVO_CAIDO})
    return JSONResponse(status_code=200, content={"disponible": True, **datos})


@router.get("/dashboard", response_class=HTMLResponse)
def pagina_dashboard(request: Request):
    """La página. Todo el HTML se arma aquí; el navegador no pide nada más."""
    datos, motivo = _datos()
    return plantillas.TemplateResponse(
        request=request, name="dashboard.html",
        context={"d": datos, "motivo": motivo, "caido": _MOTIVO_CAIDO})
