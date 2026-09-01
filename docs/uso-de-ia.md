# Uso de IA

## Cómo la usamos

**Exploración de datos.** Agentes de IA escribieron y ejecutaron los scripts de `analytics/recon/`, midiendo cada hipótesis contra los datos en vez de asumirla. Varias intuiciones razonables quedaron desmentidas así: el abandono como señal de intención, la existencia de sesiones de navegación, la hora del día como factor del enganche.

**Contraste, no generación.** El patrón que más valor dio fue pedir verificación en lugar de producción: *"esto es lo que creemos, compruébalo contra los datos y dinos si es falso"*. Varios números que circulaban resultaron calculados sobre las muestras y no sobre las tablas completas, y las muestras son truncados de un solo día.

**Revisión cruzada.** Cada área preparó su trabajo por separado y un paso final buscó las incompatibilidades entre áreas. Aparecieron seis roturas de contrato —nombres de archivo divergentes, claves de diccionario que no coincidían, un orden de puertas contradictorio— y **las seis fallaban en silencio**: sin excepción, sin registro, sin prueba en rojo.

**Documentación y código.** Borradores de documentos, esqueletos de servicio, plantillas de texto y pruebas.

## Qué no le delegamos

- **La elección de la función objetivo.** Es una decisión de producto con consecuencias para el cliente.
- **El veto a clientes frágiles.** Igual.
- **La aceptación de un número sin fuente.** Toda cifra de este repo se reproduce ejecutando un script de `analytics/`.

## Lo que aprendimos del proceso

La IA acelera la parte que ya sabías hacer y **es especialmente buena encontrando lo que no sabías que estaba mal**. El hallazgo con más impacto del proyecto —que el aviso con más clics es el que peor resultado deja— salió de pedirle que buscara contradicciones entre métricas, no de pedirle un modelo.

El segundo aprendizaje es sobre el fallo silencioso. Cuando varios agentes trabajan en paralelo sin verse, producen piezas coherentes por dentro e incompatibles entre sí, y el error no se manifiesta como una excepción sino como un valor por defecto que nadie mira. La verificación cruzada no es opcional.
