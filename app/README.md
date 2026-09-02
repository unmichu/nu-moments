# app

Backend y frontend de la simulación. Un proceso, un puerto, sin paso de compilación.

| Archivo | Qué hace | Guía |
|---|---|---|
| `main.py` | FastAPI: carga al arranque, 8 endpoints, manejo de errores | ING-4 |
| `scoring.py` | Escalera de fallback de tres niveles | ING-4 |
| `razones.py` | Rellena las plantillas con la contribución del modelo | BA-5 |
| `panorama.py` | Vista poblacional por corte, montada en el `lifespan` | ING-4 |
| `formato.py` | El único sitio que decide cómo se escribe un porcentaje | ING-4 |
| `explicacion.py` | Los datos de la pestaña «Cómo funciona» (`GET /api/explicacion`) | — |
| `dashboard_datos.py` | El cálculo del dashboard general: los 9 bloques, sin HTML | — |
| `rutas_dashboard.py` | `APIRouter` con `GET /dashboard` y `GET /api/dashboard` | — |
| `fixture.json` | Respuesta de ejemplo — desbloquea el frontend | ING-2 |
| `templates/index.html` | La pantalla: pestañas «Decisión» y «Cómo funciona» | ING-6 |
| `templates/dashboard.html` | La página del dashboard general | — |
| `static/` | CSS, JS y la librería reactiva vendorizada | ING-6 |

Diez endpoints en total: ocho en `main.py` y los dos del dashboard, que se montan
con `app.include_router(rutas_dashboard.router)`. La tabla completa, con lo que
devuelve cada uno, está en [`../docs/arquitectura.md`](../docs/arquitectura.md);
el dashboard, en [`../docs/dashboard.md`](../docs/dashboard.md).

```bash
make demo   # producción del pitch, sin recarga automática
make dev    # desarrollo, con recarga
```

Usa `make demo` para presentar: la recarga automática puede matar el proceso en el peor momento.

Para ensayar la degradación **sin corromper artefactos**, `NU_MOMENTS_NIVEL_MAX`
apaga los niveles por encima del que se nombra y lo publica en `/health`:

```bash
NU_MOMENTS_NIVEL_MAX=regla_24h  make demo   # nivel 2 activo
NU_MOMENTS_NIVEL_MAX=demo_pack  make demo   # nivel 3 activo
```
