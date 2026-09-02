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

**El silencio es el estado más frecuente: 86.4 % de los casos.** No es una pantalla vacía, es una decisión con razón registrada.

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

## 4.b · La experiencia: que el juicio se pueda leer

El modelo puede tener razón y aun así no convencer a nadie si el número que
enseña es `0.03007`. La pantalla se rehízo alrededor de una idea: **cada cifra
que aparece dice qué mide, sobre qué población y cómo se lee.**

### Dos lecturas, una detrás de la otra

La oferta ya no se enseña de golpe. Lo primero que se ve es **lo que vería el
cliente en la app**: el banner con el título y la frase, y un botón. Nada más. Ni
un score, ni un percentil, ni una traza de puertas: un cliente no audita su
propia recomendación.

Detrás de **«Mostrar por qué»** está la otra lectura, la de quien tiene que
defender la decisión: las gráficas de población, los tres factores, la traza de
las 8 puertas y el expediente del cliente. Es el mismo dato, no un resumen: lo que
se abre es exactamente lo que produjo la decisión.

Cuando el sistema se calla no hay banner ni botón que pulsar, así que la pantalla
de silencio se enseña completa desde el principio: ahí la vista de auditoría *es*
la pantalla.

### El «por qué» se ve, no solo se lee

Un percentil escrito no responde «¿por qué él y no otro?». Cinco gráficas sí, y
todas se alimentan de `app/panorama.py` —conteos y distribuciones sobre los 38 000
del mismo corte—, nunca de una cifra escrita a mano:

1. **Su lugar entre los 38 000.** El reparto real del corte en una barra apilada
   —1 748 reciben esta misma oferta, 2 802 otra, 32 843 ninguna— con el segmento
   del cliente marcado, y el desglose de por qué se calla con los demás (27 872
   sin señal reciente, 2 283 sin cupo, 2 202 dados de baja…).
2. **Dónde cae en la distribución.** El histograma de `p_intencion` de los 38 000
   al mismo corte con su barra marcada, la mediana y la tasa base señaladas en el
   eje, y el percentil escrito: «38.69 %, percentil 98.36 %; solo 622 de 38 000
   tienen una más alta». El eje es logarítmico porque la distribución lo exige: la
   mediana está en 3.19 % y el máximo en 87.54 %. Y por eso mismo la franja avisa
   de lo que **no** es: la marca cae al 85.80 % del ancho del eje, no al 98.36 %,
   y la regla del percentil del score va en su propia caja debajo, rotulada
   «otra escala», para que dos posiciones contiguas no se lean con la misma regla.
3. **Su probabilidad contra la tasa base.** Dos barras a la misma escala —el
   cliente y la población— con el múltiplo al lado: 6.54× en intención, 4.18× en
   enganche.
4. **Cuándo fue la señal**, situada en los umbrales que usa la política: fresca
   hasta 24 h, tibia hasta 7 días, fría después. El marcador cae donde de verdad
   está la señal del cliente, no donde quedaría bonito.
5. **Cuántas veces ya se le dijo**: sus exposiciones frente al cupo de 2, y debajo
   la curva de fatiga contada en los datos —15.72 % de enganche en la primera
   exposición, 3.50 % en la tercera, con las bajas subiendo de 0.28 % a 2.57 %—
   con su próxima exposición marcada sobre la curva.

Ninguna gráfica se explica sola: cada una lleva su lectura escrita al lado (el
percentil, el múltiplo, los conteos) y esa misma frase es la alternativa textual
que anuncia a un lector de pantalla. Un lector que no ve la barra lee el número.

**El score, desarmado.** Ya no se enseña el producto suelto, sino los tres
factores en sus unidades naturales —la probabilidad de que el cliente haga la
acción, la probabilidad de que responda al aviso y el valor en **días de
descubierto evitados**— y luego el resultado. Cada factor lleva su referencia
*calculada*: cuántas veces está por encima de la tasa base observada de esa
acción en ese corte, y en qué percentil queda frente a los otros 38,000. La tasa
base es un conteo sobre `labels_intent.parquet`; el percentil, la posición real
en la distribución. Ninguno de los dos se estima.

**El corte y el silencio se explican.** «Corte» es la fecha desde la que el
sistema mira hacia atrás: nada posterior a ella existe para él. «Silencio» es el
porcentaje de los 38 000 clientes a los que hoy no se les dice nada. Las dos
explicaciones están a un `?` de distancia, alcanzable con el ratón, con el
teclado y con el dedo.

**Se puede cambiar de foto.** Hay 5 tablas as-of en disco y el selector permite
elegir entre ellas. La cobertura **se recalcula**, porque cambia de verdad:
83.96 % de silencio el 2026-05-23 y 89.26 % el 2026-06-14. Con «auto», cada
escenario curado se evalúa en la fecha exacta en la que se verificó.

**La traza cuenta un recorrido, no una lista de códigos.** Cada puerta con su
pregunta en lenguaje llano («¿Este producto le haría daño?»), qué comprueba, y un
resultado distinguible a simple vista: pasa, cierra o no activa. *No activa* se
explica: la puerta existe y se ejecuta, pero en el piloto no cierra a nadie; no
es un fallo. Los silencios se agrupan por la puerta que los cerró, con el porqué
de cada producto.

**El cupo tiene una razón, no un número mágico.** Son 2 exposiciones por tipo de
producto porque en la tercera el aviso engancha al 3.51 % y da de baja al 2.53 %:
0.72 bajas por cada enganche. Insistir a partir de ahí destruye más de lo que gana.

**Filtro por lo que el sistema haría.** La búsqueda libre se filtra por el tipo
de oferta que ese cliente recibiría —o por silencio y la puerta que se lo cerró—.
No es una heurística: corre las mismas puertas y el mismo score sobre los 38 000
al corte elegido.

**La línea del tiempo es la tesis dibujada.** Navegación y avisos en el mismo
eje: se ve la señal y se ve si el aviso llegó cerca o lejos de ella. El corte
está marcado y el tramo posterior es una franja rayada y **vacía a propósito**:
después del corte el sistema no mira, y en ese dibujo no hay ni una marca.

**Modo claro y oscuro**, con la elección recordada en el navegador, contraste
suficiente en ambos y foco visible en todo lo que se pueda enfocar. El tema se
aplica antes de pintar, así que no hay destello al cargar. En las gráficas el
segmento del cliente se distingue por **color y por forma** —raya vertical con
punta, contorno propio—, nunca solo por el tono.

**La página no se desplaza de lado.** De 320 px a 2560 px el `body` no tiene
scroll horizontal. Lo que es intrínsecamente ancho —la línea del tiempo, la tabla
de señales— se desplaza **dentro de su propio contenedor**, sin arrastrar a la
página. La regla la vigilan cuatro pruebas sobre el CSS de la plantilla en
`pipeline/tests/test_interfaz.py`.

**Un solo formato de porcentaje.** Todo lo que lleva `%` se escribe `XX.XX %`
—dos decimales, espacio antes del signo— venga de la API o de la prosa de la
pantalla. Antes convivían `86.43 %` y `14.0 %` y parecía que los números salían
de dos sitios distintos. Cuando un porcentaje no existe se escribe `—`, no
`0.00 %`: no saber y valer cero no son lo mismo, y el silencio de este producto
se apoya justo en esa diferencia. El contrato está en
[`arquitectura.md`](arquitectura.md#contrato-de-formato-de-porcentajes).

## 4.c · Que se entienda sin preguntar: la pestaña «Cómo funciona»

La pantalla de decisión convence a quien ya sabe leerla. A un directivo que ve el
producto por primera vez no le convence nadie: no sabe qué es un score, ni por
qué hay ocho puertas, ni por qué el sistema presume de callarse. La segunda
pestaña existe para eso, y está escrita **para alguien que no ha visto nunca el
dataset**: cada término técnico se define donde aparece.

**Tres pestañas en el menú.** `Decisión` es todo lo que ya existía, sin un cambio
de comportamiento. `Cómo funciona` es la explicación. `Panorama` lleva al
dashboard. Las dos primeras conmutan paneles y se recorren con el teclado; la
tercera es un enlace, porque es otra página.

**Las tres preguntas, en el orden en que se hacen.** Primero qué va a querer el
cliente, luego si conviene hablarle ahora, y al final cuánto aporta o cuánto
daña. El orden es la cadena de preguntas: cada una necesita la respuesta de la
anterior para tener sentido. Cada pieza dice qué responde, qué mira, qué
devuelve y por qué va en ese lugar.

**Y se dice cuál aprende y cuál no.** Dos de las tres son aprendizaje automático.
La tercera —la tabla de valor— es aritmética sobre datos medidos: no se entrena,
no tiene conjunto de prueba y no tiene acierto que reportar. Va marcada en cada
tarjeta donde aparece, porque presentarla como modelo sería engañoso y sería el
adorno más barato de toda la pantalla.

**Las ocho puertas, con nombre y con conteo.** Cada una dice qué comprueba, **a
quién deja fuera** y **por qué eso es bueno para el cliente**, con el número real
de personas que silencia en el corte que se esté mirando: 27 872 sin señal
reciente, 2 283 sin cupo, 2 202 dados de baja, 377 por valor negativo y 109 por
fragilidad, que suman exactamente los 32 843 silencios del corte del demo. El
matiz que hace cierta esa suma también está escrito: una persona puede estar
cerrada por varias puertas, y el conteo la asigna a la que se le explica.

**Dos de las ocho no cierran a nadie, y se dice que no es un fallo.** S5 y S7
están implementadas y se ejecutan; en el piloto no cierran. Se dejan a la vista
con su estado en vez de esconderse para que el cuadro quede limpio.

**La cadena completa hasta los cuatro resultados.** Los tres números se
multiplican en uno —multiplicar y no sumar tiene una consecuencia que se nota: si
cualquiera es casi cero, el resultado es casi cero—, ese número pasa por las
puertas en orden, y de ahí salen ofrecer (5 133), sustituir (24), callar (32 843)
o no estar en catálogo (2 de los 6 productos, para todos a la vez). **Callar es
un resultado, no un fallo:** la pantalla vacía de un sistema roto y la de un
sistema que decidió no interrumpir se ven igual, y por eso esta lleva su razón
escrita.

**Nueve clientes de verdad.** Los nueve escenarios curados, cada uno con lo que
el sistema decide sobre él **hoy** —no con lo que promete el guion—: si algún día
dejan de coincidir, la pantalla lo dice.

**Un glosario en lenguaje llano, sin dos versiones.** Se reutiliza el de la
pantalla de decisión tal cual y se amplía con los términos que allí se daban por
sabidos (qué es un modelo, qué es una probabilidad, qué es una puerta, qué es λ).
Cada entrada dice de dónde viene. Si una palabra existe en los dos sitios, manda
la de la pantalla de decisión: dos redacciones del mismo término serían dos
productos distintos.

**Ninguna cifra está escrita en la plantilla.** Todas vienen de `/api/explicacion`,
que las cuenta sobre los 38 000 del corte elegido. Cambiar la foto en el menú
cambia la pestaña entera. Hay una prueba que compara el HTML con la respuesta de
la API y falla si alguien copia un número a mano.

## 5 · Alcance

**Dentro:** modelo de intención multi-etiqueta · modelo de momento · tabla de valor · las 8 puertas · simulación navegable con escenarios curados · pestaña explicativa · dashboard · evaluación contra tres baselines.

**Fuera:** integración real en una app · prueba A/B · modelo causal de uplift · optimización de la superficie en vivo.

## 6 · Métricas de éxito

Mejora en días de descubierto evitados sin caer por debajo del piso de ingreso, con menor tasa de baja que el envío indiscriminado. Detalle en [`metricas.md`](metricas.md).
