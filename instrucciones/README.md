# Instrucciones por área

Tres guías. Cada una es **autosuficiente**: contiene el contexto necesario, los números que hay que respetar y los pasos concretos.

| Guía | Para quién |
|---|---|
| [`producto.md`](producto.md) | Definición, copy, guion, pitch |
| [`ba.md`](ba.md) | Datos, features, modelos, métricas, controles de calidad |
| [`ingenieria.md`](ingenieria.md) | Repo, backend, frontend, política, pruebas |

## Cómo usarlas

**Una persona:** léela de arriba abajo. Las tareas están en orden de dependencia.

**Un agente de IA:** cada guía termina con una sección `## Prompt para delegar` que se puede copiar tal cual. Delega **una tarea a la vez**, no la guía entera: las tareas tienen dependencias entre sí y un agente que intente hacerlas todas de golpe producirá piezas incoherentes.

## Reglas que aplican a las tres áreas

1. **Ningún número sin fuente.** Toda cifra debe reproducirse ejecutando un script de `analytics/`. Si no se puede reproducir, no va al pitch.
2. **Orden temporal estricto.** Ninguna feature puede mirar hacia adelante. Se prueba, no se promete.
3. **Los contratos mandan.** Los nombres de archivo, las claves de diccionario y las rutas de `docs/arquitectura.md` son ley. Cambiar uno por tu cuenta rompe a otra área en silencio.
4. **Commits propios por área.** Nadie commitea por otro; el historial se evalúa.
5. **El fallo silencioso es el enemigo.** Un valor por defecto que nadie mira es peor que una excepción. Ante la duda, que reviente.

## Verificación transversal

Antes de dar cualquier cosa por terminada:

```bash
make test                       # controles de calidad y anti-fuga
curl -s localhost:8000/health   # debe decir modelo: v1, no fallback
```

Si `/health` dice `fallback`, el demo está corriendo con la regla simple y **no lo va a avisar**. Es el fallo más caro del proyecto.
