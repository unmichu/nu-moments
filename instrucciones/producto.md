# Instrucciones · Producto

## Contexto mínimo

El reto pide tres cosas a Producto, en este orden: **elegir y defender la función objetivo antes de diseñar la feature**, comparar impactos entre objetivos, y definir dónde, cuándo y cómo aparece la recomendación — **incluido cuándo no aparece**.

El último punto es el diferenciador. Cualquiera entrena un clasificador; un asistente que sabe callarse es una tesis de producto.

---

## PRD-1 · Ratificar las 8 puertas · BLOQUEA A INGENIERÍA

No hay que redactarlas, ya están en `../docs/prd.md`. Hay que **ratificar el orden y confirmar los códigos**, porque Ingeniería construye contra ellos.

Dos listas distintas, a propósito:

- **Evaluación:** `S0 → S6 → S1 → S2 → S5 → S3 → S7 → S4`
- **Reporte:** `S0 > S6 > S3 > S2 > S5 > S7 > S4 > S1`

La segunda es la que hace que un cliente frágil con cupo libre reporte *veto por daño* en lugar de un silencio genérico. Es la diferencia entre que la demo diga algo memorable y que diga algo aburrido.

**S5 y S7 se declaran no activas en el piloto.** No se fabrican casos para que se disparen.

---

## PRD-2 · La función objetivo

Ya está decidida. Lo que falta es **defenderla en 90 segundos**:

```
U = p_intencion × p_enganche × V(λ)
V = (−Δdías_en_negativo) + (Δingreso / λ) + 0.3 · Δahorro
```

### Los tres argumentos, en orden de fuerza

**1. Engagement y rentabilidad eligen el mismo producto.** El aumento de línea es primero en clics y primero en ingreso — y último de todos en salud financiera. Optimizar clics no es una alternativa neutral: es la misma decisión mala por otra vía.

**2. λ no se eligió, se midió.** Dos caminos independientes, a escalas de volumen que difieren 12 veces, dan **162.7** y **164.8** MXN por día en descubierto. El statu quo revela **266**. Un parámetro medido, no una cifra de conveniencia.

**3. La satisfacción no se esquiva, se sustituye.** El indicador declarado está ausente en el 69 % de los clientes por diseño. Se reemplaza por dos señales reveladas con cobertura completa y cero valores faltantes: la baja de notificaciones y el descarte. Una baja cuesta más esfuerzo que responder una encuesta, así que dice más.

### La regla de los tres denominadores

Nunca en la misma frase:

| Número | Qué mide | Denominador |
|---|---|---|
| 63.45 % | exactitud del modelo donde hay señal | clientes con señal |
| 49.39 / 30.57 / 24.84 % | conversión por producto dado señal ≤24 h | clientes con señal en esa pantalla |
| 32.69× | lift de una pantalla sobre su tasa base | tasa base de la acción |

Mezclarlos es el error más fácil bajo presión y el más caro delante de un jurado técnico.

---

## PRD-3 · Copy

Cada oferta y cada estado de silencio necesita su texto. Regla: **la leyenda explica con el hecho del cliente, no con el modelo**. Nadie quiere leer "tu probabilidad de intención es 0.34".

| Situación | Plantilla |
|---|---|
| Meta de ahorro | «Entraste a Cajitas hace {horas}. Si apartas {monto} cada quincena, en {meses} llegas a tu meta.» |
| Préstamo | «Simulaste un préstamo hace {horas}. Con tu historial, esto es lo que te podemos ofrecer hoy.» |
| Aumento de línea | «Tu tarjeta está al {util} % y llevas {meses} sin retrasos. Podemos subirte la línea.» |
| Sustitución | «Entraste a subir tu línea hace {horas} y tu tarjeta está al {util} %. Un aumento ahora te costaría más de lo que te ayuda. Esto sí te conviene: {alternativa}.» |
| Silencio · sin señal | «No hay nada que hayas mostrado interés en hacer. Mejor no interrumpir.» |
| Silencio · cupo | «Ya te avisamos {n} veces de esto. Insistir una tercera vez cuesta más de lo que suma.» |
| Silencio · fragilidad | «Sí detectamos que buscabas {producto}, pero con tu situación actual te dejaría peor. No te lo vamos a ofrecer.» |
| Silencio · baja | «Desactivaste las notificaciones. Se respeta.» |

La de sustitución es la más importante: **el veto no es censura, es sustitución.** Se aprovecha la intención sin vender deuda.

---

## PRD-4 · Guion de la demo

Seis paradas, cuatro minutos. El arco importa más que la cantidad.

| # | Escenario | Lo que se dice |
|---|---|---|
| 1 | Señal fresca de ahorro | «Entró a Cajitas hace 15 horas. Esto es fácil.» |
| 2 | Señal fresca de préstamo | «Mismo mecanismo, otro producto.» |
| 3 | **Frágil que pide línea → sustitución** | «Aquí empieza lo interesante. Vino a pedir más crédito, y su tarjeta está al 83 %.» |
| 4 | **Frágil con cupo libre → silencio** | «Este es el importante. **Podíamos hablarle.** El cupo estaba libre. Y decidimos no hacerlo.» |
| 5 | Fatiga | «Tres veces ya. La cuarta genera más bajas que enganches.» |
| 6 | Sin señal | «Y este es el 86 % de la base.» |

**La parada 4 es el centro del pitch.** El silencio no es una restricción que se activó: es convicción. Hay que decirlo despacio.

---

## PRD-5 · Pitch

15 minutos. Cinco personas hablan.

| Bloque | Min | Contenido |
|---|---|---|
| Gancho | 0–2 | El 98.5 % de los avisos va fuera de momento |
| El traidor | 2–4 | El producto con más clics es el último en eficiencia: de cada 14 clics, 13 no convierten |
| El agravante | 4–5 | Y engancha más a quien más daña |
| La bisagra | 5–6 | «La pregunta no era a quién hablarle. Era a quién no.» |
| Cómo funciona | 6–8 | Los tres modelos y las ocho puertas |
| Demo | 8–12 | Las seis paradas |
| Impacto | 12–14 | La política final: da la vuelta al signo del sistema conservando el 81.6 % del volumen |
| Honestidad | 14–15 | Lo que medimos y descartamos |

### El bloque de honestidad no es una debilidad

Tres cosas que sumaron al medirlas y descartarlas: la hora del día es ruido · las sesiones de navegación no existen en estos datos · el abandono es anti-predictivo. Y una alternativa completa evaluada y enterrada: el modelo de mejor hora de envío.

Mostrar una alternativa bien descartada demuestra criterio. Un jurado técnico lo premia.

---

## PRD-6 · Preguntas del jurado

| Pregunta | Respuesta |
|---|---|
| ¿Por qué dos fechas de corte? | El día de pago solo toma tres valores y el corte del modelo cae en el hueco. Ahí el caso de sincronía con la quincena no existe. Propósitos distintos, no inconsistencia. |
| El árbol empata con la regla, ¿para qué el modelo? | En ese corte sí. La ganancia es estabilidad: 2.61 pp de rango entre cortes contra 7.17. Y lo decimos nosotros primero. |
| ¿Por qué no usaron el indicador de satisfacción? | Falta en el 69 % por diseño. Usamos dos señales reveladas con cobertura completa. |
| ¿No es esto un modelo de mejor hora de envío? | No. La hora del día es ruido: 0.98 pp de rango sin monotonía. Lo que manda es la recencia de intención. |
| Dicen que suben el engagement, pero los enganches bajan | Cierto, y es el punto: **el engagement es el diagnóstico, no la meta.** La meta son días de descubierto evitados. Y la política de cap retiene el 96.1 % del ingreso y el 96.0 % de los enganches. |
| ¿Solo el 14 % recibe oferta? | Sí. Predecimos muy bien a ese 14 % y nos callamos con el resto. Un asistente que habla siempre no es un asistente. |
| ¿Quién lo adoptaría? | El equipo dueño del ciclo de vida del cliente. Se inserta antes de las reglas de frecuencia existentes, no encima. |
| ¿Y si el negocio dice que el daño sí vale? | Es una decisión legítima y la hacemos explícita con un precio. Nuestra recomendación es no, y aquí está el número para discutirlo. |

---

## PRD-7 · Qué se publica

El repositorio es **público**. Antes de subir cualquier documento nuevo:

1. Nada de nombres de personas, equipos internos, canales de chat ni rutas de repositorios internos.
2. Nada de citas de documentación interna, objetivos de negocio ni cifras reales de la empresa.
3. Nada de nombres de sistemas internos.
4. Todo lo derivado del **dataset sintético** es publicable sin restricción: números, tablas, modelos, código, hallazgos.

⚠️ **Borrar un archivo no basta.** Si algo se subió una vez, sigue en el historial. La comprobación tiene que mirar el historial completo, no solo el estado actual.

---

## Prompt para delegar

```
Eres responsable de producto. Trabaja en el repo nu-moments.

Lee primero: instrucciones/producto.md (completo), docs/prd.md,
docs/metricas.md y docs/decision-log.md.

Tu tarea es [PRD-N]. Solo esa.

Reglas innegociables:
- Escribe el contenido final, no una receta para escribirlo.
- Ningún número sin fuente. Si no se reproduce con un script de analytics/,
  no va al pitch.
- Nunca mezcles en la misma frase los tres denominadores (exactitud del modelo,
  conversión por producto, lift de pantalla).
- El copy explica con el hecho del cliente, nunca con la probabilidad del modelo.
- Español mexicano, natural. Nada de jerga de producto.
- El repositorio es público: nada de material interno de la empresa.

Al terminar: entrega el texto listo para pegar, y di explícitamente qué
decisiones dejaste abiertas en vez de rellenarlas por tu cuenta.
```
