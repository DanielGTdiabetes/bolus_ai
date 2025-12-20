# 🩸 Bolus AI

Asistente inteligente para la gestión de diabetes tipo 1. Calcula tus bolos de insulina, analiza fotos de comida con IA y mantén tu historial sincronizado con Nightscout.

---

## 📖 Documentación Detallada
Para una explicación completa de cómo funciona la aplicación, consulta nuestro:
👉 **[MANUAL DE USUARIO](./docs/MANUAL_USUARIO.md)** (Incluye explicación de menús, lógica de cálculo, Smart Input y Rotación de Sitios).

---

## ✨ Características Principales

- **📸 Análisis de Comida por IA**: Estima carbohidratos, grasas y proteínas a partir de una foto.
- **🧠 Smart Input (Nuevo)**: Autocompletado inteligente de comidas y aprendizaje de favoritos.
- **📍 Mapa Corporal (Nuevo)**: Registro visual y rotación automática de sitios de inyección (Abdomen, Muslos, Glúteos) con ilustraciones médicas.
- **⏰ Calculadora de Olvido (Nuevo)**: Herramienta de seguridad para recálculo de dosis basal tardía.
- **🍴 Modo Restaurante**: Seguimiento inteligente de comidas complejas con sugerencias de ajuste al terminar.
- **⚖️ Báscula Bluetooth**: Conexión directa con básculas inteligentes (Prozis) para pesaje preciso.
- **📏 Calibración con Referencia**: Usa tu **pluma de insulina roja** (16.5cm) como referencia de tamaño para medir comida.
- **⏱️ Bolo Dual/Extendido**: Sugerencias inteligentes de fraccionamiento de insulina.
- **🔄 Integración Nightscout**: Lectura de glucosa en tiempo real, IOB y descarga de historial.
- **📊 Gestión de Basal**: Registro de glucosa al despertar, escaneo nocturno de hipos y evaluación de efectividad de cambios de dosis.

---
## 💻 Ejecución Local (Recomendado Desarrollo)
Para trabajar en el proyecto sin consumir minutos de Render, usa nuestra guía de ejecución local con Backend (Python) y Frontend (Vite) separados.

👉 **[GUÍA DE EJECUCIÓN LOCAL](./GUIA_EJECUCION_LOCAL.md)**

---

## 🚀 Despliegue Rápido (Render)

La forma más sencilla de tener tu propia instancia de Bolus AI es en **Render**. 

👉 **[Consulta la Guía Detallada de Instalación en Render](./RENDER_SETUP.md)**

---

## 🧩 Funciones Destacadas

### 🧠 Smart Input (Aprendizaje)
El sistema aprende de tus comidas anteriores. Si escribes "Lentejas", la app recuperará automáticamente cuántos carbohidratos tenían la última vez y te permitirá ajustar la cantidad. Además, guarda un historial inteligente para futuras sugerencias de estrategia.

### 📍 Rotación de Sitios (Body Map)
Evita lipodistrofias usando el avatar visual. La app recuerda exactamente dónde te pinchaste la última vez (ej: "Muslo Izquierdo - Punto 2") y te sugiere el siguiente punto de rotación automáticamente.

### 📏 Truco del Bolígrafo (Calibración)
Si habilitas el análisis de imagen, puedes colocar tu **pluma de insulina** (modelo NovoPen Echo Plus o similar, color rojo metálico) junto al plato. La IA sabe que mide exactamente **16.5 cm** y la usará para calibrar el volumen real de la comida.

### 🍽️ Sesión Restaurante (Seguridad en Exterior)
El modo restaurante te permite planificar una comida desde el menú, realizar un bolo inicial y luego ir añadiendo fotos de los platos reales. Al final, la app calcula si el bolo fue suficiente o si necesitas un pequeño ajuste, siempre vigilando tu Insulina Activa (IOB).

---

## 🔐 Seguridad y Usuarios

Para gestionar usuarios, contraseñas y accesos iniciales, consulta:
👉 **[Manual de Gestión de Usuarios](./USER_AUTH_GUIDE.md)**

---

## ⚖️ Descargo de Responsabilidad
Esta aplicación es una herramienta de apoyo y **no sustituye el criterio médico**. Los cálculos de la IA son estimaciones. Verifica siempre los datos antes de tomar cualquier decisión terapéutica.
