# 📖 Manual de Usuario - Bolus AI

Bolus AI es un asistente inteligente diseñado para facilitar el control de la diabetes tipo 1. Este manual detalla el funcionamiento de la aplicación, sus algoritmos y las medidas de seguridad integradas.

---

## 🧭 Guía de Menús y Navegación

La aplicación se organiza en 5 secciones principales accesibles desde la barra inferior:

### 1. 🏠 Inicio (Dashboard)
Es el centro de control. Aquí puedes ver:
- **Glucosa en tiempo real**: Valor actual y flecha de tendencia (conectado a Nightscout).
- **Insulina Activa (IOB)**: Cuánta insulina queda trabajando en tu cuerpo.
- **Acciones Rápidas**: Acceso directo a la Báscula Bluetooth, Registro de Glucosa o Modo Restaurante.
- **Actividad Reciente**: Listado de las últimas dosis e ingestas.

### 2. 📷 Escanear (Análisis de Comida)
Usa la cámara para identificar alimentos y estimar carbohidratos.
- **Referencia de Tamaño**: Si colocas tu pluma de insulina (roja, 16.5cm) al lado del plato, la IA la usará para calcular el volumen real de la comida.
- **Báscula**: Puedes conectar una báscula Bluetooth para pesar los ingredientes individualmente y obtener precisión absoluta.

### 3. 💉 Bolo (Calculadora)
El cerebro de la app. Calcula la dosis necesaria basándose en:
- Carbohidratos a ingerir.
- Glucosa actual.
- Insulina activa (IOB).
- Ejercicio planeado.
- Estrategia de absorción (Normal o Lenta/Dual).

### 4. 📉 Basal (Gestión de Insulina Lenta)
Herramientas para optimizar tu dosis basal:
- **Control al Despertar**: Registra tu glucosa matutina para evaluar si la basal de la noche anterior fue correcta.
- **Analizar Noche**: Escanea automáticamente tu Nightscout (00:00 - 06:00) en busca de hipoglucemias desapercibidas.
- **Evaluación de Cambios**: Si cambias tu dosis basal, la app comparará los 7 días anteriores vs. los 7 posteriores para decirte si el cambio fue efectivo.

### 5. ☰ Menú (Avanzado)
- **⏱️ Historial**: Registro completo de todos los tratamientos.
- **📊 Patrones**: Análisis detallado de tendencias por franjas horarias.
- **💡 Sugerencias**: Algoritmo de aprendizaje que sugiere mejores Ratios (CR) o Sensibilidades (ISF) basados en tus datos.
- **⭐ Favoritos**: Guarda tus comidas frecuentes para no tener que escanearlas cada vez.
- **👤 Perfil**: Configura tus dosis máximas, ratios y tipo de insulina.
- **⚙️ Ajustes**: Configuración técnica (Nightscout, modo oscuro, etc.).

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

---

## 🛡️ Medidas de Seguridad y Límites

Tu seguridad es lo más importante. Bolus AI incluye:

1.  **Límite de Bolo Máximo**: Configura en tu perfil una dosis máxima que la app nunca podrá superar por sí sola.
2.  **Límite de Corrección**: Capacidad máxima de corrección por glucosa alta para evitar bajadas bruscas.
3.  **Detección de Datos Caducados**: Si la glucosa de Nightscout tiene más de 10 minutos, la app **no realizará correcciones automáticas** y te pedirá una medición manual.
4.  **Alerta de Hipoglucemia**: Si tu glucosa es inferior a 70 mg/dL, el sistema bloqueará las sugerencias de insulina y te advertirá del riesgo.
5.  **Validación de IOB**: Antes de sugerir un micro-bolo en el Modo Restaurante, la app verifica si ya tienes insulina activa para evitar sobredosificaciones accidentales.

---

## ⚠️ Descargo de Responsabilidad Médico
Esta aplicación es una **herramienta de apoyo** a la decisión. Los cálculos son estimaciones basadas en algoritmos de IA y no deben sustituir el criterio clínico. **Verifica siempre los datos antes de administrarte insulina.**
