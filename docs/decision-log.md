# Registro de decisiones

Formato: qué se decidió, por qué, y qué se descartó.

---

### D1 · Multi-etiqueta, no multiclase
Ventana de 7 días, 8 cabezas binarias. En multiclase, las tres acciones accionables para el negocio suman 7.1 % del label y el modelo las ignoraría. Con umbral propio por clase, no.

### D2 · Dos fechas de corte, a propósito
Modelo: corte principal con validación de origen móvil sobre tres cortes. Demo: otro corte distinto. Motivo: el día de pago solo toma tres valores y el corte del modelo cae en el hueco, así que **el caso de sincronía con la quincena no existe ahí**. No es una inconsistencia, son propósitos distintos.

### D3 · El baseline es un predictor constante, no «la clase mayoritaria de cada corte»
En uno de los tres cortes la clase mayoritaria es otra. Definirlo por corte sería un oráculo: usaría la distribución del test para elegir qué predecir. Baseline = clase constante elegida en entrenamiento.

### D4 · Cap de 2 exposiciones
Derivado, no dado. En la tercera exposición hay 0.72 bajas por enganche; en la cuarta, 1.89. El brief deja el guardrail sin número y esta es su derivación.

### D5 · Veto duro para clientes frágiles, no precio
El aumento de línea engancha **45.83 %** más a los clientes frágiles (25.36 % contra 17.39 %, `recon/out/05_by_type_fragile.csv`) y les causa +17.52 pp de utilización y +2.06 días en negativo. Se excluye de la función objetivo en vez de ponerle un peso: hay decisiones que no queremos que el modelo pueda comprar.

### D6 · λ = 266 por defecto
Que el aumento de línea nunca salga **es lo que hace la puerta S4**, no un defecto del catálogo. Se presenta como el producto que el sistema sabe no ofrecer.

### D7 · `w_a = 0.3`, y el riesgo queda cerrado
Descomponiendo `V(w_a)` analíticamente, el signo de las cuatro ofertas es invariante para `w_a ∈ [0,1]`. Solo λ mueve el signo.

### D8 · El árbol de puntúa, la regresión explica
Coinciden en la clase principal entre el **94.07 %** (corte del modelo, 2026-06-09) y el **62.76 %** (corte del demo, 2026-06-16) de las veces — el 89 % que se citaba era un punto, no un rango, y no reproduce. En el corte del demo **más de un tercio de las explicaciones caen a la regla**, así que `razones.json` publica el origen de cada explicación (`origen.modelo` / `origen.regla` / `origen.paquete`) y la interfaz debe mostrar la marca. Se descartó SHAP: arrastra dependencias pesadas y devuelve 82 números en vez de una frase.

### D9 · Sin `class_weight='balanced'`
Medido: cuesta 10.07 pp de exactitud.

### D10 · Regresión logística para el momento
El árbol aporta +0.0011 de AUC. No compensa la complejidad.

### D11 · No se usan: abandono, sesiones, hora del día, espaciado entre avisos
Todas desmentidas con datos. El abandono es **anti**-predictivo: quien abandona la simulación de préstamo pide uno el 0.15 % de las veces; quien solo la mira, el 23.33 %.

### D12 · La sesión no existe en estos datos
1.01 eventos por sesión, mediana de intervalo 58 h. Se implementa igual porque el reto la pide, se muestra el histograma y se sustituye por recencia por pantalla.

### D13 · Cobertura 13.6 % / 86.4 %
Una cifra previa de 84.5 % incluía un producto fuera del catálogo. Recomputada con el catálogo real: **5,157 de 38,000** clientes reciben oferta al corte del demo (`13.57 % / 86.43 %`, `GET /health`).

Aquí había un número mal copiado: se citaba `5,315`, que es el conteo de la **réplica offline** (`demo_pack.json`: `13.99 % / 86.01 %`, 5,315 de 38,000), no el de la política en vivo. Son dos poblaciones distintas —el paquete offline se congeló con un catálogo ligeramente distinto— y mezclarlas hacía que el 13.6 % de la cabecera no cuadrase con su propio conteo. Corregido el 2026-09-01.

### D14 · S5 y S7 se declaran no activas
No se fabrican casos para que se disparen. Se documenta y se dice.

### D15 · Los productos fuera de catálogo no se reportan como «sin señal»
Tienen su propio código. Un silencio por «sin señal» que en realidad es «no lo vendemos» sería mentir en la traza.

### D16 · Un solo formato de porcentaje, y se aplica también a la prosa
`XX.XX %` —dos decimales exactos y espacio antes del signo— en un único sitio (`app/formato.py`). La revisión encontró tres generadores que se lo saltaban con un decimal: el motivo de fragilidad (`pipeline/ingesta.py`) y dos plantillas de razón (`app/razones.py`), que enseñaban `utilización 83.4 %`. Se pasaron por `formato.pct()`.

También se normalizaron las narrativas de `casos_ejemplo.json`, que son texto visible en la pantalla y traían `5.9%`, `59.9%`, `3.2%` sin espacio y con un decimal. **Se corrigió el formato, nunca el valor**: `41.63 %`, `10.30 %` y `59.90 %` siguen siendo los de `recon/out/04_moment_recency.csv`. El único cambio de redacción fue `100% MEDIADO` → `totalmente MEDIADO`, que era énfasis retórico y no una medición.

Los umbrales de política escritos en prosa (`por encima del 70 %`) se dejan como están: son constantes de la política, no cifras medidas, y `70.00 %` no se lee mejor.

### D17 · El «82.7 % sin eventos en 24 h» era un número mal copiado
La pantalla justificaba los escenarios curados con «el 82.7 % de los clientes no tiene eventos en 24 h». Recomputado desde `app_events.parquet`, al corte del demo el valor es **82.84 %** (31,478 de 38,000), y varía entre 82.84 % y 88.16 % según el corte. El `82.7` no sale de ningún recon; el valor más parecido en `out/` es el `82.72` de `03_screen_action_p72h.csv`, que es otra cosa (probabilidad de acción a 72 h tras ver la pantalla de pago de servicios). Corregido en la plantilla, en el mensaje de error de `app/main.py` y en `instrucciones/ingenieria.md`.

Queda **escrito a mano**, que es la deuda de fondo: a diferencia del contador de cobertura, este porcentaje no se recalcula al arranque. Mientras siga siendo una constante hay que reescribirlo si cambia el corte del demo.

### D18 · La oferta se enseña en dos lecturas, no de golpe
La pantalla enseñaba el banner, los tres factores, las referencias y la traza al mismo tiempo. Eso no se parece a lo que ve un cliente en la app y además entierra el argumento: si todo tiene el mismo peso, nada destaca.

Se separó en dos lecturas. La inicial es la del cliente —título, frase y un botón—. Detrás de **«Mostrar por qué»** está la de quien audita: las cinco gráficas de población, los tres factores, la traza de las 8 puertas y el expediente. Es el mismo dato desplegado, no un resumen. En la pantalla de silencio no hay banner que pulsar, así que ahí la vista de auditoría se enseña completa desde el principio.

### D19 · El histograma de la distribución va en escala logarítmica
No es una preferencia estética: en `savings_goal` la mediana de `p_intencion` es 3.19 % y el máximo 87.54 %. Con cubos de ancho constante el 97 % de los 38,000 cae en el primero y el dibujo no informa de nada. En log10 la misma población ocupa todo el eje y la posición del cliente se lee. El eje va rotulado como logarítmico y la ayuda explica por qué, para que la escala no engañe a nadie.

Se descartó el histograma por percentiles: con cubos de igual masa todas las barras miden lo mismo por construcción y el gráfico deja de decir dónde está la gente.

### D20 · La curva de fatiga se cuenta por corte, no se lee del CSV de recon
`recon/out/04_fatigue_curve.csv` tiene la curva sobre el panel completo. La gráfica del «por qué» la recuenta desde `nudges` con corte estricto `shown_ts < asof`, igual que la tasa base de enganche, para que no enseñe información posterior al corte con el que se decidió. Solo se publican las exposiciones con **al menos 200 avisos**: por encima de la sexta quedan decenas de casos y la tasa sería ruido dibujado como dato.

### D21 · El test de red comprueba peticiones, no la cadena `http`
`test_la_pantalla_no_depende_de_la_red` prohibía el literal `http://` en el HTML. Eso marcaba `xmlns="http://www.w3.org/2000/svg"`, que es el identificador del espacio de nombres de SVG —un nombre, no una URL que el navegador visite—, y el falso positivo dejaba la pantalla sin poder dibujar un SVG en línea.

Ahora se comprueba lo que de verdad saldría a la red: `src`/`href` a otro origen, `@import`, `url()` externo, `fetch`/`WebSocket` absolutos, `<link>` externo y las URL sin esquema (`//cdn…`); los atributos `xmlns` se excluyen antes de buscar. Y se añadió la contracara, `test_el_svg_en_linea_solo_declara_espacios_de_nombres`, que exige que toda cadena `http` de la plantilla esté precedida por `xmlns` y apunte a `www.w3.org`: la excepción queda acotada en vez de abierta.

### D22 · El desbordamiento horizontal era una colisión de clases, y ahora hay red
El `body` se desplazaba de lado: 1508 px de `scrollWidth` en una ventana de 1440. La causa era `.factor.res`, el recuadro del score, que compartía clase con `.res`, la insignia de la traza, y esa clase trae `white-space:nowrap`. El texto «Percentil 99.52 % frente a los demás en este corte» se volvía indivisible, su ancho pasaba a ser el mínimo de la pista del grid, y ese mínimo empujaba `.factores` → `.oferta` → `main` → `body`.

El recuadro se llama ahora `.factor.total`. Además se puso red debajo: `min-width:0` global, `minmax(0,1fr)` en todas las pistas flexibles, `overflow-wrap` en el texto largo, la línea del tiempo y la tabla ancha dentro de contenedores con `overflow-x:auto`, y la burbuja de ayuda anclada abajo de borde a borde por debajo de 700 px. Cuatro pruebas nuevas vigilan las reglas sobre el CSS de la plantilla, sin navegador.

### D23 · El scroll horizontal volvía con una burbuja de ayuda abierta
La red de D22 medía la página **en reposo**: 42 combinaciones (320–2560 px, claro y oscuro, panel abierto, `<details>` desplegados) daban exceso 0. Abriendo las burbujas de una en una, la de «Cómo se lee el histograma» desbordaba **70 px a 768 y 38 px a 800** —banda 701–830 px—.

La causa es geométrica: `.ay-p` es `position:absolute` con `width:min(320px,78vw)` centrada sobre su botón, así que si el botón queda a menos de media burbuja del borde, la burbuja sale y arrastra el `scrollWidth`. Lo único que la sujetaba era el anclaje al viewport, y ese anclaje vivía solo por debajo de **700 px**: entre 701 y 1020 no había nada.

El anclaje sube a **1020 px**, que es donde `main` ya pasa a una columna. Los dos números tienen que ser el mismo, y hay un test que lo compara leyendo los dos `@media` del CSS: si se separan vuelve a abrirse la banda huérfana.

Y el estado «burbuja abierta» entra en la batería de anchos (`test_bateria_de_anchos_con_una_burbuja_abierta`, 21 anchos): por debajo del anclaje el exceso es 0 **por construcción** —`position:fixed` entre `left:10px` y `right:10px`—, y ningún ancho de la banda medida queda fuera del anclaje. Se comprueba sobre el CSS, sin navegador, como el resto de la sección 8.

Verificado además con Chrome 152 sin cabeza sobre la app real (`/` en un iframe del ancho exacto, 35 burbujas abiertas de una en una, 23 anchos × 2 temas = 46 combinaciones): **exceso 0 en todas**. Con el `@media` devuelto a 700 px el mismo arnés reproduce 70 px a 768 y 38 px a 800, con «Cómo se lee el histograma» como culpable, así que la medición mide lo que dice medir.

### D24 · `n_encima` se cuenta contra el valor exacto, no contra el redondeado
La pantalla decía «solo **623** de 38 000 tienen una más alta» cuando son 622. `p_intencion` se publica redondeada a 4 decimales (0.38691688 → 0.3869) y el percentil se calculaba con ese número contra el array **sin redondear** con `side="right"`: el propio cliente, que vive en la población con todos sus decimales, quedaba por encima de sí mismo. El mismo patrón daba 181 en el `score`, donde el conteo es 180.

`VistaCorte` guarda ahora los valores sin ordenar alineados con `idx` y resuelve el del cliente por su id antes de contar. El exacto solo sustituye al publicado si **son el mismo número** (misma cifra a los decimales que trae el publicado, nunca menos de 4): la vista se construye a las 12:00 del corte y una petición a otra hora del mismo día puede dar otro estado de señal y, con él, otro `p_enganche` y otro `score`. Cuando esas dos cifras no coinciden se cuenta contra la publicada —rankear otra sería enseñar el percentil de un número que no está en pantalla—.

El percentil del caso estrella no se mueve (98.36 %); sí se afinan los de los cortes densos, donde el redondeo a 4 decimales cubría varios miles de vecinos (38.88 → 38.86 %, 74.73 → 74.74 %). Tres pruebas recuentan a mano sobre los 38 000, sin `searchsorted`, y una de ellas fija que el número que producía el redondeo (623) ya no se publica.

### D25 · Dos franjas contiguas no pueden leerse con la misma regla
El histograma es log10 y la regla del score es percentil lineal, y estaban pegadas. En el caso estrella la marca del cliente cae al **85.80 % del ancho** del eje mientras su percentil es **98.36 %**: leer la primera franja como la segunda le quitaba 12 puntos de excepcionalidad, justo en la dirección que hace parecer al cliente menos excepcional.

No se cambió la escala —D19 sigue en pie: en lineal el 97 % cae en la primera barra—. Se separaron las lecturas: cada eje lleva rótulo de lo que mide («probabilidad · escala log», «percentil · escala lineal»), la respuesta publica las dos posiciones (`pos_pct_cliente` junto al `percentil`) y la franja lleva la advertencia con los dos números reales; la regla del score pasa a su propia caja, `.otra-escala`, con su cabecera «aquí la posición sí es el percentil». La alternativa textual lo dice también, para quien no ve el dibujo.

### D26 · Un cubo vacío no es un cubo bajito
`Math.max(b.alto_pct, 1.8)` existe para que un cubo de una o dos personas se vea, pero aplicado al cubo vacío convertía «aquí no hay nadie» en «aquí hay poca gente». Y los cubos vacíos son reales: en `loan_offer` al corte 2026-05-23 el cubo 15 está vacío y los 14, 16, 17 y 20 tienen entre 1 y 3 clientes. `alto_pct` no los distingue —con miles en el cubo más poblado, 0 y 1 redondean los dos a 0.00 %—, así que el dibujo mira `n`: con 0 clientes no hay barra, solo el hueco marcado con una línea de puntos.

### D27 · La narrativa del escenario también espera detrás del botón
La tarjeta «Escenario» enseñaba porcentajes (tasa base, enganche por momento) encima del banner, antes de pulsar «Mostrar por qué», y eso mellaba la idea de D18. Es andamiaje del demo, no parte del banner, así que la narrativa se movió detrás del mismo botón que el resto de los números. Antes de pulsarlo la pantalla dice qué escenario es y dónde están sus cifras.

## Alternativas evaluadas y descartadas

**Modelo de mejor hora de envío.** Tres golpes: el rango horario del enganche es de 0.98 pp sin monotonía; el espaciado entre avisos no tiene efecto controlando por número de exposición; y el generador no tiene término de hora. Habría sido vender ruido.

**Extender el veto al préstamo.** Cuesta 6.5 pp más de ingreso y no mejora los días en negativo.

**Tasa de clic histórica como variable.** Aporta +0.0032 de PR-AUC y presenta paradoja de Simpson: marginalmente el signo se invierte, y controlando por número de exposición se vuelve positivo. Vale más como hallazgo que como variable.
