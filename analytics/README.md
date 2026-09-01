# analytics

EDA, modelos, métricas y controles de calidad.

| Archivo | Qué hace | Guía |
|---|---|---|
| `recon/` | Exploración ya ejecutada: 8 scripts y sus salidas en `out/` | — |
| `entrenar.py` | Entrena los tres modelos y serializa | BA-5 |
| `evaluar.py` | Top-1/top-2, AUC, precisión en el tramo superior | BA-5 |
| `metricas.py` | Embudo M1–M5 y métricas por producto | BA-8 |
| `sesiones.py` | Sesionización, histograma y por qué no aplica | BA-7 |
| `calidad.py` | Controles con criterio de aprobado/reprobado | BA-9 |
| `tests/` | Canario de baselines y controles automatizados | BA-4 |

`recon/` ya contiene resultados calculados. Reutilízalos: ocho de las doce tablas del pitch se reformatean desde ahí en lugar de recalcularse.
