# Arquitectura

## Flujo end-to-end

```
data/*.parquet                    5 tablas sintéticas, ~1.7M filas
        │
        ▼
pipeline/features.py              features as-of · corte estricto ts < asof
        │
        ├──► MODELO X · Intención      ¿qué va a querer?
        ├──► MODELO Y · Momento        ¿enganchará ahora?
        └──► MODELO Z · Valor          ¿cuánto aporta o cuánto daña?
                    │
                    ▼
        score = p_intencion × p_enganche × V(λ)
                    │
                    ▼
pipeline/politica.py              8 puertas S0–S7 en orden
                    │
        ┌───────────┼───────────┬──────────────┐
        ▼           ▼           ▼              ▼
     OFERTA    SUSTITUCIÓN   SILENCIO    FUERA DE CATÁLOGO
        │           │           │              │
        └───────────┴─────┬─────┴──────────────┘
                          ▼
             app/  ·  botón + leyenda del porqué
```

## Los tres modelos

| Modelo | Pregunta | Entrada | Algoritmo | Resultado |
|---|---|---|---|---|
| **X · Intención** | ¿qué acción hará en 7 días? | `app_events` + `financial_actions` + `customers` | 8 cabezas binarias: `HistGradientBoosting` puntúa, `LogisticRegression` explica | top-1 **43.75 %** vs baseline **33.63 %** |
| **Y · Momento** | ¿enganchará este aviso? | `nudges` + features as-of | `LogisticRegression` escalada, 2 variables | **AUC 0.7107**, precisión en el 1 % superior **33.02 %** vs base 8.27 % |
| **Z · Valor** | ¿cuánto aporta o daña? | `nudges` + `nudge_outcomes` + `customers` | Tabla determinista — **no es aprendizaje automático** | `V(ahorro,266)=+0.700` · `V(línea,266)=−0.077` |

**M0 · Fallback:** la regla de 24 h envuelta con la misma interfaz. Acierta **63.45 %** donde hay señal y entrena en 0 s.

### Por qué dos modelos y no uno

La intención dice *qué*, el momento dice *si ahora*. Son preguntas con distinta unidad de observación: la intención se predice por cliente y fecha; el momento, por aviso mostrado. Encadenarlas permite responder «sé lo que quieres, pero hoy no te lo voy a decir».

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

**`metadata.json` debe declarar el corte del demo.** Si no coincide, el backend cae al fallback y no avisa. La verificación es explícita: la respuesta del POST trae el campo `modelo`, y debe decir `v1`.

## API

| Endpoint | Devuelve |
|---|---|
| `GET /api/clientes` | Lista para el selector, con los escenarios curados al frente |
| `GET /api/clientes/{id}?asof=` | Ficha: perfil, movimientos, navegación reciente, historial de avisos |
| `POST /api/decidir` | La decisión: ofertas con score y razón, o silencio con su causa, más la traza de las 8 puertas |
| `GET /health` | Estado y versión de los artefactos cargados |

**La explicación viaja dentro del POST.** Dos razones: el clic en el botón es instantáneo, y es imposible que la leyenda diverja de la decisión que la produjo.

## Robustez

Los modelos se cargan **al arranque**, no por petición. Escalera de tres niveles:

1. Modelo entrenado
2. Regla de 24 h
3. Paquete precalculado

Cualquier excepción devuelve **silencio con HTTP 200**: el modo degradado es coherente con la tesis del producto en lugar de verse como un error.

## Decisiones de stack

Un proceso, un puerto, sin paso de compilación. Medido en la máquina de desarrollo: **0.69 s de arranque, 12 ms por petición**, con los datos en memoria (88.71 MB) y la ficha resolviéndose en 9.7 ms.

El demo **nunca depende de la red**. Cualquier consulta remota queda para el trabajo por lotes y el dashboard, jamás en el camino del pitch.
