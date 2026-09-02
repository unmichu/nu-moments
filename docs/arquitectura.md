# Arquitectura

## Flujo end-to-end

```
data/*.parquet                    5 tablas sintéticas, 1,971,986 filas
        │
        ├── customers + app_events + nudges ──────► FEATURES  (ts < asof, ESTRICTO)
        │                                              │
        │                                              ▼
        │                          pipeline/features.py · features_asof_<corte>.parquet
        │                          customer_id + 82 features · 5 fotos en disco
        │                                              │
        ├── financial_actions ─────────────────────► LABEL     (asof < ts ≤ asof+7d)
        │                          y_primera · NUNCA es feature
        │                                              │
        │        ┌─────────────────────────────────────┤
        │        ▼                                     ▼
        │   MODELO X · Intención  (ML)          MODELO Y · Momento  (ML)
        │   HistGradientBoosting × 8            LogisticRegression, 2 variables
        │   ¿qué va a querer?                   entrena con nudges ASOF app_events
        │                                       ¿enganchará ahora?
        │
        └── nudges ⋈ nudge_outcomes ───────────► MODELO Z · Valor  (NO es ML)
                                                 tabla determinista por producto
                    │
                    ▼
        score = p_intencion × p_enganche × V(λ=266)
                    │
                    ▼
pipeline/politica.py   orden de evaluación S0 → S6 → S1 → S2 → S5 → S3 → S7 → S4
                       (S5 y S7 están implementadas pero NO activas en el piloto)
                    │
        ┌───────────┼───────────┬──────────────┐
        ▼           ▼           ▼              ▼
     OFERTA    SUSTITUCIÓN   SILENCIO    FUERA DE CATÁLOGO
     13.57 %                 86.43 %     código C0
        │           │           │              │
        └───────────┴─────┬─────┴──────────────┘
                          ▼
             app/  ·  botón + leyenda del porqué
```

Cobertura medida en el corte del demo (`2026-06-16`, `GET /health`): **13.57 %
de oferta y 86.43 % de silencio** sobre los 38,000 clientes. Sin la puerta S4
sería 14.63 % / 85.37 %; se publican las dos para no maquillar.

El detalle completo de cada modelo —tabla de entradas, SQL de las uniones,
hiperparámetros, evaluación con su baseline y quién consume la salida— está en
[`docs/modelos.md`](modelos.md).

## Los tres modelos

| Modelo | Pregunta | Entrada | Algoritmo | Resultado |
|---|---|---|---|---|
| **X · Intención** | ¿qué acción hará en 7 días? | **features:** `customers` + `app_events` + `nudges` · **label:** `financial_actions` | 8 cabezas binarias: `HistGradientBoostingClassifier(max_depth=4, random_state=0)` puntúa, `StandardScaler`+`LogisticRegression(max_iter=1000)` explica | top-1 **43.80 %** vs baseline **33.63 %** |
| **Y · Momento** | ¿enganchará este aviso? | **entrena:** `nudges` ASOF LEFT JOIN `app_events` · **sirve:** la foto as-of (`senal_*`, `exp_*`) | `StandardScaler`+`LogisticRegression(max_iter=1000)`, 2 variables | **AUC 0.7104**, precisión en el 1 % superior **32.60 %** vs base 8.27 % |
| **Z · Valor** | ¿cuánto aporta o daña? | `nudges` ⋈ `nudge_outcomes` ON `nudge_id`, WHERE `engaged` (`customers` **no** participa) | Tabla determinista — **no es aprendizaje automático**, no se entrena ni se valida | `V(ahorro,266)=+0.699` · `V(línea,266)=−0.077` |

**M0 · Fallback:** la regla de 24 h envuelta con la misma interfaz. Acierta
**62.46 % de media** donde hay señal (**63.45 %** en el corte principal
`2026-06-09`) y no entrena: son constantes medidas en `analytics/recon/out/`.
Cubre solo el ~16 % de los clientes activos.

### Los números de arriba: qué población mide cada uno

Reproducibles con `analytics/evaluar.py`. Se sustituyeron los valores heredados
por los medidos; donde no coinciden, manda la medición.

| Cifra | Población | Medido | Heredado |
|---|---|---|---|
| top-1 del modelo | clientes **activos** (con ≥1 acción en los 7 días), media de los 3 cortes rolling | **43.80 %** (rango 2.65 pp) | 43.75 % (2.61 pp) |
| baseline constante | misma población | **33.63 %** (rango 15.99 pp) | 33.63 % |
| regla de 24 h · donde hay señal | activos **con señal ≤24 h** (≈16 % de los activos) | **62.46 %** (rango 2.22 pp) | 63.45 % en d100 ✔ |
| regla de 24 h · híbrida | **todos** los activos (sin señal → clase constante) | **37.79 %** (rango **13.98 pp**) | — |
| AUC del momento | 47,432 avisos posteriores a 2026-06-09 | **0.7104** | 0.7107 |
| precisión 1 % superior | mismos avisos, empates incluidos | **32.60 %** vs base 8.27 % | 33.02 % |

**El rango de 7.17 pp de la regla no se reproduce y se retira.** Medido sobre la
población que le corresponde, la regla tiene 2.22 pp de rango *donde hay señal*
y 13.98 pp *sobre toda la base*. El argumento de estabilidad se refuerza: el
modelo mueve 2.65 pp entre cortes contra 13.98 pp de la regla híbrida, que es
una brecha mayor que la que se afirmaba.


### Por qué dos modelos y no uno

La intención dice *qué*, el momento dice *si ahora*. Son preguntas con distinta unidad de observación: la intención se predice por cliente y fecha; el momento, por aviso mostrado —y por eso se entrenan sobre tablas distintas, no sobre la misma matriz. Encadenarlas permite responder «sé lo que quieres, pero hoy no te lo voy a decir».

**El modelo X se entrena sobre un panel, no sobre un corte.** Son 12 cortes
semanales (`2026-03-04` → `2026-05-20`, 456,000 filas). Con un solo corte
`dias_a_payday` toma únicamente 3 valores y el modelo no puede aprender el
efecto de la quincena: el top-1 medio cae de 43.80 % a 38.45 % y el rango entre
cortes sube de 2.66 pp a 16.26 pp. `analytics/entrenar.py --v0` reproduce la
versión de un solo corte para poder compararlas.

## Orden temporal — cómo se garantiza y cómo se prueba

Todas las features se calculan con `event_ts < asof_ts` **estricto**. La garantía no es la intención, son las pruebas:

1. Ninguna feature usa eventos con `ts >= asof`.
2. Las columnas posteriores a la decisión no están en el conjunto de features (lista negra por nombre y por patrón).
3. **Prueba negativa:** se inyecta un evento en `asof + 1h` y ninguna feature se mueve.
4. Barajado temporal: el desempeño debe degradarse.

## Contratos

| Artefacto | Ruta | Produce | Consume |
|---|---|---|---|
| Tabla de features | `pipeline/artifacts/features_asof_<corte>.parquet` | analítica | modelos, scoring |
| Modelo de intención | `pipeline/artifacts/modelo_intencion.pkl` | analítica | backend |
| Modelo de momento | `pipeline/artifacts/modelo_momento.pkl` | analítica | backend |
| Umbrales | `pipeline/artifacts/umbrales.json` | analítica | política |
| Tabla de valor | `pipeline/artifacts/tabla_valor.json` | analítica | política |
| Plantillas de razones | `pipeline/artifacts/razones.json` | producto + analítica | backend |
| Metadatos | `pipeline/artifacts/metadata.json` | analítica | backend |
| Paquete de respaldo | `pipeline/artifacts/demo_pack.json` | analítica | backend, nivel 3 |
| Escenarios curados | `pipeline/artifacts/casos_ejemplo.json` | producto + analítica | backend, selector |
| Cifras del dashboard | `dashboard/datos.json` | `app/dashboard_datos.py` | `GET /dashboard`, `GET /api/dashboard` |

**`metadata.json` debe declarar el corte del demo.** Si no coincide, el backend cae al fallback y no avisa. La verificación es explícita: la respuesta del POST trae el campo `modelo`, y debe decir `v1`.

## API

Diez en total: dos páginas y ocho de datos. Ocho las define `app/main.py`; las
dos del dashboard llegan montadas desde `app/rutas_dashboard.py`.

| Endpoint | Devuelve |
|---|---|
| `GET /` | La pantalla (Jinja2 + Alpine, sin paso de compilación) |
| `GET /api/clientes` | Lista para el selector, con los escenarios curados al frente. Filtros: `q`, `corte`, `oferta`, `razon`, `limite` |
| `GET /api/clientes/{id}?asof=` | Ficha: perfil, movimientos, navegación reciente, historial de avisos |
| `GET /api/clientes/{id}/linea-tiempo?asof=&dias=` | Navegación y avisos en un mismo eje, con el corte marcado |
| `POST /api/decidir` | La decisión: ofertas con score **desarmado en sus tres factores**, los datos de **las cinco gráficas del «por qué»** y la razón, o silencio con su causa, más la traza de las 8 puertas |
| `GET /api/contexto` | Cortes disponibles con **su** cobertura, glosario, las 8 puertas en lenguaje llano, estados de la señal |
| `GET /api/explicacion?corte=` | La pestaña «Cómo funciona»: los tres modelos en su orden, las 8 puertas **con cuánta gente silencia cada una en ese corte**, la cadena hasta los cuatro resultados, el glosario ampliado y los 9 escenarios confrontados con lo que el panorama decide hoy |
| `GET /health` | Estado y versión de los artefactos cargados, más `cortes_features`, `coberturas_por_corte`, `panorama` y `dashboard_montado` / `dashboard_motivo` (si el router del dashboard no se pudo montar, el servicio arranca igual y aquí se lee por qué) |
| `GET /dashboard` | El dashboard general: los 9 bloques ya pintados en el servidor, sin una sola petición del navegador |
| `GET /api/dashboard` | Los mismos 9 bloques en JSON: `disponible`, `firma`, `cabecera`, `bloques[]` (`clave`, `titulo`, `graficas`, `procedencia`), `glosario` y `avisos` |

**La explicación viaja dentro del POST.** Dos razones: el clic en el botón es instantáneo, y es imposible que la leyenda diverja de la decisión que la produjo.

### Contrato de formato de porcentajes

Un solo formato en toda la superficie —API y pantalla—: **`XX.XX %`**, dos
decimales exactos y espacio antes del signo. Vive en un único sitio,
`app/formato.py`, y la pantalla lo replica en su helper `pct()`
(`Number(v).toFixed(2) + ' %'`), que `pipeline/tests/test_interfaz.py` verifica.

Cada porcentaje viaja **dos veces**: el número crudo y su texto ya formateado.

```
cobertura.pct_silencio        86.43        <- para calcular
cobertura.pct_silencio_texto  "86.43 %"    <- para pintar
```

Quien calcula usa el número; quien pinta usa el texto. Ninguno de los dos
redondea por su cuenta, que es como antes aparecían `86.43 %` y `14.0 %` en la
misma pantalla. `None` se escribe `—`, nunca `0.00 %`: «no lo sé» y «es cero» no
son lo mismo.

La regla alcanza también al texto en prosa que la pantalla muestra (razones,
motivos de fragilidad, narrativas de los escenarios curados). Se exceptúan los
**umbrales de la política** citados en prosa —`por encima del 70 %`, el cupo de
2— porque son constantes de diseño, no cifras medidas.

### El score, desarmado

`POST /api/decidir` publica en cada oferta un bloque `explicacion` con los **tres
factores por separado y en sus unidades naturales**, más la referencia con la
que se leen:

```
ofertas[].explicacion
  factores[0]  p_intencion   porcentaje   "38.69 %"       referencia: tasa base observada, ×, percentil
  factores[1]  p_enganche    porcentaje   "38.71 %"       referencia: tasa base de enganche, ×
  factores[2]  valor (V)     días         "+0.6993 días"
  resultado    score         días         "+0.1047 días"  referencia: percentil · formula
```

La **tasa base** es un conteo, no una estimación: sale de `labels_intent.parquet`
(fracción de los 38,000 que de verdad hizo esa acción en la ventana de 7 días de
ese corte). El **percentil** es la posición real dentro de la distribución
completa de `p_intencion` —y de `score`— sobre los 38,000 al mismo corte, y viaja
con **los dos conteos que lo respaldan** (`n_total`, `n_encima`): «percentil
99.52 %» y «180 de 38 000 tienen un score más alto» son la misma frase, pero la
segunda se puede comprobar contando.

Los dos conteos se cuentan contra el valor **exacto** del cliente en la
población, no contra el que se publica redondeado: `p_intencion` sale a 4
decimales y el `score` a 6, y con el redondeado el propio cliente quedaba por
encima de sí mismo y sumaba uno de más (623 donde hay 622). `VistaCorte` guarda
los valores sin ordenar alineados con `idx` y resuelve el del cliente por su id;
si el número publicado y el de la población no son la misma cifra —la vista se
construye a las 12:00 del corte y una petición puede pedir otra hora, con otro
estado de señal y otro `p_enganche`— se cuenta contra el publicado, que es el
que se enseña.

### El «por qué», con gráficas · `ofertas[].explicacion.graficas`

Cada oferta trae, dentro del mismo POST, los datos ya listos para dibujar cinco
vistas de la población. Todo sale del panorama y de la ficha; ni un número se
calcula en el navegador y ninguno se estima.

```
ofertas[].explicacion.graficas
  poblacion      segmentos[]      el reparto de los 38 000 por tipo de oferta y silencio,
                                  con `es_del_cliente` en el suyo · `silencio_por_razon[]`
  distribucion   histograma       22 cubos en escala log10 de `p_intencion` de ese producto,
                                  `bin_cliente`, y `marcas[]` = mediana, tasa base y cliente
                                  · `percentil`, `n_encima`, `n_total`
  contra_base    barras[]         p_intencion y p_enganche: valor del cliente, tasa base,
                                  ancho de cada barra en la escala común y el múltiplo (`veces`)
  recencia       zonas[]          fresca ≤24 h, tibia ≤168 h, fría después —los umbrales de
                                  `pipeline/politica.py`— y `pos_pct` de la señal del cliente
  cupo           casillas[]       exposiciones usadas frente al cap de 2
                 curva[]          enganche y bajas por número de exposición, contados sobre
                                  `nudges` con `shown_ts < asof`, con `es_del_cliente` en la
                                  exposición que tocaría
```

Cada bloque trae además `alternativa`: la misma lectura escrita en una frase, que
es lo que anuncia el `aria-label` de la gráfica a un lector de pantalla. Los
porcentajes siguen la regla de dos decimales.

**El eje del histograma es logarítmico** y eso es una decisión, no un adorno: en
`savings_goal` la mediana de `p_intencion` es 3.19 % y el máximo 87.54 %, así que
con cubos de ancho constante el 97 % de los 38,000 cae en el primero y el dibujo
no dice nada.

Si el corte no tiene vista poblacional, `graficas` viaja como `null` y
`motivo_sin_comparacion` dice por qué. No se dibuja un eje inventado.

### Porcentajes

Todo porcentaje viaja **dos veces**: el número (`pct_silencio: 86.43`) y el texto
con exactamente dos decimales (`pct_silencio_texto: "86.43 %"`). Quien calcula usa
el número, quien pinta usa el texto; ninguno redondea por su cuenta. La regla vive
en `app/formato.py` y la comprueba `pipeline/tests/test_interfaz.py`.

### El panorama · `app/panorama.py`

Vista poblacional **por corte**, montada en el `lifespan`. Por cada uno de los 5
cortes con foto de features calcula, sobre los 38,000 clientes de una sola pasada:

* la cobertura (`politica.cobertura`) — **cambia con el corte**: 83.96 %, 87.89 %,
  87.91 %, 89.26 % y 86.43 % de silencio;
* la tasa base observada de cada acción y la de enganche por tipo de aviso;
* la distribución completa de `p_intencion` y de `score`, para el percentil, los
  dos conteos que lo respaldan y el histograma en escala log10;
* la **curva de fatiga** de ese corte: enganche y bajas por número de exposición,
  contados con corte estricto `shown_ts < asof` y solo con las exposiciones que
  tienen al menos 200 avisos (por encima de la sexta quedan decenas de casos y la
  tasa sería ruido);
* qué ofrecería el sistema a **cada** cliente y, si se calla, por qué puerta.

Lo último es lo que resuelve el filtro del selector. Se apoya en
`politica.evaluar_masivo()`, que ahora devuelve además `por_producto` con el
`momento`, las exposiciones y **la primera puerta que cierra**, en el mismo orden
de evaluación que `decide()`. La equivalencia no se supone: `test_interfaz.py`
vuelve a decidir cliente a cliente y compara.

Si a un corte le falta un insumo, la vista se declara caída con el motivo escrito
y `/health` lo publica en `panorama.cortes_caidos`. Nunca se sustituye por la de
otro día.

### La pestaña «Cómo funciona» · `app/explicacion.py`

La segunda pestaña de la pantalla. Está escrita para alguien que no ha visto
nunca el dataset —un directivo, negocio— y por eso define cada término donde
aparece en vez de suponerlo.

El módulo tiene una sola regla, la misma que el resto del servicio: **el texto
vive en el código, los números se calculan.** Ni una cifra está escrita en la
plantilla, y hay una prueba que lo comprueba comparando el HTML contra la
respuesta de la API (`test_ni_una_cifra_de_la_pestana_esta_escrita_en_la_plantilla`).

| Bloque | De dónde salen sus números |
|---|---|
| Los tres modelos y el respaldo | `metadata.json` (`n_features`, `acciones`), `tabla_valor.json` (la `V` de cada producto), `escalera.lmbda` y `escalera.nivel_activo` |
| Las 8 puertas + el fuera de catálogo | `panorama.de(corte).conteo_por_razon()` — las mismas puertas corridas sobre los 38,000 |
| Los 4 resultados | `conteo_por_oferta()` y, para la sustitución, `politica.evaluar_masivo()` con la definición literal de `armar_respuesta` (producto vetado por S3 **y** candidato sano disponible) |
| El glosario | `razones.glosario()` **reutilizado tal cual** + los términos que allí se daban por sabidos. Si una clave existe en los dos, manda la de la pantalla de decisión |
| Los 9 ejemplos | `casos_ejemplo.json` confrontado con lo que `panorama.de(caso.corte)` decide hoy; el desacuerdo se publica en `coincide_con_el_guion` en vez de esconderse |

**El conteo por puerta suma exactamente el silencio del corte.** Una persona
puede estar cerrada por varias puertas a la vez; el conteo asigna cada silencio a
una sola —la de mayor prioridad de reporte, la misma que se le explica al
cliente—, y la pantalla dice ese matiz en vez de dejar que se suponga.

`C0_fuera_de_catalogo` va aparte de las ocho: cierra productos, no personas.
Contarlo como puerta inflaría el silencio con 38,000 × 2 cierres que no son
decisiones sobre nadie.

Se arma en el `lifespan` para el corte del demo y se cachea por corte con tope,
igual que las coberturas.

### Las tres pestañas

`Decisión` (todo lo que ya había), `Cómo funciona` y `Panorama`. Las dos primeras
son un `tablist` real: `role="tab"`/`role="tabpanel"`, `aria-selected`, `tabindex`
itinerante y recorrido con flechas, Inicio y Fin. La activa se distingue por la
raya inferior y el peso de la letra, **no solo por el color**.

`Panorama` apunta a `/dashboard`, que es otra página, así que es un enlace normal
y vive **fuera** del `tablist`: un `role="tab"` que navega a otra URL mentiría a
quien use lector de pantalla.

## Robustez

Los modelos se cargan **al arranque**, no por petición. Escalera de tres niveles:

1. Modelo entrenado — puntúa con la foto as-of **del corte que pide la petición**:
   el corte exacto si existe y, si no, el más reciente anterior o igual al `asof`.
   Nunca uno posterior; si no hay ninguno válido, el nivel se declara caído para
   esa petición y `/health` publica el motivo en `escalera.descensos_en_peticion`.
2. Regla de 24 h
3. Paquete precalculado — `demo_pack.json`, indexado por la pareja
   `(customer_id, asof)`, para que el fallback devuelva los mismos números que el
   nivel 1 en el corte en que cada caso se decide.

Se puede bajar de nivel **a propósito y sin tocar artefactos** con
`NU_MOMENTS_NIVEL_MAX` (`v1` · `regla_24h` · `demo_pack`): apaga los niveles por
encima del que se nombra y lo deja escrito en `/health`.

Cualquier excepción devuelve **silencio con HTTP 200**: el modo degradado es coherente con la tesis del producto en lugar de verse como un error.

## Decisiones de stack

Un proceso, un puerto, sin paso de compilación. Medido en la máquina de desarrollo (8 arranques, 60 peticiones cada uno, `TestClient` en proceso, medianas): **2.2 s de arranque, 28 ms por `POST /api/decidir`**, con los datos en memoria y la ficha resolviéndose en 15 ms.
Remedido con el panorama ya montado (3 arranques y 60 peticiones por ruta, `TestClient` en proceso): **arranque instrumentado 3.85 s** (`/health → arranque_s`, rango 3.83–3.85; 4.4 s contando el import de Python), **POST /api/decidir p50 29.7 ms**, **ficha p50 16.2 ms**, línea de tiempo p50 4.1 ms y `/api/contexto` p50 48.3 ms.

Esos 3.85 s son **anteriores al dashboard**. Con `app/rutas_dashboard.py` montado —que lee `dashboard/datos.json` al importarse— el arranque real bajo uvicorn es **4.21–4.45 s** (`/health → arranque_s`, 3 arranques, 2026-09-02). Es la cifra que ve quien levanta la demo; `docs/modelos.md` cita la misma.

El arranque paga por adelantado lo que la petición no vuelve a pagar: los cinco parquets de `data/`, los `.pkl`, **las cinco fotos as-of de features** (una por corte, para poder puntuar cualquier `asof` sin usar una posterior) y el contador de cobertura sobre los 38,000 clientes. Los rangos observados fueron 1.94–2.37 s de arranque, 26–31 ms por POST y 14–17 ms por ficha; se citan las medianas.

Con el panorama el arranque sube a **3.85 s medidos** (~4.4 s con el import): son ~1.5 s más para calcular, por
cada uno de los 5 cortes, la cobertura, la matriz de `p_intencion` de los 38,000
y la decisión vectorizada. Es la única forma de que el selector de corte, el
percentil y el filtro por tipo de oferta no toquen el disco ni un modelo en el
camino de la petición. Las coberturas por `asof` se cachean con tope
(`MAX_COBERTURAS_CACHEADAS`), cebadas con los 5 cortes y los 9 escenarios, para
que un `asof` arbitrario no haga crecer la memoria.

El demo **nunca depende de la red**. Cualquier consulta remota queda para el trabajo por lotes y el dashboard, jamás en el camino del pitch.
