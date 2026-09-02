# dashboard

El **dashboard general** de nu-moments: todas las métricas del proyecto en una
página, escrita para alguien que no ha visto el dataset ni ha estado en ninguna
reunión.

```
GET /dashboard        la página
GET /api/dashboard    los mismos datos en JSON
```

Se documenta entero en [`docs/dashboard.md`](../docs/dashboard.md): los nueve
bloques, la procedencia de cada cifra y las cuatro reglas con las que se hizo
entendible.

## Qué hay en esta carpeta

| Archivo | Qué es |
|---|---|
| `datos.json` | El **artefacto precalculado** que la página sirve. Todas las cifras, con la firma de los insumos con los que se generaron |

No hay imágenes exportadas: las gráficas se dibujan en la propia página con CSS
y un `<svg>` en línea, y así no hay dos versiones de la misma cifra —una en un
PNG viejo y otra en la pantalla— que puedan desdecirse.

## Regenerar las cifras

```bash
.venv/bin/python -m app.dashboard_datos
```

Cuesta unos 5 s: carga el `Store` de 1.7 M filas, corre la política sobre los
38 000 clientes en los 5 cortes y vuelve a evaluar los dos modelos. Después la
página se sirve en 30 ms, porque el servicio lee el artefacto al arrancar.

No hace falta acordarse de ejecutarlo: `datos.json` guarda la **firma** (los
tamaños en bytes) de los 5 parquet y de los artefactos del pipeline. Si alguno
cambia, el artefacto se reconstruye solo en el siguiente arranque, y
`analytics/tests/test_dashboard.py` falla si se sirviera uno desfasado.

## Las cinco cifras que cuenta la página

| Cifra | Qué dice |
|---|---|
| **86.43 %** | de los 38 000 clientes no reciben nada hoy, y cada silencio trae su motivo contado |
| **1.46 %** | de los 285 000 avisos cae con señal fresca; el resto se manda a ciegas |
| **4.04×** | mejor convierte ese momento. Mismo mensaje, mismo producto: solo cambia cuándo |
| **11.45 %** | de los avisos reciben clic, y más de un tercio se cierran de forma activa |
| **Aumento de línea** | el aviso nº 1 en clics de seis y el último en salud financiera |

Las seis gráficas que cuentan la historia —fatiga, momento, clic contra
conversión, los tres rankings, la simulación de políticas y el embudo— están
todas en la página, en los bloques 3 a 7. La de clic contra conversión es la
que menos se espera y más se recuerda.
