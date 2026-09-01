# pipeline

Ingesta, construcción de features, política de decisión y evidencias de ejecución.

| Archivo | Qué hace | Guía |
|---|---|---|
| `mapas.py` | Diccionarios producto→acción→pantalla y catálogo | BA-1 |
| `ingesta.py` | Carga y normaliza las 5 tablas a grano de evento | ING-1 |
| `features.py` | Tabla as-of con corte temporal estricto | BA-2 |
| `politica.py` | Las 8 puertas S0–S7 | ING-3 |
| `verificar_integracion.py` | Comprueba que el backend no está en fallback | ING-5 |
| `artifacts/` | Modelos serializados y metadatos |  |
| `evidencias/` | Registro por etapa: filas dentro, filas fuera, duración | ING-8 |
| `demo/` | Código de exploración reutilizable |  |
