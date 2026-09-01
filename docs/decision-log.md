# Registro de decisiones

Formato: qué se decidió, por qué, y qué se descartó.

---

### D1 · Multi-etiqueta, no multiclase
Ventana de 7 días, 8 cabezas binarias. En multiclase, las tres acciones accionables para el negocio suman 7.1 % del label y el modelo las ignoraría. Con umbral propio por clase, no.

### D2 · Dos fechas de corte, a propósito
Modelo: corte principal con validación de origen móvil sobre tres cortes. Demo: otro corte distinto. Motivo: el día de pago solo toma tres valores y el corte del modelo cae en el hueco, así que **el caso de sincronía con la quincena no existe ahí**. No es una inconsistencia, son propósitos distintos.

### D3 · El baseline es un predictor constante, no «la clase mayoritaria de cada corte»
En uno de los tres cortes la clase mayoritaria es otra. Definirlo por corte sería un oráculo: usaría la distribución del test para elegir qué predecir. Baseline = clase constante elegida en entrenamiento.

### D4 · Cap de 2 exposiciones
Derivado, no dado. En la tercera exposición hay 0.72 bajas por enganche; en la cuarta, 1.89. El brief deja el guardrail sin número y esta es su derivación.

### D5 · Veto duro para clientes frágiles, no precio
El aumento de línea engancha 46 % más a los clientes frágiles y les causa +17.52 pp de utilización y +2.06 días en negativo. Se excluye de la función objetivo en vez de ponerle un peso: hay decisiones que no queremos que el modelo pueda comprar.

### D6 · λ = 266 por defecto
Que el aumento de línea nunca salga **es lo que hace la puerta S4**, no un defecto del catálogo. Se presenta como el producto que el sistema sabe no ofrecer.

### D7 · `w_a = 0.3`, y el riesgo queda cerrado
Descomponiendo `V(w_a)` analíticamente, el signo de las cuatro ofertas es invariante para `w_a ∈ [0,1]`. Solo λ mueve el signo.

### D8 · El árbol de puntúa, la regresión explica
Coinciden en la clase principal el 89 % de las veces; el 11 % restante cae a explicación por regla, con marca en la respuesta. Se descartó SHAP: arrastra dependencias pesadas y devuelve 82 números en vez de una frase.

### D9 · Sin `class_weight='balanced'`
Medido: cuesta 10.07 pp de exactitud.

### D10 · Regresión logística para el momento
El árbol aporta +0.0011 de AUC. No compensa la complejidad.

### D11 · No se usan: abandono, sesiones, hora del día, espaciado entre avisos
Todas desmentidas con datos. El abandono es **anti**-predictivo: quien abandona la simulación de préstamo pide uno el 0.15 % de las veces; quien solo la mira, el 23.33 %.

### D12 · La sesión no existe en estos datos
1.01 eventos por sesión, mediana de intervalo 58 h. Se implementa igual porque el reto la pide, se muestra el histograma y se sustituye por recencia por pantalla.

### D13 · Cobertura 14.0 % / 86.0 %
Una cifra previa de 84.5 % incluía un producto fuera del catálogo. Recomputada con el catálogo real: 5,315 de 38,000 clientes reciben oferta.

### D14 · S5 y S7 se declaran no activas
No se fabrican casos para que se disparen. Se documenta y se dice.

### D15 · Los productos fuera de catálogo no se reportan como «sin señal»
Tienen su propio código. Un silencio por «sin señal» que en realidad es «no lo vendemos» sería mentir en la traza.

## Alternativas evaluadas y descartadas

**Modelo de mejor hora de envío.** Tres golpes: el rango horario del enganche es de 0.98 pp sin monotonía; el espaciado entre avisos no tiene efecto controlando por número de exposición; y el generador no tiene término de hora. Habría sido vender ruido.

**Extender el veto al préstamo.** Cuesta 6.5 pp más de ingreso y no mejora los días en negativo.

**Tasa de clic histórica como variable.** Aporta +0.0032 de PR-AUC y presenta paradoja de Simpson: marginalmente el signo se invierte, y controlando por número de exposición se vuelve positivo. Vale más como hallazgo que como variable.
