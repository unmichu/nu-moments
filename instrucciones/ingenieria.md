# Instrucciones · Ingeniería

## Contexto mínimo

Un servicio, un puerto, sin paso de compilación. FastAPI sirve la API y la plantilla; el frontend es Jinja2 más una librería reactiva ligera **vendorizada en el repo** (sin CDN: el demo no puede depender de la red).

Medido en desarrollo: **0.69 s de arranque, 12 ms por petición**, datos en memoria (88.71 MB), ficha en 9.7 ms.

---

## ING-1 · Entorno · BLOQUEA A TODOS

```bash
cd /Users/miguel.soto/dev/nu-moments
make setup
.venv/bin/python -c "import sklearn, fastapi, httpx, pandas, duckdb; print('ok')"
```

`httpx` es imprescindible: sin él, el cliente de pruebas de FastAPI no funciona y las pruebas anti-fuga —que el reto pide por nombre— no corren.

**No uses un entorno en `/tmp`.** Se borra al reiniciar y un reinicio la mañana del segundo día deja al equipo sin nada.

---

## ING-2 · Fixture · DESBLOQUEA EL FRONTEND ENTERO

**Antes de escribir el backend**, publica `app/fixture.json` con la respuesta de ejemplo del POST, a mano, con la forma final:

```json
{
  "customer_id": 6007107,
  "asof": "2026-06-16T12:00:00",
  "decision": "sustitucion",
  "modelo": "v1",
  "ofertas": [
    {"producto": "bill_reminder", "score": 0.412, "surface": "home_card",
     "titulo": "Ponte al día sin intereses",
     "razon": "Entraste a subir tu línea hace 8.6 horas y tu tarjeta está al 83.4 %. Un aumento ahora te costaría más de lo que te ayuda."}
  ],
  "silencios": [
    {"producto": "limit_increase", "puerta": "S3_veto_dano",
     "razon": "Utilización 83.4 % y 2 días en negativo en los últimos 90."}
  ],
  "traza": [
    {"puerta": "S0_opt_out", "resultado": "pasa"},
    {"puerta": "S6_fecha", "resultado": "pasa"},
    {"puerta": "S1_sin_senal", "resultado": "pasa"},
    {"puerta": "S2_cupo", "resultado": "pasa"},
    {"puerta": "S5_descartes", "resultado": "no_activa"},
    {"puerta": "S3_fragilidad", "resultado": "cierra", "producto": "limit_increase"},
    {"puerta": "S7_confianza", "resultado": "no_activa"},
    {"puerta": "S4_valor", "resultado": "pasa"}
  ],
  "cobertura": {"pct_silencio": 86.0, "pct_oferta": 14.0}
}
```

Con esto, el frontend se construye completo sin esperar al modelo.

---

## ING-3 · La política — las 8 puertas

`pipeline/politica.py`. **El orden de evaluación y la prioridad de reporte no son la misma lista, y es a propósito.**

**Orden de evaluación:** `S0 → S6 → S1 → S2 → S5 → S3 → S7 → S4`

**Prioridad de reporte:** `S0 > S6 > S3 > S2 > S5 > S7 > S4 > S1`

La prioridad de reporte es lo que hace que un cliente frágil con cupo libre reporte **veto por daño** y no un silencio genérico. Si reportas la primera puerta que se dispara en vez de la más informativa, el momento clave de la demo dice algo aburrido.

```python
def decide(cliente, fecha, scores, artefactos):
    """Devuelve {decision, ofertas[], silencios[], traza[8], modelo}."""
    traza, silencios, candidatos = [], [], []

    for producto in TODOS_LOS_PRODUCTOS:
        if producto not in CATALOGO_DEMO:
            silencios.append({"producto": producto,
                              "puerta": "C0_fuera_de_catalogo"})
            continue
        # ... evaluar las 8 puertas en orden, registrar en traza
        # ... si alguna cierra, añadir a silencios con su código
        # ... si pasan todas, añadir a candidatos con su score

    # sustitución: si S3 cerró un producto y hay alternativa sana con cupo,
    # se ofrece la alternativa en lugar de callar
    return armar_respuesta(candidatos, silencios, traza)
```

**`traza` y `silencios` se emiten siempre**, en toda respuesta.

**Los productos fuera de catálogo llevan su propio código**, nunca "sin señal". Un silencio por "sin señal" que en realidad es "no lo vendemos" sería mentir en la traza, y la traza es lo que hace auditable al sistema.

---

## ING-4 · Backend

`app/main.py`. Los artefactos se cargan **al arranque**, no por petición:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = Store.cargar("data/")          # ~293 ms
    app.state.scorer = cargar_scorer("pipeline/artifacts/")
    app.state.cobertura = cargar_cobertura()
    yield

app = FastAPI(lifespan=lifespan)
```

### Escalera de fallback

1. Modelo entrenado
2. Regla de 24 h (63.45 % donde hay señal)
3. Paquete precalculado

**El nivel 2 es una línea del pitch, no una vergüenza.**

### Manejo de errores

```python
@app.exception_handler(Exception)
async def cualquier_error(request, exc):
    return JSONResponse(status_code=200, content={
        "decision": "silencio",
        "razon_silencio": "El sistema no pudo evaluar este caso con confianza.",
        "modelo": "degradado"})
```

Silencio con **HTTP 200**: el modo degradado es coherente con la tesis del producto en lugar de verse como una app rota.

### Endpoints

`GET /api/clientes` · `GET /api/clientes/{id}?asof=` · `POST /api/decidir` · `GET /health`

**La explicación viaja dentro del POST**, no en un endpoint aparte: el clic es instantáneo y la leyenda no puede divergir de la decisión que la produjo.

---

## ING-5 · Verificación de integración · EL FALLO MÁS CARO

Tres cosas fallan **en silencio** — no revientan, degradan:

| Riesgo | Comprobación |
|---|---|
| Los nombres de artefacto no coinciden | `ls pipeline/artifacts/` contra la tabla de `docs/arquitectura.md` |
| El corte de `metadata.json` no es el del demo | `jq .corte pipeline/artifacts/metadata.json` |
| El POST responde con el fallback y nadie lo nota | el campo `modelo` debe decir `v1` |

Automatízalo:

```python
# pipeline/verificar_integracion.py  → exit 1 si algo no cuadra
assert meta["corte"] == CORTE_DEMO, f"corte {meta['corte']} != {CORTE_DEMO}"
assert respuesta["modelo"] == "v1", "el POST está devolviendo fallback"
```

Es criterio, no opinión. Córrelo antes de cada ensayo.

---

## ING-6 · Frontend

`app/templates/index.html` más CSS y JS propios. Librería reactiva **vendorizada** en `app/static/`.

### El selector no puede ser aleatorio

El **82.7 %** de los clientes no tiene eventos en las últimas 24 h. Con un selector al azar, el panel de actividad sale vacío cuatro de cada cinco veces. **Escenarios curados al frente**, búsqueda libre como secundaria.

### El estado de silencio es una pantalla diseñada

Es el momento más importante de la demo y **no puede parecer que la app se rompió**. Debe mostrar:

- Que el sistema evaluó y decidió, no que falló
- La razón, en lenguaje natural
- La traza de las 8 puertas, plegada, para abrirla si alguien pregunta
- El contador: *"el 86.0 % de los clientes está en esta situación"*

El contador **se lee del artefacto**, nunca escrito a mano en el HTML.

### Flujo

Selector → ficha del cliente → `POST /api/decidir` → botones de oferta → clic → leyenda del porqué.

---

## ING-7 · Pruebas anti-fuga · EVIDENCIA, NO HIGIENE

El reto lo pide por nombre. Van en `pipeline/tests/test_leakage.py`:

```python
def test_sin_eventos_futuros():
    """Ninguna feature usa eventos con ts >= asof."""

def test_columnas_prohibidas():
    """Ninguna columna de la lista negra está en la matriz."""

def test_sin_columnas_id():
    """Ninguna columna que empiece por customer_id."""

def test_negativo_evento_futuro():
    """Se inyecta un evento en asof+1h y NINGUNA feature se mueve."""
    base = construir_features(cliente, asof)
    inyectar_evento(cliente, asof + timedelta(hours=1))
    assert construir_features(cliente, asof).equals(base)

def test_barajado_temporal_degrada():
    """Barajar el tiempo debe empeorar el modelo."""
```

El cuarto es el que convence: demuestra la propiedad en vez de afirmarla.

---

## ING-8 · Evidencias de ejecución

`pipeline/evidencias/`: por cada etapa, filas de entrada, filas de salida, duración y marca de tiempo. Un solo archivo de registro con formato estable. El reto lo pide explícitamente.

---

## ING-9 · Ensayo y blindaje

Antes de presentar, en este orden:

1. `make test` en verde
2. `python pipeline/verificar_integracion.py` con salida 0
3. **Recorrer los escenarios curados uno por uno** y confirmar que cada uno da la decisión que el guion promete
4. Capturas de pantalla de cada estado, por si el servicio falla en vivo

El paso 3 no es opcional. Con una cobertura de señal del 11.4 %, que un escenario se rompa al cambiar algo no es hipotético.

---

## Prompt para delegar

```
Eres ingeniero de software. Trabaja en el repo nu-moments.

Lee primero: instrucciones/ingenieria.md (completo), docs/arquitectura.md
(contratos y API) y docs/prd.md (las 8 puertas y las cuatro salidas).

Tu tarea es [ING-N]. Solo esa.

Reglas innegociables:
- Un proceso, un puerto, sin paso de compilación. Sin CDN: todo vendorizado.
- El demo NUNCA depende de la red.
- Los artefactos se cargan al arranque, no por petición.
- Cualquier excepción devuelve silencio con HTTP 200, nunca un 500.
- Los nombres de archivo de docs/arquitectura.md son ley: otra área los produce.
- El orden de evaluación de las puertas y la prioridad de reporte son listas
  distintas. Respeta ambas.
- Nada de valores por defecto silenciosos. Si falta un artefacto, que se note.

Al terminar: ejecuta la verificación de la tarea y pega la salida real.
Si el POST devuelve "modelo": "fallback", la tarea NO está terminada.
```
