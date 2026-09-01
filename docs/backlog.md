# Backlog

Tareas por área. El detalle ejecutable está en [`../instrucciones/`](../instrucciones/).

## Primera hora — desbloquea todo lo demás

| # | Área | Tarea | Bloquea a |
|---|---|---|---|
| 1 | Ingeniería | Entorno: `make setup` y verificar que importa `sklearn`, `fastapi`, `httpx` | todo |
| 2 | Ingeniería | Publicar `fixture.json` con la respuesta de ejemplo del POST | el frontend entero |
| 3 | Analítica | Mapas de producto→acción→pantalla como módulo compartido | features, política |
| 4 | Analítica | Verificar acceso a la herramienta de dashboard | dashboard |
| 5 | Producto | Ratificar el orden y la prioridad de reporte de las 8 puertas | la política |

## Camino crítico

```
entorno → mapas → features as-of → canario de baselines → modelo v0
   → modelo v1 → features de los cortes del demo → metadata
   → integración → verificación de escenarios → ensayo → congelamiento
```

Tres puntos sin holgura: el **canario de baselines** (puerta de calidad de toda la analítica), las **features de los cortes del demo**, y la **integración** — cuyo fallo es silencioso.

## Por área

### Producto
Ratificar las puertas · función objetivo y λ · copy de ofertas y silencios · guion de la demo · guion del pitch · slides · preguntas del jurado · PRD · backlog · registro de decisiones · revisión de qué se publica.

### Analítica
Mapas compartidos · features as-of · labels · canario de baselines · los tres modelos · umbrales · motor de razones · métricas del embudo · métricas bajo la política final · curva de fatiga · sesionización · controles de calidad · paquete de respaldo · dashboard.

### Ingeniería
Repo y estructura · entorno · fixture · ingesta · política de 8 puertas · scoring con fallbacks · backend y endpoints · frontend · estado de silencio · selector curado · pruebas anti-fuga · evidencias de ejecución · integración de artefactos · ensayo y blindaje.

## Prioridades

**P0 — sin esto no hay entrega:** entorno, features, un modelo cargable, la política, el backend, el frontend, las pruebas anti-fuga, la sesionización, el PRD y el pitch.

**P1 — el pitch se debilita:** métricas bajo la política final, dashboard, motor de razones completo, evidencias de ejecución.

**P2 — si sobra tiempo:** deslizador de λ en vivo, endpoint de simulación, análisis de la paradoja de Simpson, controles de calidad opcionales.
