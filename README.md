# 🩸 Bolus AI

Asistente inteligente para la gestión de diabetes tipo 1. Calcula tus bolos de insulina, analiza fotos de comida con IA y mantén tu historial sincronizado con Nightscout.

---

## 📖 Documentación Detallada
Para una explicación completa de cómo funciona la aplicación, consulta nuestro:
👉 **[MANUAL DE USUARIO](./docs/MANUAL_USUARIO.md)** (Incluye explicación de menús, lógica de cálculo y seguridad).

---

## ✨ Características Principales

- **📸 Análisis de Comida por IA**: Estima carbohidratos, grasas y proteínas a partir de una foto.
- **🍴 Modo Restaurante**: Seguimiento inteligente de comidas complejas con sugerencias de ajuste al terminar.
- **⚖️ Báscula Bluetooth**: Conexión directa con básculas inteligentes (Prozis) para pesaje preciso.
- **📏 Calibración con Referencia**: ¿No tienes báscula? Coloca tu **pluma de insulina roja** (16.5cm) junto al plato y la IA la usará como referencia de tamaño.
- **⏱️ Bolo Dual/Extendido**: Sugerencias inteligentes de fraccionamiento de insulina para comidas grasas o lentas.
- **🔄 Integración Nightscout**: Lectura de glucosa en tiempo real, IOB y descarga de historial.
- **📊 Gestión de Basal**: Registro de glucosa al despertar, escaneo nocturno de hipos y evaluación de efectividad de cambios de dosis.

---

## 🚀 Despliegue Rápido (Render)

La forma más sencilla de tener tu propia instancia de Bolus AI es en **Render**. 

👉 **[Consulta la Guía Detallada de Instalación en Render](./RENDER_SETUP.md)**

---

## 🧩 Funciones Destacadas

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
