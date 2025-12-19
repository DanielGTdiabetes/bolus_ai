# 🏥 Plan de Mejoras: Experiencia del Paciente (Diabetic-Centric) v3

Este documento recoge las propuestas priorizadas por el usuario.

---

## 1. 🧠 Aprendizaje y Predicción (Prioridad Alta)
**Objetivo:** Que el sistema aprenda cómo sienta cada comida específica (no solo carbohidratos genéricos) para predecir fallos y sugerir ajustes.

**El Desafío:** Para aprender de la "Pizza", el sistema necesita saber que estás comiendo "Pizza", no solo "60g de carbohidratos".

**Solución: "Smart Input" en la Calculadora de Bolo**
*   **Campo de Texto Inteligente:** Un campo "¿Qué vas a comer?" en la pantalla principal de cálculo.
*   **Funcionalidad Híbrida (Buscador + Registro):**
    *   **Autocompletado (Buscador):** Si escribes "Macarr...", busca en tus **Favoritos** y rellena automáticamente los carbohidratos (ej: "Macarrones con Tomate - 65g").
    *   **Guardado Rápido:** Si escribes algo nuevo (ej: "Bocadillo Tortilla") y pones los hidratos a mano, al terminar te ofrece: *"¿Guardar en favoritos para la próxima?"*.
*   **Resultado:**
    *   Facilita la entrada de datos (menos tecleo si ya existe).
    *   Etiqueta el tratamiento con el nombre real de la comida.
    *   Alimenta al motor de IA para que la próxima vez diga: *"Ojo, con el Bocadillo de Tortilla sueles necesitar un 10% más"*.

---

## 2. 📍 Rotación de Sitios de Inyección (Body Map)
**El Problema:** Inyectarse siempre en el mismo sitio causa lipodistrofias y mala absorción.
**Propuesta:** Avatar visual para registrar y rotar zonas de inyección (muslos, abdomen, brazos).

---

## 3. 📦 Gestión de Suministros
**Propuesta:** Recordatorios de caducidad para sensores (14 días), catéteres (3 días) y plumas abiertas (30 días).

---

## 4. 📄 Informes y Modo Enfermedad
**Propuesta:** Informes tipo AGP para el médico y modo "Días Enfermos" para reglas de insulina más agresivas temporalmente.
