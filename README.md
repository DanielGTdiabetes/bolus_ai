# 🩸 Bolus AI

Asistente inteligente para la gestión de diabetes tipo 1. Calcula tus bolos de insulina, analiza fotos de comida con IA y mantén tu historial sincronizado con Nightscout.

## ✨ Características Principales

- **📸 Análisis de Comida por IA**: Estima carbohidratos, grasas y proteínas a partir de una foto.
- **⚖️ Báscula Bluetooth**: Conexión directa con básculas inteligentes (Prozis) para pesaje preciso.
- **📏 Calibración con Referencia**: ¿No tienes báscula? Coloca tu **pluma de insulina roja** (16.5cm) junto al plato y la IA la usará como referencia de tamaño.
- **⏱️ Bolo Dual/Extendido**: Sugerencias inteligentes de fraccionamiento de insulina para comidas grasas o lentas.
- **🔄 Integración Nightscout**: Lectura de glucosa en tiempo real y descarga de historial de tratamientos.
- **📊 Gestión de Basal**: Registro y análisis de dosis basales, patrones nocturnos y sugerencias de ajuste.

---

## 🚀 Despliegue Rápido

La forma más sencilla de tener tu propia instancia de Bolus AI es en **Render**. 

👉 **[Consulta la Guía Detallada de Instalación en Render](./RENDER_SETUP.md)**

---

## 🛠️ Configuración Local (Desarrolladores)

1. **Requisitos**: Docker y Docker Compose.
2. **Setup**:
   ```bash
   cp config/config.example.json config/config.json
   docker compose up --build
   ```
3. **Acceso**: `http://localhost:8000`
   - Usuario: `admin`
   - Password: `admin123`

---

## 🧩 Funciones Avanzadas

### 📏 Referencia de Tamaño (Truco del Bolígrafo)
Si habilitas el análisis de imagen, puedes colocar tu **pluma de insulina** (modelo NovoPen Echo Plus o similar, color rojo metálico) junto al plato. La IA sabe que mide exactamente **16.5 cm** y la usará para calibrar el volumen real de la comida, mejorando drásticamente la precisión cuando no hay báscula.

### ⚖️ Báscula de Cocina
El sistema es compatible con básculas Bluetooth. Puedes:
- Tarar el plato directamente desde la app.
- Pesar alimentos individualmente.
- "Añadir al plato" para que la IA sepa el peso exacto del ingrediente.

---

## 🔐 Seguridad y Usuarios

Para gestionar usuarios, contraseñas y accesos iniciales, consulta nuestro:
👉 **[Manual de Gestión de Usuarios](./USER_AUTH_GUIDE.md)**

---

## ⚖️ Descargo de Responsabilidad
Esta aplicación es una herramienta de apoyo y **no sustituye el criterio médico**. Los cálculos de la IA son estimaciones. Verifica siempre los datos antes de tomar cualquier decisión terapéutica.
