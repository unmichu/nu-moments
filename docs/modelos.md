# Los modelos, en detalle

Versión escrita de los diagramas **4 · El modelo de datos y sus uniones** y
**5 · Qué modelo se usó para cada cosa** del board de Miro.

Todo lo que sigue está leído del código (`pipeline/features.py`,
`analytics/entrenar.py`, `analytics/evaluar.py`, `app/scoring.py`,
`pipeline/politica.py`), de los artefactos de `pipeline/artifacts/` o medido
sobre `data/`. Los números de desempeño son la salida literal de:

```bash
.venv/bin/python analytics/evaluar.py
```

---

## 0 · Resumen: qué es y qué no es aprendizaje automático

| | Pregunta | ¿Es ML? | Algoritmo | Alimenta |
|---|---|---|---|---|
| **X · Intención** | ¿qué acción financiera hará en 7 días? | **Sí** | `HistGradientBoostingClassifier(max_depth=4, random_state=0)` × 8 cabezas | el factor `p_intencion` y el ranking entre los 4 productos |
| **Y · Momento** | ¿enganchará si le hablamos ahora? | **Sí** | `StandardScaler` + `LogisticRegression(max_iter=1000)`, 2 variables | el factor `p_enganche` y la confianza de S7 (no activa) |
| **Z · Valor** | ¿cuánto aporta o cuánto daña? | **No** | media aritmética de 3 deltas, fórmula cerrada | el factor `V` y la puerta S4 |
| **M0 · Regla 24 h** | ¿y si los `.pkl` no cargan? | **No** | constantes medidas de `analytics/recon/out/` | el nivel 2 de la escalera de fallback |

`Z` no se entrena, no se valida y no tiene conjunto de test: se **recalcula**.
Presentarla como modelo sería engañoso. Lo mismo para `M0`.

El score que ordena todo es un producto de los tres:

```
score = p_intencion × p_enganche × V(λ)      λ = 266 MXN por día en descubierto
```

---

## 1 · Las cinco tablas y cómo se unen

### 1.1 Grano y cardinalidad (medido sobre `data/`)

| Tabla | Filas | Clave | Cardinalidad |
|---|---|---|---|
| `customers` | 38,000 | `customer_id` (PK) | 1 fila por cliente |
| `app_events` | 797,304 | `event_id` (PK), `customer_id` (FK) | 1 → N · los 38,000 tienen eventos |
| `financial_actions` | 566,682 | `action_id` (PK), `customer_id` (FK) | 1 → N · los 38,000 tienen acciones |
| `nudges` | 285,000 | `nudge_id` (PK), `customer_id` (FK) | 1 → N · **37,911** de 38,000 tienen aviso |
| `nudge_outcomes` | 285,000 | `nudge_id` (PK y FK) | **1 a 1** con `nudges`, sin huérfanos |

Rango temporal de las tres tablas de evento: `2026-03-01` a `2026-06-28`.

### 1.2 Dónde se aplica el corte temporal

Hay **dos lados** del corte y ninguna columna cruza de un lado al otro:

| Lado | Tablas | Condición | Alimenta |
|---|---|---|---|
| **Pasado** | `app_events`, `nudges`, `customers` | `event_ts < asof`, `shown_ts < asof` — **estricto**, nunca `<=` | las **82 features** |
| **Futuro** | `financial_actions` | `action_ts > asof AND action_ts <= asof + 7 días` | el **label** `y_primera` |

Por eso ninguna feature puede mirar hacia adelante: la ventana del label empieza
exactamente donde termina la ventana de las features, y el `<` estricto impide
que un evento con `event_ts == asof` entre en las dos.

La afirmación no es una intención, está probada:

- `pipeline/tests/test_leakage.py` — control negativo (evento en `asof + 1h`: ninguna feature se mueve) y control positivo (el mismo evento en `asof − 1h`: sí se mueve).
- `analytics/tests/test_fuga.py` — la afirmación sobre el SQL del módulo.
- `pipeline/tests/test_fuga_en_servicio.py` — la extiende al servicio: la foto as-of que puntúa una petición nunca es posterior a su `asof`.

Además hay una lista negra por patrón que se comprueba **en cada build** de la
matriz (`PATRONES_PROHIBIDOS` en `pipeline/features.py`): `customer_id`,
`engagement_score`, `abandon`, `engaged`, `dismissed`, `opted_out`, `delta_`,
`_90d`, `hours_since_last_nudge`, `hour`, `dow`, `nps`. Si una entra, el build
falla con `AssertionError`.

### 1.3 Columnas de `customers` que **no** son features

`card_utilization_pct` y `days_negative_90d` sí se leen, pero **solo** en la
puerta S3 (fragilidad) de `pipeline/politica.py`, nunca en la matriz. El motivo
está en el docstring de `analytics/evaluar.py`: `_90d` declara una ventana de 90
días sin fecha de corte, que dentro de estos 120 días de datos solapa cualquier
`asof`; y `card_utilization_pct`, `avg_balance_mxn` y `revenue_ltm_mxn` son
*snapshots* sin vintage declarado, así que no se pueden reconstruir as-of.

De `customers` entran a la matriz **solo 6 columnas**: los 5 flags `has_*` y
`payday_day_of_month` (transformada en `dias_a_payday`).

Reparto exacto de las 82 features por tabla de origen (recontado sobre el parquet):

| Tabla de origen | Columnas |
|---|---|
| `app_events` | **71** — `rec_h_*` 10, `n24_*` 10, `n72_*` 10, `s24_*` 10, `s72_*` 10, `senal_*` 8 (derivadas de `rec_h_*`), `ratio_start_*` 8, y 5 agregados |
| `customers` | **6** — `has_*` 5 + `dias_a_payday` |
| `nudges` | **5** — `exp_*` 4 + `n_exposiciones_total` |
| **total** | **82** |

---

## 2 · Modelo X · Intención

### 2.1 Tabla de entradas

| Rol | Tabla | Columnas | Bloque de features |
|---|---|---|---|
| base | `customers` | `customer_id` | el índice: siempre 38,000 filas |
| feature | `customers` | `has_cuenta_nu`, `has_cajita_turbo`, `has_personal_loan`, `has_investments`, `has_payroll_portability` | `has_*` (5) |
| feature | `customers` | `payday_day_of_month` | `dias_a_payday` (1) |
| feature | `app_events` | `event_ts`, `screen`, `action` | `rec_h_*` (10), `n24_*` (10), `n72_*` (10), `s24_*` (10), `s72_*` (10), `senal_*` (8), `ratio_start_*` (8), 5 de los 6 agregados |
| feature | `nudges` | `shown_ts`, `nudge_type` | `exp_*` (4) + `n_exposiciones_total` (1 de los 6 agregados) |
| **label** | `financial_actions` | `action_ts`, `action_type` | `y_primera`, `y_<accion>` × 8, `activo` |

**82 features exactas**, verificadas contra el parquet:

| Bloque | Columnas | Origen |
|---|---|---|
| `rec_h_<pantalla>` | 10 | horas desde la última vista de cada pantalla |
| `n24_<pantalla>` | 10 | eventos en 24 h por pantalla |
| `n72_<pantalla>` | 10 | eventos en 72 h por pantalla |
| `s24_<pantalla>` | 10 | eventos `action='start'` en 24 h por pantalla |
| `s72_<pantalla>` | 10 | eventos `action='start'` en 72 h por pantalla |
| `senal_<accion>` | 8 | estado ordinal 0 `on_time` / 1 `warm` / 2 `cold` / 3 `never` |
| `ratio_start_<pantalla>` | 8 | `start / view` histórico en las 8 pantallas acopladas |
| `has_*` | 5 | tenencia de producto |
| `exp_<producto>` | 4 | exposiciones previas por producto del catálogo |
| `dias_a_payday` | 1 | `(payday_day_of_month − día del asof) mod 30` |
| agregados | 6 | `n_exposiciones_total`, `n_eventos_24h`, `n_eventos_72h`, `n_eventos_7d`, `pantallas_distintas_7d`, `horas_desde_ultimo_evento` |
| **total** | **82** | |

`rec_h_*` sin visita histórica vale `1e6`, no `0`: un `0` significaría "acaba de
verlo". Ninguna columna admite nulos — `_verificar()` lo comprueba.

### 2.2 Las uniones, con SQL

Ninguna unión usa `USING`: duplicaría la clave y metería `customer_id_2` en la
matriz. Todas son `ON` explícito, o `GROUP BY` + pivote + `reindex` sobre el
índice de `customers`, que es la forma que garantiza que no se pierden filas.

**Navegación por pantalla** (`pipeline/features.py::construir`):

```sql
SELECT e.customer_id, e.screen,
       date_diff('second', max(e.event_ts), TIMESTAMP '<asof>') / 3600.0 AS rec_h,
       count(*) FILTER (WHERE e.event_ts >= TIMESTAMP '<asof>' - INTERVAL 24 HOUR) AS n24,
       count(*) FILTER (WHERE e.event_ts >= TIMESTAMP '<asof>' - INTERVAL 72 HOUR) AS n72,
       count(*) FILTER (WHERE e.action = 'start'
                          AND e.event_ts >= TIMESTAMP '<asof>' - INTERVAL 24 HOUR) AS s24,
       count(*) FILTER (WHERE e.action = 'start'
                          AND e.event_ts >= TIMESTAMP '<asof>' - INTERVAL 72 HOUR) AS s72,
       count(*) FILTER (WHERE e.action = 'start') AS n_start_hist,
       count(*) FILTER (WHERE e.action = 'view')  AS n_view_hist
FROM app_events e
WHERE e.event_ts < TIMESTAMP '<asof>'      -- ← el corte, ESTRICTO
GROUP BY e.customer_id, e.screen
```

Luego se pivota por `screen` y se hace `.reindex(df.index)` contra el índice de
`customers`: es un **LEFT JOIN por reindexación**, sentido `customers ← app_events`.
Los clientes sin eventos en una pantalla quedan con `rec_h = 1e6` y contadores 0.

**Exposición previa por producto:**

```sql
SELECT n.customer_id, n.nudge_type, count(*) AS n
FROM nudges n
WHERE n.shown_ts < TIMESTAMP '<asof>'      -- ← el corte, ESTRICTO
GROUP BY n.customer_id, n.nudge_type
```

Pivote por `nudge_type` + `reindex` → `exp_<producto>` para los 4 del catálogo,
y la suma de todas las columnas → `n_exposiciones_total`.

**Agregados de navegación:** mismo `WHERE e.event_ts < asof`, `GROUP BY e.customer_id`.

**El label** (`pipeline/features.py::labels_intencion`):

```sql
SELECT f.customer_id, f.action_type,
       min(f.action_ts) AS primera_ts, count(*) AS n
FROM financial_actions f
WHERE f.action_ts >  TIMESTAMP '<asof>'                  -- ← el otro lado del corte
  AND f.action_ts <= TIMESTAMP '<asof>' + INTERVAL 7 DAY
GROUP BY f.customer_id, f.action_type
```

`y_primera` = el `action_type` con el `primera_ts` mínimo del cliente.
`activo` = 1 si el cliente hizo alguna acción en la ventana; es el universo
sobre el que se mide la exactitud contra el baseline.

La ventana se valida en `_ventana_valida()`: se descartan los **3 primeros días**
(el primer día trae 7.36× la mediana de acciones) y los **3 últimos** (censura).

### 2.3 Algoritmo e hiperparámetros

```python
# el que puntúa — una instancia por cada una de las 8 acciones
HistGradientBoostingClassifier(max_depth=4, random_state=0)   # class_weight: None

# el que explica — una instancia por acción
make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
```

Todo lo demás son los valores por defecto de scikit-learn 1.9.0.

Decisiones registradas en el docstring de `analytics/entrenar.py`:

- **Sin `class_weight='balanced'`**: cuesta 10.07 pp.
- **`StandardScaler` obligatorio** antes de la regresión, o no converge.
- El label de cada cabeza es `y_primera == accion`, no `y_<accion>`: es lo que mide el top-1.

### 2.4 Diseño temporal del entrenamiento — **cambió respecto al diseño original**

El diseño hablaba de un solo corte (`d100`). Lo construido es un **panel**:

| Fase | Cortes |
|---|---|
| entrenamiento | 12 cortes semanales, `2026-03-04` → `2026-05-20` (`freq=7D`) |
| umbrales | `2026-05-23` |
| test (rolling) | `2026-05-30` · `2026-06-09` · `2026-06-14` |
| demo | `2026-06-16` |

456,000 filas de entrenamiento = 38,000 clientes × 12 cortes.

**Sin fuga:** las ventanas de label del panel terminan el `2026-05-27`, antes
del primer corte de test (`2026-05-30`).

El motivo del panel está escrito en el código: entrenando en un solo corte
`dias_a_payday` toma solo 3 valores (el día del mes es constante) y el modelo no
puede aprender el efecto de la quincena. Con el panel el top-1 medio pasa de
**38.45 % a 43.80 %** y el rango entre cortes de **16.26 pp a 2.66 pp**.

`analytics/entrenar.py --v0` reproduce la versión de un solo corte con los
mismos nombres de archivo, para poder comparar.

### 2.5 Evaluación contra **tres** baselines

Salida literal de `analytics/evaluar.py`:

```
     corte  activos  pct_con_senal  baseline_constante  regla_hibrida  modelo_top1  modelo_top2  regla_donde_senal  modelo_donde_senal  modelo_decil_superior
2026-05-30    24268           16.3               25.63          30.74        44.04        67.67              61.23               61.99                  66.85
2026-06-09    18606           16.1               41.62          44.72        45.01        63.23              63.45               64.92                  71.91
2026-06-14    20701           16.3               33.64          37.91        42.36        63.37              62.71               63.04                  66.52
```

| Métrica | Media de los 3 cortes | Rango |
|---|---|---|
| `baseline_constante` (M0a, clase `spei_out`) | **33.63 %** | 15.99 pp |
| `regla_hibrida` (M0b sobre toda la base) | **37.79 %** | 13.98 pp |
| `modelo_top1` (M1) | **43.80 %** | **2.65 pp** |
| `modelo_top2` | **64.76 %** | 4.44 pp |
| `regla_donde_senal` (solo el ~16 % con señal ≤24 h) | **62.46 %** | 2.22 pp |
| `modelo_donde_senal` (mismo subconjunto) | **63.32 %** | 2.93 pp |

**Lo honesto va primero:** en el corte principal (`2026-06-09`) el árbol
**empata** con la regla donde hay señal — regla 63.45 %, árbol 64.92 %. La
ganancia no es exactitud, es **estabilidad**: 2.65 pp de rango contra 13.98 pp
de la regla híbrida, y la regla solo cubre ~16 % de los activos.

### 2.6 Acuerdo árbol / regresión — **el número del diseño era otro**

```
     corte  acuerdo_total_pct  acuerdo_activos_pct
2026-05-30              80.69                75.98
2026-06-09              94.07                93.35
2026-06-14              80.44                76.85
2026-06-16              62.76                59.51
```

En el corte del demo (`2026-06-16`) el acuerdo es **62.76 %**, no el ~89 % que
suponía el diseño. Cuando no coinciden, la explicación cae a la regla de
recencia y la respuesta lleva marca (`razones.json → origen.regla`).

### 2.7 Quién consume su salida

`app/scoring.py::ModeloEntrenado.scores` → `p_intencion` por producto →
factor del `score` → `pipeline/politica.py` (ranking de candidatos y puerta S7).

---

## 3 · Modelo Y · Momento

### 3.1 Tabla de entradas

| Rol | Tabla | Columnas |
|---|---|---|
| grano | `nudges` | `nudge_id`, `customer_id`, `shown_ts`, `nudge_type`, `exposure_no` |
| **label** | `nudges` | `engaged` |
| variable `senal` | `app_events` | `event_ts`, `screen` (vía ASOF join) |

Son **2 variables**, no más: `senal` y `exposure_no`.

### 3.2 La unión: un ASOF LEFT JOIN

`pipeline/features.py::labels_momento`. Cada aviso se empareja con el **último
evento anterior** en la pantalla acoplada de su producto:

```sql
-- clave sintética cliente|pantalla, para que el ASOF join sea de una sola columna
CREATE TEMP TABLE ek AS
SELECT customer_id::VARCHAR || '|' || screen AS k, event_ts FROM app_events;

CREATE TEMP TABLE nn AS
SELECT n.nudge_id, n.customer_id, n.nudge_type, n.exposure_no,
       n.engaged, n.shown_ts,
       n.customer_id::VARCHAR || '|' || m.want_screen AS k
FROM nudges n JOIN nmap m ON m.nudge_type = n.nudge_type;   -- ON explícito

SELECT nn.nudge_id, nn.customer_id, nn.nudge_type, nn.exposure_no, nn.shown_ts,
       CAST(nn.engaged AS INT) AS y_engaged,
       coalesce(date_diff('second', ek.event_ts, nn.shown_ts) / 3600.0, 1e6) AS gap_h
FROM nn ASOF LEFT JOIN ek
  ON nn.k = ek.k AND ek.event_ts < nn.shown_ts;             -- ← corte ESTRICTO
```

`nmap` es el mapa `nudge_type → pantalla` de `pipeline/mapas.py`, más
`payroll_portability → home`. El `LEFT` garantiza que los 285,000 avisos
sobreviven; los que no tienen evento previo reciben `gap_h = 1e6`.

`gap_h` se discretiza con los umbrales de `mapas.py`
(`UMBRAL_ON_TIME_H = 24`, `UMBRAL_WARM_H = 168`):

| `senal` | Condición |
|---|---|
| 0 `on_time` | `gap_h <= 24` |
| 1 `warm` | `24 < gap_h <= 168` |
| 2 `cold` | `168 < gap_h < 1e5` |
| 3 `never` | `gap_h >= 1e5` (sin evento previo) |

Ni `senal` ni `exposure_no` miran al futuro: los dos están definidos en el
instante `shown_ts`.

### 3.3 Algoritmo, hiperparámetros y split

```python
make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
```

Split **out-of-time** en `CORTE_MODELO = 2026-06-09`:

- entrenamiento: `shown_ts <= 2026-06-09` → **237,568** avisos
- test: `shown_ts > 2026-06-09` → **47,432** avisos

Coeficientes escalados medidos: `senal −0.3373`, `exposure_no −0.6994`.
Los dos negativos, y es lo esperado: señal más fría y más exposiciones bajan el
enganche.

**El árbol se probó y se descartó:** aporta `+0.0011` de AUC.

### 3.4 Evaluación

| Métrica | Medido | Objetivo declarado en el código |
|---|---|---|
| AUC | **0.7104** | 0.7107 |
| precisión en el 1 % superior (n=1,006, empates incluidos) | **32.60 %** | 33.02 % |
| tasa base | **8.27 %** | 8.27 % |

Lift sobre la base: 32.60 / 8.27 = **3.94×**.

Los objetivos de 0.7107 y 33.02 % vienen del diseño y **no se reproducen
exactamente**; manda la medición.

### 3.5 Quién consume su salida

`app/scoring.py::ModeloEntrenado._p_enganche` reconstruye
`DataFrame([[senal, exposure_no]])` desde la ficha y llama al `pipeline`.
La salida `p_enganche` es el segundo factor del `score` y, multiplicada por
`p_intencion`, es la `confianza` que lee la puerta S7 (implementada, **no activa**).

---

## 4 · Modelo Z · Valor — **no es aprendizaje automático**

### 4.1 Tabla de entradas

| Tabla | Columnas |
|---|---|
| `nudges` | `nudge_id`, `nudge_type`, `engaged` |
| `nudge_outcomes` | `delta_days_negative_90d`, `delta_revenue_mxn_90d`, `delta_savings_rate_pct_90d` |

`customers` **no participa** (a diferencia de lo que decía el diseño).

### 4.2 La unión

```sql
SELECT n.nudge_type AS producto, count(*) AS n,
       avg(o.delta_days_negative_90d)    AS d_dias_neg,
       avg(o.delta_revenue_mxn_90d)      AS d_ingreso,
       avg(o.delta_savings_rate_pct_90d) AS d_ahorro_pp
FROM nudges n
JOIN nudge_outcomes o ON o.nudge_id = n.nudge_id     -- INNER, 1 a 1
WHERE n.engaged                                       -- ← solo los que engancharon
GROUP BY n.nudge_type
```

El `WHERE n.engaged` es deliberado: el efecto de un aviso ignorado es 0 por
construcción del generador. Enganches por producto: `limit_increase` 8,975 ·
`payroll_portability` 6,563 · `bill_reminder` 5,373 · `savings_goal` 4,269 ·
`loan_offer` 4,068 · `invest_start` 3,396.

### 4.3 La fórmula

```
V(producto, λ) = (−Δdías_negativos) + (Δingreso / λ) + 0.3 · (Δahorro_pp / 10)
```

| Parámetro | Valor | Dónde |
|---|---|---|
| `λ` por defecto | **266.0** MXN por día en descubierto | `mapas.LAMBDA_DEFECTO` |
| `λ` alternativa (tabulada, no la que corre) | 165.0 | `entrenar.LAMBDA_ALT` |
| peso del ahorro | 0.3 | `mapas.PESO_AHORRO` |
| escala del ahorro | 10.0 (pp/10) | `entrenar.ESCALA_AHORRO` |

Unidad del resultado: **días de descubierto evitados por enganche**.

No hay ajuste, ni conjunto de validación, ni test: cambiar `λ` recalcula la
tabla entera. `app/scoring.py::_normalizar_tabla_valor` recalcula `V` con la
propia fórmula del artefacto si el `λ` pedido no está tabulado, en vez de caer a
un valor por defecto.

### 4.4 Resultado medido

| Producto | Δdías neg. | Δingreso MXN | Δahorro pp | **V(λ=266)** | V(λ=165) | En catálogo |
|---|---|---|---|---|---|---|
| `loan_offer` | −0.0082 | 260.372 | −2.2046 | **+0.9209** | +1.5201 | sí |
| `savings_goal` | −0.4635 | 11.843 | +6.3765 | **+0.6993** | +0.7266 | sí |
| `bill_reminder` | −0.8469 | −73.502 | +0.0021 | **+0.5707** | +0.4015 | sí |
| `invest_start` | −0.0011 | 95.600 | −0.0318 | +0.3596 | +0.5796 | no |
| `payroll_portability` | −0.0013 | 40.125 | +3.1121 | +0.2455 | +0.3378 | no |
| `limit_increase` | +0.9337 | 245.562 | −2.2147 | **−0.0770** | +0.4881 | sí |

`limit_increase` es el **único** producto del catálogo con `V` negativo con la
λ por defecto. Nótese que con λ=165 se volvería positivo (+0.4881): la elección
de λ es la que decide si ese aviso se manda o no.

### 4.5 Quién consume su salida

- Tercer factor del `score`.
- **Puerta S4** (`pipeline/politica.py::puerta_S4`): cierra si `V <= 0`. Es la que
  apaga `limit_increase` sin una sola regla escrita a mano.
- El texto del silencio S4 cita el `V` y la `λ` exactos.

---

## 5 · M0 · La regla de 24 h (nivel 2 de la escalera)

No es un modelo entrenado: `app/scoring.py::ReglaVeinticuatroHoras` lee
constantes de `analytics/recon/out/` y, si faltan, cae a las constantes
documentadas en el módulo.

- `p_intencion` = conversión medida de la pantalla acoplada a su acción
  (`03_screen_action_p24h.csv` / `_p72h.csv`). Para `warm` usa
  `p72 − p24`, no `p72` directo: comparar una acumulada a 72 h contra una a 24 h
  haría que una señal tibia le ganara a una fresca.
- `p_enganche` = `TASA_ENGANCHE_POR_MOMENTO[momento] × curva_de_fatiga[exposición]`,
  con `on_time 0.4163 · warm 0.2127 · cold 0 · never 0` y la curva
  `1 → 1.0 · 2 → 0.499 · 3 → 0.224 · 4 → 0.112 · 5 → 0.045 · 6 → 0.0`.

Desempeño medido: **62.46 %** de media donde hay señal (63.45 % en `2026-06-09`),
sobre el ~16 % de los activos que tienen señal ≤24 h.

---

## 6 · Cómo se sirve — **cambió respecto al diseño original**

### 6.1 Una foto de features por corte, elegida por el `asof`

El diseño servía siempre la tabla del corte del demo. Eso era **fuga temporal en
caliente**: el caso `multi_senal` se decide el `2026-06-09` y su `p_intencion`
salía de una foto tomada 7 días después.

Lo construido (`app/scoring.py::corte_vigente` y `tabla_para`):

1. Se cargan **todas** las fotos as-of en el arranque. Hoy hay 5:
   `2026-05-23`, `2026-05-30`, `2026-06-09`, `2026-06-14`, `2026-06-16`.
2. Para un `asof` se toma el corte **exacto** si existe; si no, el más reciente
   **anterior o igual**. Nunca uno posterior.
3. Si no hay ninguno válido, el nivel 1 se declara caído **para esa petición** y
   la escalera baja, con el motivo publicado en
   `/health → escalera.descensos_en_peticion`.

Cada oferta de la respuesta trae `corte_features`, que dice de qué foto salió su
`p_intencion`.

### 6.2 El paquete de respaldo se indexa por `(customer_id, asof)`

`demo_pack.json` se genera **por el nivel 1**, instanciando el mismo
`ModeloEntrenado` que sirve en caliente y guardando su salida literal. Con un
solo corte el fallback mentía en 1 de los 9 escenarios curados. Ahora hay un
bloque por corte: `clientes` (el corte por defecto, `2026-06-16`, 5,319 clientes)
y `clientes_por_corte` (hoy solo `2026-06-09`, con 1 cliente).

`V` y `explicacion` **no** se guardan en el paquete: los pone el backend al
leer, para que el paquete no pueda quedarse con una λ vieja.

### 6.3 Umbrales — se eligen en su propio corte, nunca en test

`umbrales.json`, seleccionados en `CORTE_UMBRALES = 2026-05-23`:

| Umbral | Valor | Cómo se eligió |
|---|---|---|
| `p_intencion_min` | **0.2093** | el umbral más bajo cuya precisión iguala la regla de 24 h (objetivo 63.45 %); da 65.73 % de precisión y 15.0 % de cobertura |
| `p_enganche_min` | **0.1927** | el que duplica la tasa base de enganche (10.58 %) sobre los avisos del mes anterior al corte |
| `v_min` | 0.0 | puerta S4 |
| `cap_exposiciones` | 2 | en la 3ª exposición hay 0.72 bajas por enganche |

---

## 7 · La política: qué hace con los tres números

`pipeline/politica.py`. Dos listas distintas y es a propósito:

- **Orden de evaluación** `S0 → S6 → S1 → S2 → S5 → S3 → S7 → S4` — el orden en
  que se corren y en que se escribe la traza.
- **Prioridad de reporte** `S0 > S6 > S3 > S2 > S5 > S7 > S4 > S1` — el orden en
  que se elige *qué* silencio se le cuenta al usuario.

| Puerta | Cierra cuando | ¿Activa? |
|---|---|---|
| S0 · opt-out | el cliente desactivó notificaciones (cliente entero) | sí |
| S6 · fecha | el `asof` cae en zona de datos contaminada (cliente entero) | sí |
| S1 · sin señal | `momento` no es `on_time` ni `warm` (más de 168 h) | sí |
| S2 · cupo | `exposiciones >= 2` | sí |
| S5 · descartes | `n_descartados >= 2` | **no** (se evalúa, no cierra) |
| S3 · fragilidad | cliente frágil **y** producto en `{limit_increase}` | sí |
| S7 · confianza | `confianza < 0.05` | **no** (se evalúa, no cierra) |
| S4 · valor | `V <= 0` | sí |
| C0 | el producto no está en el catálogo del piloto | código propio, no puerta |

`invest_start` y `payroll_portability` reciben siempre C0, nunca "sin señal".

**Cobertura medida** en `2026-06-16` (`/health`, es decir `pipeline/politica.cobertura`):

| | Con S4 | Sin S4 |
|---|---|---|
| oferta | **13.57 %** (5,157 de 38,000) | 14.63 % |
| silencio | **86.43 %** | 85.37 % |

La réplica de analítica (`analytics/metricas.cobertura`, que no evalúa S4) da
**13.99 % / 86.01 %** y desglosa el silencio así: `sin_senal` 28,242 ·
`opt_out` 2,195 · `cupo_agotado` 2,139 · `veto_fragilidad` 109.

---

## 8 · Cómo reproducir todo

```bash
make pipeline                              # features + labels + entrena + artefactos
.venv/bin/python analytics/evaluar.py      # las cifras de este documento
.venv/bin/python analytics/metricas.py     # embudo M1–M5, fatiga, cobertura
make test                                  # anti-fuga temporal y controles de calidad
```

## 9 · Pendientes — números que **no** se pudieron reproducir

Aparecían en el diseño y no están en el código ni en los artefactos, así que no
se usaron en los diagramas:

- `limit_increase +10.78 pp de utilización` — `delta_card_utilization_pct_90d`
  existe en `nudge_outcomes` pero `tabla_valor()` no lo calcula.
- `correlación salud vs revenue = −0.829` — no hay código que la calcule.
- `Store pandas 88.71 MB`, `arranque 293 ms`, `ficha 9.7 ms p50` — no hay
  instrumentación que reporte la memoria; las latencias medidas son otras
  (ver abajo).
- `motor de razones: contribución local coef × z de la LR`, `12 plantillas`,
  `5 µs` — `app/razones.py` explica con el **hecho** del cliente (pantalla,
  horas, exposición, monto), no con la contribución local de la regresión.

Latencias que **sí** se midieron aquí (TestClient en proceso, 60 peticiones por
ruta), después de que la interfaz añadiera `app/panorama.py`:

| | Medido |
|---|---|
| arranque instrumentado (`/health → arranque_s`) | **3.85 s** (rango 3.83–3.85 en 3 arranques) |
| arranque total, contando el import de Python | **4.4 s** |
| `POST /api/decidir` p50 | **29.7 ms** |
| `GET /api/clientes/{id}` (ficha) p50 | **16.2 ms** |
| `GET /api/clientes/{id}/linea-tiempo` p50 | **4.1 ms** |
| `GET /api/contexto` p50 | **48.3 ms** |

El arranque subió de 2.7 s a 3.85 s cuando `app/panorama.py` pasó a montar la
vista poblacional de los **5 cortes** en el `lifespan`. Es un trueque
deliberado: a cambio, el selector de corte, el percentil y el filtro del
selector no tocan disco ni modelo durante la petición.

El servicio expone **10 rutas**: `GET /`, `GET /api/contexto`,
`GET /api/explicacion`, `GET /api/clientes`, `GET /api/clientes/{id}`,
`GET /api/clientes/{id}/linea-tiempo`, `POST /api/decidir`, `GET /health` y,
montadas desde `app/rutas_dashboard.py`, `GET /dashboard` y `GET /api/dashboard`.
Las dos últimas no pagan cálculo por petición: sirven el artefacto
`dashboard/datos.json` que se construye en el arranque.

Ese arranque de 2.7 s es **anterior al panorama**. Hoy, con las cinco vistas
poblacionales montadas en el `lifespan` **y el artefacto del dashboard leído al
importar `app/rutas_dashboard.py`**, `GET /health` reporta `arranque_s` =
**4.21–4.45 s** (3 arranques con uvicorn, remedido el 2026-09-02). La cifra de
**3.85 s** que da «Decisiones de stack» en `docs/arquitectura.md` se midió con
`TestClient` y **antes** del dashboard: las dos son correctas, miden arranques
distintos, y la que ve quien levanta la demo es la de 4.2–4.5 s. Todo el coste
está en el arranque: las latencias por petición no cambian.
