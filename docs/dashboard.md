# El dashboard general

`GET /dashboard` — todas las métricas del proyecto en una página, escrita para
alguien que **no ha visto el dataset ni ha estado en ninguna reunión**.

La pantalla de la demo (`GET /`) contesta *«¿qué le decimos hoy a este
cliente?»*. Esta contesta *«¿en qué nos basamos?»*. Son dos productos
distintos y por eso son dos páginas distintas.

```
GET /dashboard        la página completa, ya pintada desde el servidor
GET /api/dashboard    los mismos datos en JSON, con la misma procedencia
```

---

## Cómo está montado

| Archivo | Qué hace |
|---|---|
| [`app/dashboard_datos.py`](../app/dashboard_datos.py) | El cálculo. Arma un diccionario con los 9 bloques y no sabe nada de HTML |
| [`app/rutas_dashboard.py`](../app/rutas_dashboard.py) | Un `APIRouter` con las dos rutas. Se registra con `app.include_router(rutas_dashboard.router)` |
| [`app/templates/dashboard.html`](../app/templates/dashboard.html) | La plantilla. CSS en línea, gráficas en CSS y un `<svg>` en línea, cero red |
| [`dashboard/datos.json`](../dashboard/datos.json) | El artefacto precalculado que se sirve |
| [`analytics/tests/test_dashboard.py`](../analytics/tests/test_dashboard.py) | 32 pruebas: recuento, red, formato y lectura |

### El cálculo no se paga por petición

Construir el diccionario entero cuesta **~5 s**: carga el `Store` de 1.7 M
filas, monta la escalera de scoring, corre la política sobre los 38 000
clientes en los 5 cortes y vuelve a evaluar los dos modelos. Eso no puede pasar
dentro de una petición.

```
importar app.rutas_dashboard          ← ocurre en el arranque del servicio
  └── dashboard_datos.obtener()
        ├── ¿está en memoria de este proceso?      → se devuelve
        ├── ¿existe dashboard/datos.json y su FIRMA cuadra? → se lee (~3 ms)
        └── si no: se construye (~5 s) y se escribe el artefacto
```

La **firma** son los tamaños en bytes de los 5 parquet y de los artefactos del
pipeline, más `VERSION`, la versión de esquema del propio módulo. Si alguno
cambia, el artefacto describe otros datos y se reconstruye: así una cifra vieja
no puede sobrevivir a un `make pipeline`.

⚠️ **La firma NO mira el código que construye el diccionario.** Si tocas un
texto o un cálculo de `app/dashboard_datos.py` sin cambiar ningún dato, la firma
sigue cuadrando y el servicio te seguirá sirviendo el artefacto viejo sin avisar.
Al editar ese módulo hay que **subir `VERSION`** y regenerar; si no, el cambio no
se ve. Se regenera a mano con:

```bash
.venv/bin/python -m app.dashboard_datos
```

Medido: **la página se sirve en 30 ms y el JSON en 2 ms**.

### Si algo falta, se dice

Cada bloque se construye por separado. Si a uno le falta un insumo, ese bloque
**no aparece** y el motivo viaja en `avisos`, que la página pinta en rojo. Si
falla el diccionario entero, las dos rutas devuelven **HTTP 200** con el motivo
escrito: nunca un 500, y nunca una página de ceros. Un dashboard con ceros
miente y un 500 se lee como una app rota.

---

## Los nueve bloques, y por qué están en ese orden

El orden es una narración: primero quién es la gente, luego qué hace, luego qué
le decimos, luego los tres descubrimientos que justifican el producto, luego qué
hace nuestro sistema, y al final cómo leerlo todo sin equivocarse.

| # | `clave` | Bloque | Qué se aprende ahí | De dónde salen las cifras |
|---|---|---|---|---|
| 1 | `clientes` | **Quiénes son estas 38 000 personas** | Perfil, productos, situación financiera, día de pago. Casi 1 de cada 5 está en situación frágil: ese es el grupo al que el crédito le hace daño | `data/customers.parquet`, recalculado · `recon/06_nps_pattern.csv` |
| 2 | `comportamiento` | **Qué hacen dentro de la app, y qué hacen con su dinero** | Navegación y acciones, y el puente entre las dos: entrar al simulador multiplica por 30 la probabilidad de pedir un préstamo | `recon/03_event_composition.csv`, `02_action_type_dist.csv`, `03_screen_action_p24h.csv`, `03_screen_action_lift24h.csv`, `03_event_gap_histogram.csv` · el hueco de señal, desde `data/app_events.parquet` |
| 3 | `avisos` | **Los avisos que se mandan hoy, y en qué acaban** | 285 000 avisos con su resultado, el embudo M1–M5 y la gráfica que menos se espera: el aviso más clicado es el que menos convierte | `data/nudges.parquet` + `financial_actions.parquet` vía `analytics/metricas.py` · `recon/04_by_nudge_type.csv`, `04_by_surface.csv`, `04_global_rates.csv` |
| 4 | `fatiga` | **Lo que cuesta repetir el mismo mensaje** | Cada repetición parte el clic por la mitad y duplica las bajas. De aquí sale el tope de 2, derivado y no elegido | `data/nudges.parquet` vía `analytics/metricas.py` · `recon/04_fatigue_by_type.csv` |
| 5 | `momento` | **Hablar con señal o hablar sin ella: no es el mismo producto** | Solo el 1.46 % de los avisos cae con señal fresca, y ahí convierte 4.04× mejor. El día de pago casi no importa por sí mismo | `recon/04_moment_recency.csv`, `04_moment_x_fatigue.csv`, `07_payday_total.csv`, `07_payday_mediation.csv` |
| 6 | `objetivos` | **Clics, salud financiera e ingreso apuntan a sitios distintos** | Los tres criterios dan tres órdenes distintos del mismo catálogo. Y λ = 266 MXN por día en descubierto es el precio que revela el statu quo | `data/nudge_outcomes.parquet` vía `recon/05_*.csv` y `07_policy_simulation.csv` · `pipeline/artifacts/tabla_valor.json` |
| 7 | `sistema` | **Lo que decide nuestro sistema, y por qué se calla** | Cobertura por corte, reparto de ofertas y las razones del silencio, contadas | `pipeline/politica.py` + `app/panorama.py` sobre los 38 000 · `pipeline/artifacts/labels_intent.parquet` |
| 8 | `modelos` | **Qué tan bien predicen los modelos, y contra qué** | Acierto contra tres referencias, estabilidad entre cortes, AUC del modelo de momento y el barrido de umbrales | `analytics/evaluar.py` sobre `modelo_intencion.pkl` y `modelo_momento.pkl` · `umbrales.json`, `metadata.json` |
| 9 | `advertencias` | **Cómo leer todo esto sin equivocarse** | Qué comparaciones son limpias, cuáles no, y el inventario de columnas que nunca entran al modelo | `recon/06_randomization_tests.csv`, `06_selection_bias.csv`, `06_leakage_table.csv`, `01_integrity.csv`, `02_edge_effect.csv` |

Los 54 CSV de `analytics/recon/out/` **se leen, no se rehacen**: son conteos,
no estimaciones. Lo que sí se recalcula en cada construcción es lo que depende
del corte o del motor: el perfil de clientes, el embudo, la conversión a 7
días, la curva de fatiga, la cobertura de la política y la evaluación de los
modelos.

---

## Cómo se hizo entendible

Cuatro reglas, y las cuatro tienen una prueba que las vigila.

**1 · Cada gráfica dice qué muestra y qué hay que concluir.** No es un adorno:
es la diferencia entre una gráfica y un dibujo. Ninguna gráfica se publica sin
las dos frases, y las dos tienen que pasar de 40 caracteres —
`test_cada_grafica_dice_que_muestra_y_que_hay_que_concluir`.

**2 · Si una gráfica se puede leer mal, lo dice dentro.** Ocho gráficas llevan
un aviso obligatorio en amarillo, y la prueba
`test_las_graficas_que_se_pueden_leer_mal_lo_dicen_dentro` no deja que
desaparezca ninguno:

| Gráfica | Cómo se puede leer mal |
|---|---|
| Clic contra conversión | Las dos barras comparten denominador; la segunda no es «de los que clicaron» |
| Embudo M1–M5 | M1 se mide sobre clientes y M2–M5 sobre avisos: no se multiplican |
| El momento | La señal fresca no está aleatorizada; parte del efecto es de quién es esa persona |
| El día de pago | El rango es de 11.31 % a 12.90 %, no de 10.11 % a 41.63 %: comparar de reojo con la gráfica de arriba lleva a la conclusión contraria |
| Seis predictores | Dos barras se miden solo sobre el 16 % con señal fresca, que es el subconjunto fácil |
| Barrido de umbrales | El umbral se eligió en un corte que no participa en la evaluación |
| Salud por tipo de aviso | Son promedios sobre todos los avisos, no solo sobre los que recibieron clic |
| Curva de fatiga | Las dos series comparten escala y una es mucho más pequeña: hay que mirar la forma |

**3 · Ningún número aparece sin la referencia que lo hace significar algo.** Un
`AUC 0.7104` va con «0.50 sería tirar una moneda». Un acierto del 43.80 % va
con el 33.63 % de decir siempre lo más común. Una probabilidad del 20 % va con
la tasa base de esa acción. La prueba
`test_las_cifras_de_los_modelos_son_las_del_evaluador` comprueba que el
baseline sigue estando en el detalle.

**4 · Nada de jerga sin traducir.** Ocho términos en el glosario —aviso, señal,
clic, conversión a 7 días, frágil, λ, tasa base, corte— y los nombres internos
(`savings_move`, `home_card`, `S1_sin_senal`) se traducen antes de pintarse.

### Las gráficas

Cuatro tipos, todos en CSS o en `<svg>` en línea. **Nada externo**, ni una
librería, ni una fuente, ni un icono:

- **`barras`** — barras horizontales de CSS. La mayoría de las gráficas.
- **`barras_pareadas`** — dos barras finas por fila, para comparar dos medidas
  del mismo grupo (clic contra conversión, con señal contra sin señal).
- **`barras_divergentes`** — barras que salen de un **cero central**. Para las
  cifras con signo: una barra normal diría «magnitud» y dejaría el signo solo
  en el color, así que un dato malo y grande se leería igual que uno bueno y
  grande. El lado dice bueno o malo y el color lo confirma.
- **`curva`** — un `<svg viewBox="0 0 100 100" preserveAspectRatio="none">`
  **sin una sola letra dentro**: las etiquetas de los ejes van en HTML
  alrededor del dibujo, así el texto no se estira con el gráfico. Se usa una
  vez, para el cruce de la curva de fatiga.

Y `escalones`, que no es una gráfica: son las cinco métricas del embudo, cada
una en su unidad. Dibujarlas a la misma escala mentiría.

Todas llevan, además, un `<details>` con **los números en una tabla**: es a la
vez la alternativa textual visible y la forma de comprobar cualquier barra.

---

## Accesibilidad y ancho

- Cada lienzo es un `role="img"` con un `aria-label` que **dice los valores**,
  no solo el título. Generado siempre, no a mano
  (`test_cada_grafica_trae_alternativa_textual_con_sus_numeros`).
- **Claro y oscuro.** Los dos temas definen exactamente el mismo juego de
  variables CSS y ninguna regla vuelve a nombrar un color, así que no puede
  haber un color que solo exista en un tema
  (`test_los_dos_temas_definen_las_mismas_variables`). Por defecto se sigue la
  preferencia del sistema; el botón la sobreescribe y lo recuerda.
- **Sin scroll horizontal entre 320 y 2560 px.** `min-width:0` en todo, cada
  pista de grid es `minmax(0,…)`, ningún ancho fijo pasa de 320 px y **lo
  intrínsecamente ancho vive dentro de su propio `overflow-x:auto`**: las
  tablas de seis columnas se desplazan dentro de su caja, nunca arrastrando la
  página. Tres pruebas lo vigilan sobre el CSS, sin navegador.

Comprobado además con navegador a 320, 360, 375, 414, 480, 500, 768, 1024,
1200, 1440, 1920 y 2560 px: `scrollWidth == clientWidth` en todos, y los
únicos elementos que sobresalen de su contenedor son las `<table>`, que es
justamente lo que se pretende.

## Sin red

`test_la_pantalla_no_depende_de_la_red` rechaza `<link>`, `@import`, `srcset`,
`fetch(`, `import(`, `XMLHttpRequest`, `EventSource`, `WebSocket`, `//cdn`,
`url()` remoto, `@font-face` y cualquier `src`/`href` absoluto a otro host. La
tipografía es la del sistema. Los datos viajan **dentro** del HTML: no hay una
segunda petición que pueda fallar, y por eso la página no parpadea.

El único JavaScript de la página cambia el tema y lo recuerda. Sin él la página
funciona igual, con el tema del sistema.

## Formato de los números

Todo porcentaje viaja como `{"valor": 86.43, "texto": "86.43 %"}` vía
[`app/formato.py`](../app/formato.py), que es el único sitio del repo que decide
cuántos decimales lleva un porcentaje. Quien calcula usa `valor`; quien pinta
usa `texto`. Dos pruebas buscan **cualquier** token `12.3 %` con un número de
decimales distinto de dos, también dentro de las frases explicativas — que es
donde se cuelan.

Eso obligó a arreglar dos incoherencias reales que traían los CSV del
reconocimiento redondeados a un decimal:

- la cuota de avisos con señal fresca se publicaba como `1.50 %` en un sitio y
  `1.46 %` en otro; ahora se cuenta desde los `n` y sale `1.46 %` en los dos;
- las cuotas de la tabla de mediación del día de pago (`4.6 %` / `1.2 %`) se
  recalculan desde los conteos y salen `4.59 %` / `1.16 %`.

---

## Pruebas

```bash
.venv/bin/pytest -q analytics/tests/test_dashboard.py     # 32 pruebas, ~3 s
.venv/bin/pytest -q analytics/tests pipeline/tests        # la suite entera
```

Las 32 se reparten en cuatro familias:

1. **Que las cifras se pueden recalcular** (13 pruebas). Se vuelve a contar
   desde `data/*.parquet` una muestra representativa: una de cada tabla del
   dataset y el motor de decisión completo. El perfil de clientes, el reparto
   de acciones, la composición de eventos, el hueco de señal, los resultados de
   los avisos, el clic por tipo y por superficie, la conversión a 7 días
   reconstruida con su propio SQL, la curva de fatiga, el estado de señal con
   un `ASOF JOIN` contra `app_events`, las consecuencias a 90 días, la
   cobertura de las 8 puertas y el AUC del modelo de momento. La tolerancia es
   el propio redondeo publicado (0.01 en un porcentaje de dos decimales).
2. **Que no hay red** (4 pruebas), incluida una que comprueba que dos
   peticiones devuelven el mismo objeto ya calculado y que la segunda tarda
   menos de 2 s.
3. **Que los porcentajes se escriben igual en todas partes** (4 pruebas).
4. **Que la página no se puede leer mal** (11 pruebas): alternativas textuales,
   qué muestra y qué concluir, procedencia declarada por bloque, avisos
   obligatorios, glosario, los dos temas, las tres reglas de ancho, y que la
   portada no cite ninguna cifra que no esté en un bloque.

La última merece un párrafo: `test_la_portada_no_inventa_ninguna_cifra`
comprueba que cada número del encabezado esté **literalmente** en las cifras de
algún bloque. Es la trampa más fácil de un dashboard — un titular redondo que
no cuadra con la tabla de abajo — y ya cazó una: la portada decía «el que más
daña» donde el bloque decía «Aumento de línea».
