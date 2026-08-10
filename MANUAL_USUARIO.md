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
5.  **Comidas Largas y Bolos Divididos**
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
*   **Línea Punteada:** Representa tu glucosa prevista.
*   **Inteligencia de Contraste (Trust the Bolus) 🧠:** La gráfica no es solo un dibujo; entiende lo que has hecho.
    *   **Validación:** Si te has puesto un bolo mucho mayor que los hidratos (ej. para cubrir mucha proteína), la gráfica lo detecta y dice: *"Entendido, el sobrante es para la proteína (+Xg Auto-ajuste)"*. La curva se mostrará estable.
    *   **Auditoría de Seguridad ⚠️:** Si te pasas de frenada y pones insulina que no cabe ni sumando proteínas ni grasas, la gráfica te avisará con un mensaje rojo: *"Posible exceso de insulina"* y mostrará la caída real prevista.
*   **Precisión Horaria:** El simulador usa exactamente tus mismos ratios (ISF y CR) según el **Horario de Comidas** que tengas configurado, igual que la calculadora.
*   **Datos Clave:** Mínimo Estimado, Pico de Glucosa y Glucosa Final.

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
4.  **Webhook Directo (MyFitnessPal / Bridge sin JWT):**
    *   Configura la URL de destino como `https://TU_HOST/api/integrations/nutrition?key=TU_CLAVE` usando la clave almacenada en la variable de entorno `NUTRITION_INGEST_KEY`.
    *   Ejemplo rápido:

        ```bash
        curl -X POST 'https://tu-host/api/integrations/nutrition?key=XXXX' \
          -H 'Content-Type: application/json' \
          -d '{"carbs":10,"fat":0,"protein":0,"fiber":0,"date":"2026-01-06T12:00:00Z"}'
        ```

    *   Sin la `key` o con una clave incorrecta, la API responde `401` en JSON (`{"success":0,"error":"Authentication required for nutrition ingest"}`) y nunca redirige a HTML.

### D. Absorción Inteligente (🤖 Modo Auto)
Ya no necesitas elegir manualmente si la comida es "Rápida" o "Lenta". El sistema lo decide por ti analizando:
*   **Macros:** Si detecta >15g de grasa/proteína o >5g de fibra, activa el modo **Lento** (Curva de 4-5 horas).
*   **Falta de información:** Si no hay datos, usa el modo **Medio** (3h) con confianza baja.
*   **Ajuste Manual:** Si crees que el sistema se equivoca, pulsa el botón **"Ajustar"** en la calculadora para forzar un perfil específico solo para ese bolo.

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

#### 🍷 3. Modo Alcohol
*Seguridad para cuando bebes alcohol (cañas, vino, copas).*
*   **¿Qué hace?**
    *   **Bolo Dual (Si está activo):** Fuerza automáticamente la duración de la segunda parte a **4 horas (240 min)**. Esto adapta la insulina a la digestión lenta que provoca el alcohol y evita hipoglucemias tempranas.
    *   **Techne (Redondeo Inteligente):** Se **desactiva**. El sistema será más conservador y no redondeará hacia arriba aunque tu glucosa esté subiendo, para evitar excesos.
    *   **Dosis Total:** **NO reduce la cantidad** total de insulina automáticamente (a diferencia del deporte). Si quieres ponerte menos, debes bajar los hidratos manualmente.

#### 🧙 4. Estrategia de IOB
La app usa una única regla de seguridad: la insulina activa reduce solamente una corrección positiva de glucosa. No reduce automáticamente la cobertura de hidratos nuevos. Si la glucosa está por debajo del objetivo, el ajuste negativo sí puede reducir prudentemente el bolo de comida.
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

## 5. 🍽️ COMIDAS LARGAS
El antiguo modo Restaurante fue retirado. Para un plato adicional, introduce únicamente sus hidratos nuevos en la calculadora normal. El motor mantendrá su cobertura aunque exista IOB y seguirá evitando apilar correcciones. Para comidas grasas conocidas desde el inicio, utiliza el bolo dividido.

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
*   **Bot Proactivo:** El asistente de Telegram ahora vigila tu stock y te enviará un mensaje automático si detecta que te queda poco material (ej. < 10 agujas o < 3 sensores).

---

## 7b. 🚨 MODO EMERGENCIA (Calculadora Manual)
Pensado para el "Apocalipsis Digital". Si te quedas sin internet, se caen los servidores o Nightscout deja de funcionar.
*   **Acceso:** Menú Principal -> **Modo Emergencia** (icono rojo).
*   **Funcionamiento Offline:** Esta herramienta vive en tu teléfono. Funciona incluso en "Modo Avión" o en medio del desierto.
*   **Calculadora Pura:** Tú introduces todos los datos (Glucosa, Carbs, IOB manual) y la app hace las matemáticas por ti (teniendo en cuenta tu Sensibilidad y Ratio).
*   **Seguridad:** Al no haber conexión, la app **NO puede verificar** los datos con la nube. Tú eres el responsable de asegurar que lo que escribes es correcto.

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

### C. Dexcom Share (Cloud Mirror) 📡
Si no tienes Nightscout o quieres una conexión directa de respaldo:
*   **Habilitar Dexcom Share:** Activa el interruptor en Ajustes.
*   **Credenciales:** Introduce tu usuario y contraseña de Dexcom.
*   **Servidor:** Selecciona "US" si estás en Estados Unidos o "Global" para el resto del mundo.
*   **Uso:** La app leerá tu glucosa directamente de los servidores de Dexcom en tiempo real. Es ideal como redundancia si tu Nightscout falla.

### C. Modo Enfermo (Sick Mode) 🤒
(Suele estar en el Perfil o Cabecera).
*   Actívalo cuando tengas gripe o fiebre.
*   **Efecto:** Aumenta temporalmente tus dosis (ej. +20%) porque la enfermedad crea resistencia a la insulina.

---

### D. Configuración Avanzada (Cálculo)
Desde la pestaña "Cálculo" en Ajustes, puedes afinar el comportamiento automático.

#### 1. Método Warsaw Adaptativo (Grasas/Proteínas) 🧠
Define cómo la app gestiona la insulina necesaria para las grasas y proteínas.

*   **Umbral de Disparo (Kcal):** Mínimo de energía grasa/proteica para considerar la comida "copiosa".
    *   *Por defecto:* **300-500 kcal**.
    *   **Bajo el umbral:** Se suma al bolo inmediato (Bolo Simple) para no complicar el día a día.
    *   **Sobre el umbral:** La app sugiere dividir la dosis (Bolo Dual / Extendido).

*   **Factores de Seguridad (Intensidad):**
    *   **Factor Simple:** Para comidas normales (pollo, huevos). Defecto **0.1**.
    *   **Factor Dual:** Para banquetes (pizzas, asados). Defecto **0.2-0.3**.
    *   *Nota:* Si decides ponerte más insulina manualmente, la Gráfica de Predicción lo detectará y "subirá" este factor automáticamente para validarte.

#### 2. Deducción de Fibra 🥗
Para dietas ricas en fibra (que no se absorbe como glucosa).
*   **Restar Fibra:** Si activas esto, la app restará la fibra de los hidratos totales.
*   **Umbral Mínimo:** Solo resta si la comida tiene más de **5g** de fibra (para ignorar trazas).
*   **Factor:** Generalmente se resta el **50%** o el **100%** de la fibra (Configurable).
*   *Excepción:* Si hay tanta fibra como hidratos (ej. salvado puro), la app deja de restar y sugiere un perfil de absorción Lento.

---

## 10. 🎯 CALIBRACIÓN AVANZADA DE LA PREDICCIÓN
*(Para usuarios expertos que quieren afinar la "Bola de Cristal")*

La gráfica de predicción (línea violeta) es el corazón de Bolus AI. Si notas que la predicción no coincide con la realidad, suele ser porque los **tiempos** configurados no coinciden con tu metabolismo real. Aquí tienes cómo ajustarlo.

### A. Diagnóstico de la "Duración de Insulina" (DIA) 💉
Este es el ajuste más importante y el error más común. Por defecto viene en **4 horas**.

#### Síntoma: "El Falso Rebote"
*   **Situación:** Te pusiste insulina hace 4 horas. Tu glucosa real (línea sólida) está bajando o estable y todo va bien.
*   **Problema:** De repente, la gráfica de predicción (línea punteada) muestra que vas a empezar a **SUBIR** (rebotar) en la próxima hora, aunque tú sabes que no has comido nada nuevo.
*   **Causa:** El sistema cree que tu insulina se ha terminado y ha dejado de hacer efecto ("se ha apagado el motor"), pero tu cuerpo aún tiene un poco de efecto residual. Como el sistema cree que ya no hay freno, cualquier pequeña digestión pendiente (proteínas, grasas) empuja la gráfica hacia arriba.

#### Solución:
1.  Ve a **Ajustes -> IOB / Insulina**.
2.  Busca **"Duración de Insulina (DIA)"**.
3.  **Súbelo**: Cambia de 4.0 a **4.5** o **5.0 horas**.
4.  **Efecto:** Le dices al sistema que la insulina tiene una "cola larga". Eso "cubrirá" el final de la digestión y la gráfica de predicción se aplanará, eliminando el falso rebote.

### B. Ajuste de Grasas y Proteínas (Warsaw) 🥓
El sistema convierte automáticamente los chuletones, huevos y quesos en "glucosa lenta" para predecir subidas tardías.

#### Cómo funciona la Clasificación:
*   **Comida Ligera (< 20g Grasa+Prot):** Absorción rápida (2h).
*   **Comida Media (20g - 60g Grasa+Prot):** Absorción media (3-4h). *La mayoría de platos de carne/pescado*.
*   **Comida Pesada (> 60g Grasa+Prot):** Absorción lenta (6h+). *Pizzas, hamburguesas dobles, cocidos*.

#### Síntoma: "El Pesimismo Eterno"
*   **Problema:** Has comido un filete. Han pasado 4 horas y ya estás bien, pero la gráfica sigue diciendo que subirás hasta el infinito.
*   **Causa:** El sistema ha clasificado tu comida como "Pesada" y cree que seguirá soltando glucosa durante 2 horas más.
*   **Solución:** Confía en las actualizaciones automáticas del algoritmo (ya ajustado para ser menos agresivo), o revisa si has exagerado la cantidad de grasas en el registro.

### C. Referencia de Basal (El "Modo Olvido") 📉
El sistema vigila tu basal para saber si estás cubierto.

*   **Si tienes basal activa (>5%):** El sistema confía en ti. Asume que tu basal es correcta (incluso si te pusiste un poco menos por deporte) y no altera la gráfica. **Predicción Neutra**.
*   **Si NO tienes basal (0%):** El sistema detecta "Peligro". Asume que se te ha olvidado pincharte y predice una **SUBIDA** constante (deriva) para alertarte.

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

### 🍽️ 3. Cena prolongada
Calcula cada plato cuando vaya a consumirse e introduce solamente sus hidratos nuevos. La IOB anterior no se interpreta como cobertura automática de ese plato. Si además hay glucosa alta, esa misma IOB sí reduce o elimina la corrección adicional.

### 🍰 4. El "Postre Sorpresa"
Has comido bien, te has puesto tu insulina... y de repente, a los 45 minutos, sacan una tarta que no esperabas.
*   **Error:** Pincharte "a ojo" la dosis completa de la tarta sin pensar.
*   **Solución:**
    1.  Abre la calculadora RÁPIDO.
    2.  Mete los carbs de la tarta (ej. 30g).
    3.  **Importante:** La app verá que tienes **Insulina Activa (IOB)** de la comida anterior.
    4.  **Cálculo Inteligente:** En lugar de mandarte la dosis completa, la app restará lo que te sobra de la comida anterior para evitar que se te acumule (Stacking).
    5.  La cobertura de los 30 g nuevos se mantiene; la IOB solo se aplicará si también existe una corrección positiva.

### 📈 5. Subida tardía
Usa **Solo corrección**. La calculadora aplicará toda la IOB activa a la corrección positiva y recomendará insulina adicional únicamente si la corrección calculada supera esa IOB. Ya no existe un modo que permita ignorarla.

---
*Bolus AI está diseñado para ser tu copiloto. Siempre consulta con tu médico antes de hacer cambios drásticos en tu terapia.*
