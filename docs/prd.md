# PRD · nu-moments

## En una línea

Una tarjeta que le muestra a cada cliente **la única acción más relevante en este momento** —crear una meta de ahorro, pedir un préstamo, subir su línea o ponerse al día con un pago— elegida por el modelo para optimizar su salud financiera con un piso de rentabilidad, **y que se queda callada cuando nada encaja**.

## 1 · Problema y oportunidad

**Lo difícil no es la interfaz, es el juicio.** Saber qué quiere el cliente, si es el momento de decir algo, y qué debe optimizar la recomendación.

**Los objetivos no apuntan al mismo lado.** En los datos, el engagement es ortogonal a la salud financiera (r = −0.086) y a la rentabilidad (r = +0.086). Optimizar clics no es un proxy de nada, ni siquiera de dinero. Y salud contra rentabilidad tienen correlación de rangos **−0.829**: el ranking se invierte casi por completo.

**El momento está desatendido.** El 98.5 % de los avisos se envía sin señal reciente de intención. El 1.5 % que sí la tiene convierte 41.63 % contra 10.11 %.

## 2 · El producto: cuatro salidas

El modelo decide cuál aplica a cada cliente en cada visita.

| Salida | Qué ve el cliente | Cuándo |
|---|---|---|
| **Recomendar** | La mejor acción para su salud financiera | Hay señal reciente y el valor esperado es positivo |
| **Sustituir** | Una alternativa que sí le conviene, en la misma pantalla donde vino a pedir otra cosa | Reveló intención en un producto que le haría daño |
| **Silencio** | Nada. La app normal, sin tarjeta | Sin señal, cupo agotado, o el aviso empeoraría su situación |
| **Fuera de catálogo** | Nada | El producto no se ofrece en este piloto |

**El silencio es el estado más frecuente: 86.0 % de los casos.** No es una pantalla vacía, es una decisión con razón registrada.

## 3 · El Reglamento del Silencio

Ocho puertas en orden. Cada una emite un código auditable y la respuesta de la API incluye la traza completa.

| Puerta | Se cierra cuando | Estado en el piloto |
|---|---|---|
| S0 | El cliente desactivó notificaciones | activa |
| S6 | La fecha cae en zona de datos contaminada | activa |
| S1 | No hay señal reciente de intención | activa |
| S2 | Ya se agotó el cupo de exposiciones del producto | activa |
| S5 | El cliente descartó este producto repetidamente | implementada, no activa |
| S3 | El cliente es frágil y el producto le haría daño | activa |
| S7 | El modelo no tiene confianza suficiente | implementada, no activa |
| S4 | El valor esperado del aviso es negativo | activa |

S5 y S7 se declaran **no activas** en vez de fabricar casos que las disparen.

## 4 · Función objetivo

```
U = p_intencion × p_enganche × V_producto(λ)
V = (−Δdías_en_negativo) + (Δingreso / λ) + w_a · Δahorro
```

Con **λ = 266 MXN por día en descubierto** (precio revelado del statu quo) y `w_a = 0.3`.

**Salud como objetivo, rentabilidad como piso** — no un número único que esconda el trade-off.

El peso del ahorro no cambia el resultado: descomponiendo `V(w_a)`, el signo de las cuatro ofertas es invariante para `w_a ∈ [0,1]`. Solo λ mueve el signo.

## 5 · Alcance

**Dentro:** modelo de intención multi-etiqueta · modelo de momento · tabla de valor · las 8 puertas · simulación navegable con escenarios curados · dashboard · evaluación contra tres baselines.

**Fuera:** integración real en una app · prueba A/B · modelo causal de uplift · optimización de la superficie en vivo.

## 6 · Métricas de éxito

Mejora en días de descubierto evitados sin caer por debajo del piso de ingreso, con menor tasa de baja que el envío indiscriminado. Detalle en [`metricas.md`](metricas.md).
