# 🩸 Bolus AI

Asistente inteligente para la gestión de diabetes tipo 1. Calcula tus bolos de insulina, analiza fotos de comida con IA y mantén tu historial sincronizado con Nightscout.

---

## 📖 Documentación Detallada
Para una explicación completa de cómo funciona la aplicación, consulta nuestro:
👉 **[MANUAL DE USUARIO](./docs/MANUAL_USUARIO.md)** (Incluye explicación de menús, lógica de cálculo, Smart Input y Rotación de Sitios).

---

## ✨ Características Principales

- **🤖 Autosens (Nuevo)**: Detección automática de resistencia/sensibilidad en tiempo real (ajusta tus ratios si tienes un mal día).
- **🕸️ Shadow Labs (Experimental)**: Pruebas de algoritmos de absorción en segundo plano sin riesgo (Auto-ISF, curvas personalizadas).
- **🧠 Motor de Aprendizaje**: Sugerencias clínicas basadas en tus patrones (ej. "Baja tu ratio del desayuno").
- **📸 Análisis de Comida por IA**: Estima carbohidratos, grasas y proteínas a partir de una foto.
- **📍 Mapa Corporal**: Rotación de sitios de inyección con memoria visual.
- **⏰ Calculadora de Olvido**: Seguridad para recálculo de basal tardía.
- **🍴 Modo Restaurante**: Seguimiento inteligente de comidas complejas.
- **⚖️ Báscula Bluetooth**: Conexión directa con básculas inteligentes.
- **⏱️ Bolo Dual/Extendido/Micro**: Estrategias avanzadas para grasas, proteínas y correcciones post-pandriales ("Dessert Mode").
- **🔄 Integración Nightscout**: Lectura en tiempo real + Subida de Tratamientos.
- **📊 Gestión de Basal**: Análisis de "Amanecer" y eficacia nocturna.

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

### 🤖 Autosens & Sugerencias
Olvídate de calcular si hoy estás más resistente. La app analiza las últimas 24h y ajusta dinámicamente tu ISF y Ratios (+10%, -5%...) para clavar el bolo. Además, el **Motor de Aprendizaje** revisa tus noches y comidas recurrentes para sugerirte cambios permanentes en tu terapia ("Tu desayuno de las 8am siempre acaba alto, sube el ratio").

### 🍽️ Sesión Restaurante (Seguridad en Exterior)
El modo restaurante te permite planificar una comida desde el menú, realizar un bolo inicial y luego ir añadiendo fotos de los platos reales. Al final, la app calcula si el bolo fue suficiente o si necesitas un pequeño ajuste, siempre vigilando tu Insulina Activa (IOB).

---

## 🔐 Seguridad y Usuarios

Para gestionar usuarios, contraseñas y accesos iniciales, consulta:
👉 **[Manual de Gestión de Usuarios](./USER_AUTH_GUIDE.md)**

---

## ⚖️ Descargo de Responsabilidad
Esta aplicación es una herramienta de apoyo y **no sustituye el criterio médico**. Los cálculos de la IA son estimaciones. Verifica siempre los datos antes de tomar cualquier decisión terapéutica.
