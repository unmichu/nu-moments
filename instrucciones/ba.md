# Instrucciones · Analítica

## Contexto mínimo

Cinco tablas sintéticas en `../data/`. Unión por `customer_id`; `nudge_id` entre avisos y resultados. Ya existe código de exploración en `../analytics/recon/` con 8 scripts y sus salidas: **reutilízalo, no lo rehagas**.

## Números que debes respetar

No los recalcules para "confirmar" — úsalos como **prueba de regresión de tu propio código**. Si tu script da otra cosa, tu script está mal.

| Concepto | Valor |
|---|---|
| Baseline por corte (predictor constante) | 25.63 / 41.62 / 33.64 |
| Baseline en el corte de umbrales | 45.89 |
| Activos por corte | 24,268 / 18,606 / 20,701 · umbrales 16,999 |
| Conversión dado señal ≤24 h, por producto | 49.39 % ahorro · 30.57 % línea · 24.84 % préstamo |
| Tasa base de esas acciones | 4.51 % · 1.52 % · 1.24 % |
| Curva de fatiga (enganche) | 15.68 → 7.83 → 3.51 → 1.75 → 0.70 → 0.00 |
| Curva de fatiga (baja) | 0.279 → 1.270 → 2.531 → 3.308 → 4.502 → 6.112 |
| Cobertura | 13.6 % oferta / 86.4 % silencio · 14.6/85.4 sin la puerta de valor |

---

## BA-1 · Mapas compartidos

**Bloquea a:** todo lo demás, en las dos áreas.

Crea `pipeline/mapas.py` con tres diccionarios y nada más:

```python
PRODUCTO_A_ACCION = {
    "savings_goal": "savings_move",
    "limit_increase": "limit_increase_request",
    "loan_offer": "loan_request",
    "bill_reminder": "bill_payment",
    "invest_start": "investment_buy",
}
PRODUCTO_A_PANTALLA = {
    "savings_goal": "savings_cajita",
    "limit_increase": "limit_increase",
    "loan_offer": "loan_simulation",
    "bill_reminder": "bill_payment",
    "invest_start": "investments",
}
CATALOGO_DEMO = ["savings_goal", "limit_increase", "loan_offer", "bill_reminder"]
```

`payroll_portability` **no está** en ningún mapa: su pantalla acoplada es la de inicio, así que cualquiera que abra la app "tiene señal" y se lleva el 10.5 % de las ofertas por trivialidad.

**Verificación:** `python -c "from pipeline.mapas import CATALOGO_DEMO; assert len(CATALOGO_DEMO)==4"`
**Después de esto, el archivo es de solo lectura.** Cambiarlo rompe a Ingeniería sin avisar.

---

## BA-2 · Tabla de features as-of

**Depende de:** BA-1. **Bloquea a:** todos los modelos.

Grano: una fila por `(customer_id, asof_ts)`. **Toda feature se calcula con `event_ts < asof_ts` estricto.**

### Los joins

```sql
-- navegación: recencia por pantalla
SELECT c.customer_id,
       DATE_DIFF('hour', MAX(e.event_ts), $asof) AS horas_desde_vista,
       COUNT(*) FILTER (WHERE e.action='start') AS n_start,
       COUNT(*) AS n_vistas
FROM customers c
LEFT JOIN app_events e
       ON e.customer_id = c.customer_id
      AND e.event_ts < $asof            -- ESTRICTO. sin esto, fuga.
      AND e.screen = $pantalla
GROUP BY c.customer_id
```

⚠️ **No uses `LEFT JOIN ... USING`.** Duplica la clave y mete `customer_id_2` en la matriz de features. Verificado: aparece de verdad, y un modelo llegó a usarla con peso 0.070. Usa `ON` explícito y una lista de columnas explícita.

### Las features

| Grupo | Definición | Cantidad |
|---|---|---|
| Recencia por pantalla | horas desde la última vista de cada pantalla | 10 |
| Conteo por pantalla | vistas en 24 h y en 72 h | 20 |
| Señal por producto | `on_time` / `warm` / `cold` / `never` según recencia en la pantalla acoplada | 8 |
| `start` vs `view` | proporción de inicios sobre vistas | 8 |
| Tenencia | los indicadores `has_*` | 5 |
| Calendario | días hasta el próximo día de pago | 1 |
| Exposición | número de exposiciones previas por producto | 4 |

**Prohibidas, con motivo:**

| Feature | Por qué no |
|---|---|
| Cualquier cosa de resultados a 90 días | Es el target |
| `engaged`, `dismissed`, la baja | Es el target |
| `engagement_score` | Genera el volumen de eventos **y** de avisos: es casi el label |
| Abandono | **Anti**-predictivo: 0.15 % contra 23.33 % |
| Hora del día, día de semana | Ruido: rango de 0.98 pp y 0.35 pp |
| Espaciado desde el último aviso | Efecto nulo controlando por exposición |
| Secuencia histórica de acciones | Predice **peor** que el baseline |
| `customer_id_2` y similares | Artefacto de join |

**Precomputa en los tres cortes:** el del modelo y **los dos del demo**. El demo no corre en el corte del modelo.

**Verificación:** la tabla debe tener 82 columnas de features. `assert len([c for c in df.columns if not c.startswith("customer_id")]) == 82`

---

## BA-3 · Labels

`labels_intent.parquet`: una fila por `(customer_id, asof)`, ocho columnas binarias `y_<accion>` = ¿hizo esa acción en `(asof, asof+7d]`?

`labels_moment.parquet`: una fila por `nudge_id`, columna `y_engaged`.

**Descarta los 3 primeros días y los 3 últimos.** El primer día tiene 7.36 veces la mediana de acciones (artefacto del generador) y el final está censurado.

---

## BA-4 · Canario de baselines · PUERTA DE CALIDAD

**Sin esto en verde, nada de lo que sigue es confiable.**

Recomputa los baselines desde tu propio label y compara:

```python
esperado = {"d90": 25.63, "d100": 41.62, "d105": 33.64, "d83": 45.89}
for corte, val in esperado.items():
    obtenido = acc_baseline(corte)
    assert abs(obtenido - val) < 0.05, f"{corte}: {obtenido} != {val}"
```

**El baseline es un predictor constante elegido en entrenamiento**, no "la clase mayoritaria de cada corte". En uno de los tres cortes la mayoritaria es otra clase, y elegirla por corte sería usar el test para decidir qué predecir.

---

## BA-5 · Los modelos

### Intención

```python
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

# una cabeza por acción
hgb = HistGradientBoostingClassifier(max_depth=4, random_state=0)   # puntúa
lr  = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))  # explica
```

- **Sin `class_weight='balanced'`**: medido, cuesta 10.07 pp.
- **`StandardScaler` obligatorio** antes de la regresión, o no converge.
- El árbol puntúa, la regresión explica. Coinciden en la clase principal el 89 % de las veces; el 11 % restante cae a explicación por regla, **con marca en la respuesta**.

### Momento

Regresión logística escalada con dos variables: estado de señal y número de exposición. El árbol aporta +0.0011 de AUC — no lo uses.

Objetivo: AUC 0.7107, precisión en el 1 % superior 33.02 % contra base 8.27 %.

### Valor

No es aprendizaje automático, es aritmética:

```
V(producto, λ) = (−Δdías_negativos) + (Δingreso / λ) + 0.3 · Δahorro
```

Comprobación: `V(ahorro, 266) = +0.700` y `V(línea, 266) = −0.077`.

### Umbrales

Se eligen en el **corte de umbrales**, nunca en test.

### Evaluación

Reporta contra **tres** baselines, no uno: el predictor constante, la regla de 24 h (63.45 % donde hay señal) y el modelo.

**Di primero que en el corte principal el árbol empata con la regla.** La ganancia es estabilidad: rango de 2.61 pp entre cortes contra 7.17 pp de la regla. Esconderlo y que lo pregunten es peor.

---

## BA-6 · Fases de entrega — el backend nunca espera

| Fase | Qué entrega | Cuándo |
|---|---|---|
| v0 | Modelos reales de sklearn, aunque simples | Primera hora y media |
| v1 | Los modelos definitivos | Tres horas después |

**v1 reemplaza a v0 en el sitio, con los mismos nombres de archivo.** El backend no cambia una línea. No entregues un JSON de consulta como v0: rompe esa promesa.

Guarda en `pipeline/artifacts/` con estos nombres exactos: `modelo_intencion.pkl`, `modelo_momento.pkl`, `umbrales.json`, `tabla_valor.json`, `razones.json`, `metadata.json`.

**`metadata.json` debe declarar el corte del demo.** Si no coincide, el backend cae al fallback en silencio.

---

## BA-7 · Sesionización — la respuesta honesta

El reto pide definir sesiones de navegación. **En estos datos no existen.** No lo escondas: demuéstralo.

1. Implementa la sesionización con umbral configurable.
2. Barre umbrales de 15, 30, 60 y 120 minutos.
3. Genera el histograma de intervalos entre eventos.
4. Reporta: mediana de intervalo **58 h**, solo **1.09 %** de los intervalos bajan de 30 min, y con umbral de 30 min salen **1.01 eventos por sesión**.
5. Propón el sustituto: recencia por pantalla.

Implementarlo y explicar por qué no aplica puntúa más que fingir que funcionó.

---

## BA-8 · Métricas

Calcula el embudo M1–M5 y las métricas por producto (ver `../docs/metricas.md`), **bajo la política final, no solo bajo el statu quo**. La tabla comparativa es el cierre del pitch.

Los valores del statu quo ya están medidos: úsalos como prueba de regresión.

---

## BA-9 · Controles de calidad

| Control | Criterio |
|---|---|
| Integridad de uniones | 0 huérfanos en las tres tablas |
| Canario de baselines | los cuatro valores dentro de ±0.05 |
| Distribución de clases | estable entre los tres cortes |
| Sin fuga | ninguna feature se mueve al inyectar un evento futuro |
| Sin columnas de identificador | ninguna `customer_id*` en la matriz |
| Cobertura | 14.0 % ± 0.1 con el catálogo de 4 |

---

## Prompt para delegar

```
Eres analista de datos. Trabaja en el repo nu-moments.

Lee primero: instrucciones/ba.md (completo), docs/arquitectura.md (contratos)
y data/README-dataset.md (diccionario de datos).

Tu tarea es [BA-N]. Solo esa.

Reglas innegociables:
- Toda feature con corte temporal estricto: event_ts < asof_ts. Se prueba, no se promete.
- Los números de la tabla "Números que debes respetar" son pruebas de regresión.
  Si tu código da otra cosa, tu código está mal.
- Respeta los nombres de archivo de docs/arquitectura.md. Otra área los consume.
- No uses las features prohibidas. Cada una tiene su motivo escrito.
- Reutiliza analytics/recon/: hay 8 scripts y sus salidas ya calculadas.

Al terminar: ejecuta la verificación de la tarea y pega la salida real,
no la esperada. Si no coincide, dilo en vez de ajustar el número.
```
