# nu-moments

**Reto 3 · Próxima intención, momento adecuado** — Frente A, asistente financiero orientado al cliente.

## Objetivo

Predecir la **próxima intención financiera** de cada cliente y decidir si **este es el momento adecuado** para actuar. Encadenamos un modelo de intención y un modelo de momento, y elegimos y defendemos una función objetivo.

## El desafío

La dificultad no está en la interfaz, está en el juicio: saber qué quiere el cliente, si es el momento de decir algo, y qué debe optimizar la recomendación. Tres preguntas, no una:

1. **Próxima intención** — ¿qué acción financiera está a punto de tomar?
2. **Momento adecuado** — ¿vale la pena hablar ahora? La misma recomendación repetida no es neutral: cuesta.
3. **Qué optimizamos** — salud financiera, satisfacción, engagement o rentabilidad apuntan a recomendaciones distintas.

## La tesis

Hoy **el 98.5 % de los avisos se envían fuera del momento**. El 1.5 % que cae bien recibe **4 veces más clic** (41.63 % contra 10.30 %) y genera **36 % menos bajas** que la señal fría. Clic, no la acción hecha: son dos métricas distintas y el dashboard las separa.

No nos falta contenido. Nos falta la decisión de callarnos: el sistema guarda silencio en el **86.4 %** de los casos, y cada silencio trae su razón auditable.

## Instrucciones

```bash
git clone <este-repo> && cd nu-moments
make setup      # entorno virtual + dependencias
make pipeline   # construye features y entrena los modelos
make test       # controles de calidad y pruebas anti-fuga temporal
make demo       # levanta la simulación en http://localhost:8000
```

Requiere Python 3.12+. Los datos sintéticos ya están en `data/`, no hay que descargar nada.

Dos pantallas en el mismo proceso: la simulación en `/` —con las pestañas «Decisión» y
«Cómo funciona»— y el dashboard general en [`/dashboard`](docs/dashboard.md).

## Índice

| Ruta | Contenido |
|---|---|
| [`docs/prd.md`](docs/prd.md) | Documento de producto: problema, feature, estados, alcance |
| [`docs/arquitectura.md`](docs/arquitectura.md) | Flujo end-to-end, contratos de datos y de API |
| [`docs/modelos.md`](docs/modelos.md) | **Los modelos en detalle**: entradas, uniones con su SQL, hiperparámetros, evaluación |
| [`docs/metricas.md`](docs/metricas.md) | Árbol de métricas, función objetivo y guardrails |
| [`docs/dashboard.md`](docs/dashboard.md) | El dashboard general (`GET /dashboard`): los 9 bloques, qué mide cada gráfica y de dónde sale |
| [`docs/backlog.md`](docs/backlog.md) | Tareas por área con dependencias |
| [`docs/decision-log.md`](docs/decision-log.md) | Decisiones tomadas y por qué |
| [`docs/uso-de-ia.md`](docs/uso-de-ia.md) | Cómo usamos IA en el proceso |
| [`instrucciones/`](instrucciones/) | **Guías ejecutables por área** — para una persona o para un agente de IA |
| [`data/`](data/) | Dataset sintético (5 tablas, ~1.7 M filas) y su generador |
| [`pipeline/`](pipeline/) | Ingesta, features, política de decisión, evidencias de ejecución |
| [`app/`](app/) | El servicio de la demo: 10 endpoints, escalera de fallback y las dos pantallas |
| [`analytics/`](analytics/) | EDA, modelos, métricas y controles de calidad |
| [`dashboard/`](dashboard/) | `datos.json`, el artefacto precalculado que sirve `GET /dashboard` |
| [`pitch/`](pitch/) | Material de la presentación |

## Datos

100 % sintéticos. Ninguna información de clientes reales está involucrada.

| Tabla | Filas | Contenido |
|---|---|---|
| `customers` | 38,000 | Perfil y situación financiera |
| `app_events` | 797,304 | Navegación, 119 días, sin identificador de sesión |
| `financial_actions` | 566,682 | Acciones con las que se construye el label |
| `nudges` | 285,000 | Exposición, momento, enganche, descarte y baja |
| `nudge_outcomes` | 285,000 | Consecuencias a 90 días en salud financiera e ingresos |

Claves de unión: `customer_id` en todas; `nudge_id` entre `nudges` y `nudge_outcomes`.
