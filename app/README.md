# app

Backend y frontend de la simulación. Un proceso, un puerto, sin paso de compilación.

| Archivo | Qué hace | Guía |
|---|---|---|
| `main.py` | FastAPI: carga al arranque, endpoints, manejo de errores | ING-4 |
| `scoring.py` | Escalera de fallback de tres niveles | ING-4 |
| `razones.py` | Rellena las plantillas con la contribución del modelo | BA-5 |
| `fixture.json` | Respuesta de ejemplo — desbloquea el frontend | ING-2 |
| `templates/index.html` | La pantalla | ING-6 |
| `static/` | CSS, JS y la librería reactiva vendorizada | ING-6 |

```bash
make demo   # producción del pitch, sin recarga automática
make dev    # desarrollo, con recarga
```

Usa `make demo` para presentar: la recarga automática puede matar el proceso en el peor momento.
