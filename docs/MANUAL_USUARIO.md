# 📖 Manual de Usuario - Bolus AI

Bolus AI es un asistente inteligente diseñado para facilitar el control de la diabetes tipo 1. Este manual detalla el funcionamiento de la aplicación, sus algoritmos y las medidas de seguridad integradas.

---

## 🧭 Guía de Menús y Navegación

La aplicación se organiza en 5 secciones principales accesibles desde la barra inferior:

### 1. 🏠 Inicio (Dashboard)
Es el centro de control. Aquí puedes ver:
- **Glucosa en tiempo real**: Valor actual, flecha de tendencia y una **Gráfica Avanzada** que superpone tu curva de glucosa con los bolos de insulina (azul) y carbohidratos (naranja) para ver el efecto post-prandial.
- **Feedback Visual (Toasts)**: Las confirmaciones de acciones aparecen como burbujas suaves en la parte inferior, mejorando la experiencia frente a las alertas antiguas.
- **Insulina Activa (IOB)**: Cuánta insulina queda trabajando en tu cuerpo.
- **Acciones Rápidas**: Acceso directo a favoritos, calculadora, báscula y alimentos.
- **Actividad Reciente**: Listado de las últimas dosis e ingestas.

### 2. 📷 Escanear (Análisis de Comida)
Usa la cámara para identificar alimentos y estimar carbohidratos.
- **Referencia de Tamaño**: Si colocas tu pluma de insulina (roja, 16.5cm) al lado del plato, la IA la usará para calcular el volumen real de la comida.
- **Báscula**: Puedes conectar una báscula Bluetooth para pesar los ingredientes individualmente y obtener precisión absoluta.

### 3. 💉 Bolo (Calculadora Inteligente)
El cerebro de la app. Calcula la dosis necesaria basándose en:
- **Smart Input**: Escribe qué vas a comer (ej: "Pizza") y el sistema buscará en tus favoritos para rellenar los carbohidratos automáticamente.
- **Simulación Predictiva**: Antes de confirmar, verás una **gráfica de futuro a 6 horas** que desglosa:
    - 🟣 **Curva Final**: Tu glucosa estimada.
    - 🟠 **Impacto Carbohidratos**: Cuánto subiría si no te pusieras insulina.
    - 🔵 **Impacto Insulina**: Cuánto bajaría solo por el efecto de la insulina y basal.
- **Insulina Activa (IOB)**: Para evitar acumulación.
- **Gestión Inteligente de Stock**: Si registras solo carbohidratos (sin insulina, ej: corrección de hipo), el sistema **NO** descontará agujas ni rotará el sitio de inyección.
- **Rotación de Sitios**: Te muestra un avatar visual (Abdomen) y te sugiere dónde pincharte hoy para evitar repetir el mismo sitio (lipodistrofia).

### 4. 📉 Basal (Gestión de Insulina Lenta)
Herramientas para optimizar tu dosis basal:
- **Gráfica 24h con Cobertura**: Visualiza tu curva de glucosa sobre tu nivel de basal estimado para detectar huecos de cobertura.
- **Soporte Dosis Partida**: Si te inyectas basal dos veces al día (mañana y noche), la app suma automáticamente las dosis del día para el historial y análisis.
- **Calculadora de Olvido**: ¿Se te pasó la hora? Pulsa en "¿Llegas tarde?" y la app calculará si debes ponerte la dosis competa o reducirla para no solapar con la de mañana.
- **Mapa Corporal Basal**: Avatar visual (Muslos/Glúteos) para rotar los sitios de inyección lenta.
- **Control al Despertar**: Registra tu glucosa matutina para evaluar si la basal de la noche anterior fue correcta.
- **Analizar Noche**: Escanea automáticamente tu Nightscout (00:00 - 06:00) en busca de hipoglucemias desapercibidas.
- **Evaluación de Cambios**: Si cambias tu dosis basal, la app comparará los 7 días anteriores vs. los 7 posteriores para decirte si el cambio fue efectivo.

### 5. ☰ Menú (Avanzado)
- **📦 Suministros (NUEVO)**: Control de inventario de consumibles.
    - **Agujas**: Se descuentan solas cada vez que registras una dosis. Tú solo tienes que darle a "+1 Caja" cuando compres.
    - **Sensores**: Control manual simple (+1 / -1).
- **⏱️ Historial**: Registro completo de todos los tratamientos.
- **📊 Patrones**: Análisis detallado de tendencias por franjas horarias.
- **📍 Mapa Corporal**: Vista completa del estado de tus sitios de inyección.
- **⭐ Favoritos**: Gestiona tus comidas guardadas.
- **👤 Perfil**: Configura tus dosis máximas, ratios y tipo de insulina.
- **⚙️ Ajustes**: Configuración técnica.

---

## 🍽️ Modo Restaurante (Sesión Inteligente)

Este modo está diseñado para situaciones donde no sabes exactamente qué te van a servir o cuánto vas a comer.

### Paso a paso:
1. **Escanear Carta**: Saca una foto al menú o escribe lo que piensas pedir. La IA hará una **estimación conservadora** de los carbohidratos totales esperados.
2. **Bolo Inicial**: Realiza un bolo para esa estimación.
3. **Fotos de los Platos**: Según lleguen los platos a la mesa, saca fotos. La IA irá sumando los carbohidratos **reales** servidos.
4. **Cierre y Ajuste**: Al terminar, pulsa "Terminar". La aplicación comparará lo que planeaste originalmente con lo que realmente comiste.
   - **Si comiste más**: Te sugerirá un "micro-bolo" de corrección.
   - **Si comiste menos**: Te avisará para que tomes unos pocos carbohidratos extra y evitar una hipoglucemia.

---

## 🧠 Lógica del Cálculo de Bolos

El cálculo se divide en varias fases matemáticas:

1.  **Dosis por Comida**: `Carbohidratos (g) / CR (Ratio de CH)`.
2.  **Dosis de Corrección**: `(Glucosa Actual - Glucosa Objetivo) / ISF (Sensibilidad)`.
3.  **Ajuste por IOB**: Se resta la insulina activa detectada en Nightscout para evitar el "apilamiento" de insulina.
4.  **Redondeo Inteligente (Techne)**:
    - Si la flecha de glucosa es **Ascendente**, la app redondea hacia arriba (ej: 2.3U -> 2.5U).
    - Si la flecha es **Descendente**, redondea hacia abajo (ej: 2.3U -> 2.0U).
5.  **Estrategia Dual/Cuadrada**: Para comidas con mucha grasa o proteína, puedes dividir el bolo en una parte inmediata y otra extendida en el tiempo.
6.  **Modo Postre (Ignorar IOB)**: Si decides comer un segundo plato o postre poco después de tu comida principal, puedes activar esta casilla.
    - Esto le dice a la app que NO reste la insulina activa (IOB) del primer plato.
    - **⚠️ Importante**: Si tu bolo anterior fue hace menos de 2 horas, la app te sugerirá esperar **15-20 minutos** antes de inyectar este segundo bolo para dar tiempo al vaciado gástrico y evitar una hipoglucemia por solapamiento.
7.  **Ajuste por Ejercicio**:
    - Si indicas actividad física (previa o planeada), el sistema reducirá el bolo total para prevenir hipoglucemias.
    - La reducción depende de la intensidad (Suave, Moderada, Intensa) y la duración, pudiendo llegar hasta un -75% en ejercicios intensos y prolongados.

---

## 🛡️ Medidas de Seguridad y Límites

Tu seguridad es lo más importante. Bolus AI incluye:

1.  **Calculadora de Olvido Basal**: Impide sobredosificación accidental si te pones la lenta con muchas horas de retraso.
2.  **Límite de Bolo Máximo**: Configura en tu perfil una dosis máxima que la app nunca podrá superar por sí sola.
3.  **Límite de Corrección**: Capacidad máxima de corrección por glucosa alta para evitar bajadas bruscas.
4.  **Detección de Datos Caducados**: Si la glucosa de Nightscout tiene más de 10 minutos, la app **no realizará correcciones automáticas** y te pedirá una medición manual.
5.  **Alerta de Hipoglucemia**: Si tu glucosa es inferior a 70 mg/dL, el sistema bloqueará las sugerencias de insulina y te advertirá del riesgo.
6.  **Validación de IOB**: Antes de sugerir un micro-bolo en el Modo Restaurante, la app verifica si ya tienes insulina activa para evitar sobredosificaciones accidentales.

---

## 🔍 Análisis ISF Inteligente (Ajustes)

El factor de sensibilidad (ISF) determina cuánto baja tu glucosa con 1 unidad de insulina. Este valor cambia con el tiempo y es difícil de calcular manualmente.

La nueva herramienta de **Análisis ISF** (en `Ajustes` -> `Análisis`) utiliza inteligencia artificial para auditar tu historial:

1.  **Detección de "Correcciones Limpias"**: Identifica momentos donde te pusiste insulina correcona (sin comida) y analiza qué pasó en las siguientes 4 horas, filtrando interferencias (comidas posteriores, ejercicio, etc).
2.  **Cálculo Real**: Mide cuánto bajó realmente tu glucosa por cada unidad.
3.  **Análisis por Franjas**: Te da resultados específicos para:
    - Madrugada (00-06h)
    - Mañana (06-12h)
    - Tarde (12-18h)
    - Noche (18-24h)
4.  **Sugerencias**:
    - Si detecta que tu ISF es **demasiado fuerte** (>15% de desvío), te sugerirá subir el número (para corregir menos agresivamente).
    - Si detecta que es **demasiado débil**, te sugerirá bajarlo.
    - Puedes ver la **evidencia** detallada de cada evento analizado para confiar en el resultado.

    - Puedes ver la **evidencia** detallada de cada evento analizado para confiar en el resultado.

---

## 9. 🤖 Sistema de Aprendizaje (Patrones)

Bolus AI aprende de tus datos históricos para sugerir cambios en tus Ratios (ICR/ISF). Ten en cuenta:

1.  **Periodo de Calentamiento**: El sistema necesita entre **7 y 14 días** de datos fiables para empezar a generar sugerencias precisas. Ignora las alertas de "Patrón detectado" durante la primera semana de uso.
2.  **Validación Capilar**: Ante cualquier sugerencia de cambio de Ratio, o si el sistema predice una hipoglucemia que no te cuadra, realiza siempre una **prueba de glucosa capilar** para confirmar. No te fíes ciegamente del sensor o del algoritmo al principio.
3.  **Modo Enfermedad**: Si estás enfermo, activa el "Modo Enfermedad" en tu Perfil. Esto evitará que el sistema aprenda datos "erróneos" (resistencia temporal a la insulina) que luego estropearían tus predicciones cuando te cures.

---

## 10. ⚠️ Descargo de Responsabilidad Médico
Esta aplicación es una **herramienta de apoyo** a la decisión. Los cálculos son estimaciones basadas en algoritmos de IA y no deben sustituir el criterio clínico. **Verifica siempre los datos antes de administrarte insulina.**
