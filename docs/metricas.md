# Métricas

## North Star

**Días de descubierto evitados.** Todo lo demás se convierte a esa unidad mediante λ.

## Embudo primario

| # | Métrica | Definición | Valor en el statu quo |
|---|---|---|---|
| M1 | Cobertura de oferta | % de clientes que reciben ≥1 oferta | **13.6 %** (86.4 % silencio) |
| M2 | Tasa de clic | enganches / avisos mostrados | **10.98 %** |
| M3 | Conversión a 7 días | hizo la acción en los 7 días siguientes | **4.47 %** |
| M4 | Eficiencia del clic | M3 / M2 | **0.41** |
| M5 | Brecha con-clic / sin-clic | conversión si enganchó − si no | **+3.47 pp** |

## Por producto

| Producto | Clic | Conversión 7 d | Eficiencia | Con clic | Sin clic | Brecha |
|---|---|---|---|---|---|---|
| Recordatorio de pago | 11.30 % | **11.57 %** | **1.02** | 18.67 % | 10.67 % | +8.00 pp |
| Meta de ahorro | 8.95 % | 6.34 % | 0.71 | 12.65 % | 5.72 % | +6.93 pp |
| Inversión | 7.17 % | 1.87 % | 0.26 | 4.77 % | 1.64 % | +3.13 pp |
| **Aumento de línea** | **18.90 %** | **1.31 %** | **0.07** | 1.64 % | 1.24 % | **+0.40 pp** |
| Préstamo | 8.58 % | 1.22 % | 0.14 | 2.93 % | 1.06 % | +1.87 pp |

**El aumento de línea es primero en clics y último en eficiencia.** De cada 14 clics, 13 no convierten.

### Nota de rigor

El tipo de aviso y la superficie **están asignados al azar**, así que comparar entre productos es una lectura causal. El enganche **no** está aleatorizado: las columnas con-clic / sin-clic llevan sesgo de selección y son diagnóstico, no efecto causal.

### Nota de denominadores

La tasa de clic global aparece con dos valores según el denominador: **10.98 %** sobre los 237,603 avisos con acción acoplada, y **11.45 %** sobre los 285,000 avisos totales. No es una inconsistencia: un tipo de aviso no tiene acción acoplada y queda fuera del primero.

## De dónde sale el silencio

Tres cifras distintas según cuánto de la política se aplique. **La del pitch es la última: es lo que el motor ejecuta.**

| Alcance | Oferta | Silencio |
|---|---|---|
| Catálogo de 4 productos, asignación sin puertas | 14.0 % | 86.0 % |
| Con las puertas de señal, cupo y fragilidad | 14.6 % | 85.4 % |
| **Política completa, incluida la puerta de valor** | **13.6 %** | **86.4 %** |

La puerta de valor añade 1.1 pp de silencio: es la que cierra el aumento de línea para todos, porque a λ = 266 su valor esperado es negativo. Eso no es un defecto del catálogo — es la puerta funcionando.

**El contador de la interfaz se recalcula al arranque**: `politica.cobertura()` corre las 8 puertas sobre los 38,000 clientes en el `lifespan` del servicio y la pantalla muestra el resultado. No se lee de un artefacto ni —lo que importa— se escribe a mano en el HTML.

En cifras exactas al corte del demo (`GET /health`): **5,157 de 38,000 con oferta → 13.57 % / 86.43 %**. No confundir con los **5,315 (13.99 % / 86.01 %)** de `demo_pack.json`, que es la réplica offline congelada y mide otra población.

### Cobertura por corte — cambia de verdad

El selector de la pantalla recalcula, no reescala una cifra fija:

| Corte | Silencio | Oferta | Con oferta |
|---|---|---|---|
| 2026-05-23 | 83.96 % | 16.04 % | 6,094 |
| 2026-05-30 | 87.89 % | 12.11 % | 4,602 |
| 2026-06-09 | 87.91 % | 12.09 % | 4,593 |
| 2026-06-14 | 89.26 % | 10.74 % | 4,083 |
| **2026-06-16** (demo) | **86.43 %** | **13.57 %** | **5,157** |

### Por qué los escenarios van curados

Al corte del demo, el **82.84 %** de los clientes (31,478 de 38,000) no tiene ni un evento en las 24 h previas; entre cortes el rango va de 82.84 % a 88.16 %. Un selector al azar deja el panel de actividad vacío cuatro de cada cinco veces. Recomputado desde `app_events.parquet` en la revisión del 2026-09-01: la cifra anterior, `82.7 %`, no procedía de ningún recon.

## Estabilidad entre cortes — qué población mide cada cifra

Reproducible con `analytics/evaluar.py`. Se retiran los valores heredados que no
reproducen y se dice sobre qué población se mide cada uno, que es donde estaba
la ambigüedad.

| Predictor | Población medida | Media | Rango entre los 3 cortes |
|---|---|---|---|
| Baseline constante (`spei_out`) | clientes activos | 33.63 % | 15.99 pp |
| Regla de 24 h, **donde hay señal** | activos con señal ≤24 h (≈16 %) | 62.46 % | **2.22 pp** |
| Regla de 24 h, **híbrida** | todos los activos | 37.79 % | **13.98 pp** |
| **Modelo (árbol), top-1** | todos los activos | **43.80 %** | **2.65 pp** |

Dos lecturas, y conviene no mezclarlas:

1. **Donde hay señal, el árbol empata con la regla** (64.92 % contra 63.45 % en
   el corte principal). Se dice primero, no se esconde.
2. La ganancia es **cobertura y estabilidad**: la regla solo opina sobre el 16 %
   de los activos, y aplicada a toda la base se mueve 13.98 pp entre cortes
   contra los 2.65 pp del modelo.

**El «rango de 7.17 pp» que circulaba no reproduce con ninguna de las dos
poblaciones y queda retirado.** El argumento no se debilita: 2.65 contra 13.98
es una brecha mayor que 2.61 contra 7.17.

## Guardrails

| Guardrail | Valor |
|---|---|
| Baja de notificaciones | 0.969 % |
| Descarte | 37.24 % |
| Avisos por cliente al mes | **cap de 2 por tipo** |
| Silencio | 86.4 % |

El cap de 2 no viene dado: se deriva. En la tercera exposición ya se generan **0.72 bajas por cada enganche**; en la cuarta, **1.89**. El punto donde el coste supera al beneficio está entre la segunda y la tercera.

## Curva de fatiga

| Exposición | Enganche | Baja |
|---|---|---|
| 1 | **15.68 %** | 0.279 % |
| 2 | 7.83 % | 1.270 % |
| 3 | **3.51 %** | **2.531 %** |
| 4 | 1.75 % | 3.308 % |
| 5 | 0.70 % | 4.502 % |
| 6+ | **0.00 %** | 6.112 % |

Cada repetición corta el enganche a la mitad y duplica la baja. A la sexta exposición el enganche es exactamente cero.

## Simulación de políticas

| Política | Enviados | % vol | Enganche | Ingreso retenido | Días en negativo |
|---|---|---|---|---|---|
| P0 · enviar todo | 285,000 | 100 % | 11.45 % | 100 % | **+1,679** |
| P1 · cap 2 | 240,110 | 84.2 % | 13.06 % | 96.1 % | +1,612 |
| P6 · solo salud | 19,693 | 6.9 % | 27.97 % | 4.6 % | −1,502 |
| **P8 · cap 2 ∧ veto** | **232,500** | **81.6 %** | **12.55 %** | **75.2 %** | **−2,895** |

**P8 le da la vuelta al signo del sistema conservando el 81.6 % del volumen.**

## El precio sombra

Estimado por dos caminos independientes, a escalas de volumen que difieren 12 veces: **162.7** y **164.8 MXN por día en descubierto**. Convergen, así que λ ≈ 165 en el margen es un parámetro medido, no elegido. El statu quo revela **266**.
