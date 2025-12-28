# 📘 MANUAL COMPLETO DE USUARIO: BOLUS AI
**Versión Extendida**

Bienvenido a **Bolus AI**, tu sistema avanzado de ayuda a la decisión para la diabetes tipo 1.
Esta aplicación esLa nueva herramienta de **Análisis ISF** (en `Ajustes` -> `Análisis`) utiliza algoritmos estadísticos para auditar tu historial:tmos matemáticos y no deben sustituir el criterio clínico. **Verifica siempre los datos antes de administrarte insulina.**

Este manual detalla **cada función**, pantalla por pantalla, para que aproveches el 100% de su potencial.

---

## 📑 ÍNDICE DE CONTENIDOS
1.  **Pantalla de Inicio (Tu Cuadro de Mando)**
2.  **Calculadora de Bolos (Funciones Avanzadas)**
3.  **Escáner de Alimentos (IA y Báscula)**
4.  **Gestión de Insulina Basal & Sueño**
5.  **Modo Restaurante & Comidas Largas**
6.  **Análisis Inteligente (Patrones y Sugerencias)**
7.  **Gestión de Insumos (Material)**
8.  **Base de Datos y Favoritos**
9.  **Configuración y Perfil**
10. **Ejemplos Reales (Escenarios)**

---

## 1. 🏠 PANTALLA DE INICIO (Tu Cuadro de Mando)
El centro de control diseñado para darte información crítica en 1 segundo.

### A. Panel de Glucosa (El Hero)
*   **Número Grande:** Tu glucosa actual (mg/dL).
*   **Flecha:** Tendencia (Sube, Baja, Estable).
*   **Minutos:** Hace cuánto se recibió el dato (ej. "Hace 3 min").
*   **Círculo de Color:**
    *   🟢 **Verde:** En Rango (70-180).
    *   🟡 **Naranja:** Alerta (Alto/Bajo leve).
    *   🔴 **Rojo:** Peligro (Hipo/Hiper severa).

#### La Gráfica de Predicción (El "Futuro")
Toca el número de glucosa o la pequeña curva debajo para ver el gráfico detallado.
*   **Línea Punteada:** Predicción a 30-60 minutos. La app calcula tu velocidad actual + insulina activa.
*   **Sombra (Cono de Incertidumbre):** El margen de error. Sombra ancha = predicción menos segura.
*   **Avisos:** Si la línea futura toca la zona roja (<70), aparecerá un aviso de **"Riesgo Inminente"** para que comas antes de tener la hipoglucemia.
*   **Datos Clave (Debajo de la gráfica):**
    *   **Mínimo Estimado:** El valor más bajo calculado por el sistema.
    *   **Tiempo al Mínimo:** Cuántos minutos faltan para llegar a ese punto más bajo. (Vital para saber si tienes prisa por comer o si puedes esperar).
    *   **Glucosa Final:** Dónde acabarás dentro de 6 horas si no haces nada.

### B. Métricas Clave
Debajo de la glucosa verás 3 tarjetas:
1.  **💧 IOB (Insulin On Board):** Insulina Activa.
    *   *Qué es:* La insulina rápida que te pusiste en las últimas 3-4 horas y que **aún está trabajando**.
    *   *Uso:* Vital para no "sobre-corregirte". La app la resta automáticamente.
2.  **🍪 COB (Carbs On Board):** Carbohidratos Activos.
    *   *Qué es:* Comida que ingeriste y que aún se está digiriendo y pasando a la sangre.
3.  **💉 Último:** Dosis del último bolo y hace cuánto fue.

### C. Paneles Dinámicos (Solo aparecen cuando se necesitan)
*   **🚦 Bolo Dividido (U2):** Si usaste el modo "Pizza/Grasa", aquí verás la cuenta atrás para la segunda dosis. Te permite **"Recalcular"** o **"Cancelar"**.
*   **🍽️ Restaurante Activo:** Si hay una sesión de restaurante abierta, aparecerá aquí para añadir platos rápidamente.
*   **⚠️ Alertas de Insumos:** Si te quedan pocas agujas o el sensor va a caducar, verás un aviso aquí.

---

## 2. 🧮 CALCULADORA DE BOLOS (El Núcleo)
No es una calculadora normal. Es un "Cerebro".

### A. Entradas
*   **Glucosa:** Se rellena sola (Nightscout). Si está vacía o es vieja (>15 min), escríbela a mano.
*   **Carbohidratos:** Gramos totales.
*   **Plato (Opcional):** Escribe el nombre para guardarlo en el historial o aprender en el futuro y buscar en el listado de alimentos.

### C. Sincronización MyFitnessPal / Salud 📲
La app es capaz de leer los carbohidratos que registres en aplicaciones externas (Apple Health, MyFitnessPal, FatSecret) si tienes configurada una app de exportación (como Nightscout Uploader).

#### ¿Cómo Funciona?
1.  **Detección Automática:** Cuando la app detecta un nuevo registro de carbohidratos externo, aparecerá una **alerta verde** en la parte superior de la calculadora.
2.  **Modo Diferencia:**
    *   Si ya habías registrado una parte de la comida (ej. 45g) y ahora llega una actualización con el total (ej. 60g), la app te avisará.
    *   Te ofrecerá un botón para **"Usar Diferencia (+15g)"**. Así solo te pinchas por lo que te falta.
3.  **Regla de Colisión (Anti-Duplicados):**
    *   Si llegan dos datos casi a la vez (ej. el registro original de 45g y la corrección de 60g en menos de 5 minutos), el sistema inteligente **NO los suma** (no verás 105g).
    *   Automáticamente se queda con el valor **mayor** (60g) para los gráficos y cálculos de COB, asumiendo que es la corrección más reciente.

### D. Funciones Avanzadas (Los Modos)
#### 🍕 1. Modo Grasa/Proteína (Pizza, Burger, Asados)
Existen dos formas de gestionar las grasas:

**A. Planificado (Bolo Dual / Extendido):**
*   *Cuándo:* Antes de empezar a comer.
*   **Acción:** Activa el interruptor "Bolo Dual".
*   **Estrategia:** La app te propone dividir la dosis (ej. 60% Ahora + 40% en 2 horas).

**B. Reactivo (Corrección Tardía):** *¡NUEVO!*
*   *Cuándo:* Si a las 2-3 horas ves que tu glucosa empieza a subir inesperadamente (por la grasa).
*   **Acción:** En la calculadora, marca **"Solo Corrección"** y activa **"Ignorar IOB (Grasas)"**.
*   **Estrategia (Micro-bolos):** La app calculará la corrección necesaria sin restar la insulina de la comida anterior (porque asume que está "ocupada").
    *   *Seguridad:* Aplicará límites automáticos (1.0 - 1.5 U máximo) para que corrijas poco a poco cada 45-60 min sin peligro.

#### 🏃 2. Modo Ejercicio
*Actívalo si vas a moverte después de comer (caminar, gimnasio).*
*   **Intensidad:** Baja, Media, Alta.
*   **Duración:** Cuánto tiempo.
*   **Efecto:** Reduce la dosis (ej. -20% o -50%) para evitar la hipoglucemia durante el deporte.

#### 🧙 3. Estrategia de IOB ("Mago" vs "Loop")
La app gestiona la insulina activa de dos formas (configurable):
1.  **Modo Loop (Estándar):** Resta TODA la IOB del cálculo total. Es lo más seguro.
2.  **Modo Mago (Postres):** Si comes un postre, no resta la insulina de la comida anterior (porque esa insulina está ocupada con la comida anterior). Solo resta si te vas a corregir una glucosa alta.
Esta aplicación no es una simple calculadora; es un sistema que aprende, predice y te protege utilizando algoritmos estadísticos y reglas clínicas avanzadas.

---

## 3. 📸 ESCÁNER DE ALIMENTOS
Usa la Inteligencia Artificial (Gemini Vision) para estimar tu comida.

### Pasos
1.  **Foto:** Saca una foto cenital (desde arriba) del plato.
2.  **Análisis:** La IA identifica los ingredientes y estima el volumen.
    *   *Truco:* Pon un cubierto o tu mano al lado para que entienda el tamaño.
3.  **Edición:** Te mostrará una lista (ej. "Arroz: 150g, Pollo: 100g"). Puedes tocar cualquier número para corregirlo si tienes ojo experto.
4.  **Báscula Bluetooth:** Si tienes una báscula compatible conectada, el peso de la báscula aparecerá directamente en la pantalla al pesar el ingrediente.

---

## 4. 🌙 BASAL Y SUEÑO
Gestiona tu insulina lenta (Lantus, Levemir, Tresiba...).

### A. Registro Diario
Apunta tu dosis. La app crea un gráfico para ver si eres estable.

### B. Análisis "Al Levantarme" ☀️
**¡Importantísimo!** Pulsa este botón cada mañana al despertar.
*   La app analiza tu noche (00:00 - 08:00).
*   **Detecta:**
    *   Si subiste mucho (Fenómeno del Alba).
    *   Si bajaste (Hipo nocturna).
    *   Si tuviste efecto rebote (Somogyi).
*   **Resultado:** Te dirá si tu dosis basal es correcta o si deberías hablar con tu médico.

### C. BodyMap (Rotación) 🧍
Un muñeco interactivo.
*   Toca dónde te pinchaste.
*   La app recuerda tus últimos sitios y te sugiere **rotar** para evitar lipodistrofias (bultos) que estropean la absorción.

---

## 5. 🍽️ MODO RESTAURANTE
Para comidas largas, bodas o eventos donde no sabes qué vendrá después.

1.  **Iniciar:** En Menú -> Restaurante. Estimas un total aproximado (ej. "Comeré unas 60g").
2.  **Bolo Inicial:** La app te da una dosis pequeña de seguridad.
3.  **Añadir Platos:** A medida que llegan los platos, sácales foto o añádelos. La app suma y te dice si necesitas refuerzo ("micro-bolo").
4.  **Cierre:** Al final, la app hace balance (Total Comido - Total Insulina) y te sugiere una corrección final si hace falta.

---

## 6. 🧠 ANÁLISIS INTELIGENTE (Tu "Coach")
La app revisa tus datos cada noche.

### A. Patrones 📉
Detecta tendencias repetitivas.
*   *"Siempre estás alto después del desayuno (11:00)"*.
*   *"Sueles tener hipoglucemias los domingos noche"*.

### B. Sugerencias (El Doctor Virtual) 💡
Si un patrón se repite mucho, la app genera una **Sugerencia de Cambio de Terapia**.
*   *Ejemplo:* "Baja tu ratio del desayuno de 10 a 9".
*   **Acciones:**
    *   **Aceptar:** Guarda el cambio en tu configuración.
    *   **Rechazar:** Ignora si fue una semana atípica.
*   **Historial:** En la pestaña "Aceptadas" puedes ver todo lo que cambiaste y **Borrar** cambios si te arrepientes.

### C. Análisis ISF (Sensor de Sensibilidad)
Mide cuánto te baja realmente 1 unidad de insulina.
*   **¡OJO!** Solo funciona con datos "limpios" (Corrección aislada, sin comida, sin insulina previa).
*   Si ves "Faltan datos", es normal. Significa que siempre te corriges comiendo. Intenta corregirte en ayunas un par de veces para calibrarlo.

### D. Autosens (Sensibilidad Automática) 🤖
Es tu **piloto automático de sensibilidad**.

#### ¿Qué hace?
Revisa tu glucosa de las últimas 24 horas y detecta si hoy estás **Resistente** (necesitas más insulina) o **Sensible** (necesitas menos).

#### ¿Cómo funciona?
*   Si detecta **Resistencia** (ej. estrés, enfermedad, sedentarismo): La app **bajará tu ISF y Ratio** temporalmente para que los próximos bolos sean más fuertes (+10%, +20%...).
*   Si detecta **Sensibilidad** (ej. deporte intenso ayer): Hará los bolos más suaves para evitar hipoglucemias.

#### ¿Dónde lo veo?
*   **Calculadora:** Al calcular un bolo, verás un aviso: *"🔍 Autosens: Factor 1.2 (Resistencia +20%)"*. El ISF efectivo ya estará ajustado.
*   **Gráfica de Predicción:** La curva futura ya tendrá en cuenta este factor. Si estás resistente, la curva bajará más despacio.

#### Seguridad
*   Tiene límites estrictos (mínimo 0.7, máximo 1.2 o 1.3 según config).
*   Ignora datos "sucios" (si tenías comida activa o el sensor fallaba).
*   Si tienes dudas, puedes desactivarlo desde **Ajustes > Perfil**.

---

## 7. 📦 GESTIÓN DE INSUMOS
Evita quedarte sin material.
En **Menú -> Insumos**:
*   **Control de Stock:** Apunta cuántas cajas de agujas, sensores y reservorios tienes.
*   **Alertas:** Configura avisos (ej. "Avísame cuando queden 5 agujas").

---

## 8. 🗂️ BASE DE DATOS Y FAVORITOS
### Buscador (Lupa)
*   Busca cualquier alimento (pan, manzana, Big Mac).
*   Funciona **Offline** (sin internet) con una base de datos interna enorme.

### Favoritos (Estrella)
*   Guarda tus platos recurrentes (ej. "Mi Desayuno de Campeones").
*   Guarda los Carbs exactos y la foto.
*   Úsalos en la calculadora con un solo toque desde "Acciones Rápidas".

---

## 9. ⚙️ CONFIGURACIÓN Y PERFIL
### A. Perfil Clínico
Aquí están tus números sagrados.
*   **Ratios (ICR):** Cuántos gramos cubre 1 unidad.
*   **Sensibilidad (ISF):** Cuánto baja 1 unidad.
*   **Objetivo:** A qué valor quieres llegar (ej. 100).
*   **Duración Insulina (DIA):** Cuánto dura el efecto en tu cuerpo (habitualmente 4 horas).

### B. Configuración Nightscout
Para conectar con tu sensor Dexcom/Libre en la nube.
*   **URL:** Tu dirección de Nightscout (ej. `https://mi-ns.herokuapp.com`).
*   **Token:** Tu clave de acceso (API Secret).

### C. Modo Enfermo (Sick Mode) 🤒
(Suele estar en el Perfil o Cabecera).
*   Actívalo cuando tengas gripe o fiebre.
*   **Efecto:** Aumenta temporalmente tus dosis (ej. +20%) porque la enfermedad crea resistencia a la insulina.

---

### D. Configuración Avanzada (Warsaw & Autosens)
Desde la pestaña "Cálculo" en Ajustes, puedes afinar el comportamiento automático.

#### Método Warsaw (Grasas/Proteínas)
Define cuándo y cuánto corregir por comidas grasas.
*   **Umbral de Disparo (Kcal):** Mínimo de energía extra (grasa+proteína) para que la app sugiera bolo doble.
    *   *Por defecto:* **300 kcal** (aprox. 33g de grasa). Esto evita avisos en desayunos sanos normales.
*   **Factor de Seguridad:** Porcentaje de la grasa que se cubre con insulina.
    *   *Por defecto:* **0.1 (10%)**. Un inicio muy conservador para evitar hipoglucemias tardías. Usuarios expertos pueden subirlo a 0.5 (50%) si su basal lo requiere.

---

### D. Configuración Avanzada (Warsaw & Autosens)
Desde la pestaña "Cálculo" en Ajustes, puedes afinar el comportamiento automático.

#### Método Warsaw Adaptativo (Grasas/Proteínas) 🧠
Define cómo la app gestiona la insulina necesaria para las grasas y proteínas. Ahora el sistema es inteligente y se adapta al tamaño de la comida.

*   **Umbral de Disparo (Kcal):** Mínimo de energía grasa/proteica para considerar la comida "copiosa" y activar el Bolo Dual.
    *   *Por defecto:* **300 kcal** o **500 kcal**.
    *   **Bajo el umbral:** La insulina extra se suma al bolo inmediato (Bolo Simple) para no complicarte la vida en comidas normales.
    *   **Sobre el umbral:** La app sugiere dividir la dosis (Bolo Dual) para evitar picos tardíos.

*   **Factores de Seguridad (Intensidad):**
    Puedes definir dos niveles de agresividad diferentes:
    1.  **Factor Estándar (Bolo Simple):** Se usa para el día a día (pollo, pescado, huevos).
        *   *Recomendado:* **0.1 (10%)**. Cubre solo un poco para mantener la línea plana sin riesgo.
    2.  **Factor Dual (Bolo Copioso):** Se usa solo cuando se supera el umbral (hamburguesas, pizzas, asados).
        *   *Recomendado:* **0.2 o 0.3 (20-30%)**. Al ser mucha grasa, se requiere más insulina para vencer la resistencia temporal.


---

# 🌟 Ejemplos Prácticos de Uso

### 🏠 1. Comer en Casa (Día Normal)
Estás en tu cocina y vas a comer un plato de lentejas y un yogur.
1.  **Escáner:** Abres la app, vas a Escáner y sacas foto al plato.
2.  **Confirmar:** La app dice "Lentejas estofadas (60g Carbs)". Tú sabes que te has puesto poco, así que corriges a **45g** manualmente.
3.  **Calcular:** Pulsas calcular.
4.  **Bolo Normal:** Como es comida sana y normal, te sugiere **4.5 Unidades**.
5.  **Acción:** Te las pones, aceptas en la app y a comer. ¡Listo!

### 🍔 2. Hamburguesería / Comida Rápida (Mucha Grasa)
Vas al Burger King o comes pizza.
*   **Problema:** La grasa de la carne o el queso hará que la glucosa suba **muy tarde** (a las 3-4 horas), cuando la insulina rápida normal ya se ha ido.
*   **Solución Bolus AI:**
    1.  Calculas los carbs (ej. 100g).
    2.  En la calculadora, activas el interruptor **"🍕 Grasa/Proteína"** (o "Bolo Lento").
    3.  **Estrategia:** La app te dirá: *"Ponte el 60% ahora (6 U) y el resto (4 U) dentro de 2 horas"*.
    4.  **Acción:** Te pones las 6 U ahora y comes.
    5.  **Aviso:** A las 2 horas, la pantalla de inicio te mostrará el aviso del **Bolo Dividido**.
        *   Entras y pulsas **"Recalcular"**.
        *   ¿Estás bajando? --> La app te dirá que NO te pongas la segunda parte.
        *   ¿Estás subiendo? --> Te dirá que te pongas las 4 U restantes para frenar el subidón tardío de la grasa.

### 🍽️ 3. Restaurante "A la Carta" (Cena de Empresa/Navidad)
Una cena larga. Pica-pica, luego un segundo, luego postre, copa... Dura 3 horas.
*   **Problema:** No sabes todo lo que vas a comer desde el principio. Si te pinchas todo al inicio, te dará una hipoglucemia antes del segundo plato.
*   **Modo Restaurante:**
    1.  En la app, ve a **Menú -> Modo Restaurante**.
    2.  **Inicio:** Dile: *"Creo que comeré unas 80g en total"*. La app te sugerirá un **Bolo Inicial** pequeño (ej. 3 U) para cubrir los entrantes y el pan.
    3.  **Durante la cena:** Sigue comiendo tranquilo.
    4.  **Plato Principal:** Llega el asado o el pescado. Añades el plato en la sesión activa. La app te dice si necesitas un refuerzo o si vas bien con lo del principio.
    5.  **Final:** Al terminar, cierras la sesión. La app mira tu glucosa final y te dice si necesitas una corrección final para irte a dormir perfecto.

### 🍰 4. El "Postre Sorpresa"
Has comido bien, te has puesto tu insulina... y de repente, a los 45 minutos, sacan una tarta que no esperabas.
*   **Error:** Pincharte "a ojo" la dosis completa de la tarta sin pensar.
*   **Solución:**
    1.  Abre la calculadora RÁPIDO.
    2.  Mete los carbs de la tarta (ej. 30g).
    3.  **Importante:** La app verá que tienes **Insulina Activa (IOB)** de la comida anterior.
    4.  **Cálculo Inteligente:** En lugar de mandarte la dosis completa, la app restará lo que te sobra de la comida anterior para evitar que se te acumule (Stacking).
    5.  Te dirá: *"Para la tarta necesitas 3 U, pero como te sobra 1 U activa de la comida, ponte solo **2 U**"*. ¡Salvado de la hipoglucemia!

### 📈 5. La Subida Tardía (El "Micro-Bolo" de Rescate)
Cenaste pizza o comida grasa hace 3 horas. Te pusiste tu bolo normal. Todo iba bien, pero de repente... ¡tu glucosa se dispara a 180 y subiendo ↗️!

*   **Error:** Usar la calculadora normal. Te dirá "0.0 U sugeridas" porque aún tienes algo de insulina activa (IOB) de la cena.
*   **Solución (Modo Microbolos):**
    Este es tu "Plan C" para cuando la grasa gana la batalla a la insulina inicial.

    1.  Abre la calculadora. Pon Glucosa: 180.
    2.  Marca ☑️ **Solo Corrección**.
    3.  Marca ☑️ **Modo Microbolos**.
    4.  **Cálculo:** La app sugerirá una pequeña dosis de rescate (ej. 0.5 o 1.0 U) ignorando parcialmente la insulina activa, porque entiende que no es suficiente para la grasa que está entrando.
    
    **💡 Ejemplo Práctico: Cena de Nochevieja**
    1.  **21:00 (Inicio):** Usas Bolo Dual. Te pones 6 U ahora y programas 4 U para luego.
    2.  **23:30 (2ª Parte):** Te pones las 4 U restantes.
    3.  **01:30 (El Problema):** Pasado el tiempo, la glucosa sigue alta en 180 ➡️. Las 4 U no pudieron con todo el turrón. 
        *   Si usas la calculadora normal: *"Tienes IOB. Espera"*. (Te deja vendido).
        *   **Con Modo Microbolos:** *"Bolo hace 2 horas. Te calculo **1.0 U** extra de rescate"*.
    
    **⚠️ Reglas de Seguridad Automáticas:**
    *   **Bloqueo de Tiempo:** Si te has pinchado hace menos de **75 min**, el sistema **NO** te dejará ponerte micro-bolos. (Te dirá: *"⛔ Espera, bolo reciente"*).
    *   **Alcohol:** Si marcas modo Alcohol, la dosis sugerida se reduce a la **mitad** (50%) para evitar bajones peligrosos de madrugada.
    *   **Redondeo Seguro:** La dosis siempre se redondeará al paso de tu bolígrafo (ej. 0.5 o 1.0) para que sea real y accionable.

---
*Bolus AI está diseñado para ser tu copiloto. Siempre consulta con tu médico antes de hacer cambios drásticos en tu terapia.*
