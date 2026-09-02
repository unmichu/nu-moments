# pipeline

Ingesta, construcción de features, política de decisión y evidencias de ejecución.

| Archivo | Qué hace | Guía |
|---|---|---|
| `mapas.py` | Diccionarios producto→acción→pantalla y catálogo | BA-1 |
| `ingesta.py` | Carga y normaliza las 5 tablas a grano de evento | ING-1 |
| `features.py` | Tabla as-of con corte temporal estricto | BA-2 |
| `politica.py` | Las 8 puertas S0–S7 | ING-3 |
| `verificar_integracion.py` | Comprueba que el backend no está en fallback | ING-5 |
| `artifacts/` | Modelos serializados, fotos as-of, `demo_pack.json` y `casos_ejemplo.json` |  |
| `evidencias/` | Registro por etapa: filas dentro, filas fuera, duración | ING-8 |

`pipeline/demo/` ya no existe: era un prototipo anterior de la política (5 reglas,
sin S4/S6/S7) cuyos scripts apuntaban a un intérprete y a un directorio de salida
inexistentes. La única política del repo es `politica.py`. Lo único que se usaba
de allí, `casos_ejemplo.json`, vive ahora en `artifacts/`.
