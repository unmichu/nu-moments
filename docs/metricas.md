# Métricas

## North Star

**Días de descubierto evitados.** Todo lo demás se convierte a esa unidad mediante λ.

## Embudo primario

| # | Métrica | Definición | Valor en el statu quo |
|---|---|---|---|
| M1 | Cobertura de oferta | % de clientes que reciben ≥1 oferta | **14.0 %** (86.0 % silencio) |
| M2 | Tasa de clic | enganches / avisos mostrados | **10.98 %** |
| M3 | Conversión a 7 días | hizo la acción en los 7 días siguientes | **4.47 %** |
| M4 | Eficiencia del clic | M3 / M2 | **0.41** |
| M5 | Brecha con-clic / sin-clic | conversión si enganchó − si no | **+3.48 pp** |

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

## Guardrails

| Guardrail | Valor |
|---|---|
| Baja de notificaciones | 0.969 % |
| Descarte | 37.24 % |
| Avisos por cliente al mes | **cap de 2 por tipo** |
| Silencio | 86.0 % |

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
