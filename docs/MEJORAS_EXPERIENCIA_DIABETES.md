# 🏥 Plan de Mejoras: Experiencia del Paciente (Diabetic-Centric) v3

Este documento recoge las propuestas priorizadas por el usuario.

---

## 1. 🧠 Aprendizaje y Predicción (Prioridad Alta)
**Objetivo:** Que el sistema aprenda cómo sienta cada comida específica para predecir fallos y sugerir ajustes.

**El Desafío:** Para aprender de la "Pizza" de forma segura, el sistema necesita saber qué estás comiendo.

**Solución: "Smart Input" en la Calculadora de Bolo**
*   **Campo Inteligente:** "¿Qué vas a comer?".
*   **Funcionalidad Híbrida:**
    *   **Autocompletado:** Busca en tus **Favoritos** y rellena automáticamente los carbohidratos. ✅ **(IMPLEMENTADO v1)**
    *   **Aprendizaje Rápido:** Al confirmar un bolo, pregunta: *"¿Guardar [Comida] como favorito?"*. ✅ **(IMPLEMENTADO v1)**
    *   **Carbohidratos Manuales:** Siempre permite sobrescribir la cantidad sugerida.
*   **Próximo Paso (Fase 2):**
    *   Sugerencias de Estrategia: *"Con [Pizza] sueles necesitar Bolo Dual (+10%)"*. ⏳

---

## 2. 📍 Rotación de Sitios de Inyección (Body Map)
**Objetivo:** Evitar lipodistrofias y asegurar buena absorción rotando los puntos.

✅ **ESTADO: COMPLETADO**
*   **Visuales Profesionales:** Nuevas ilustraciones médicas anatómicas (v2).
    *   **Abdomen:** Vista frontal detallada.
    *   **Piernas/Glúteos:** Vista trasera unificada (más clara para zonas basales).
*   **Lógica de Rotación:**
    *   Recuerda el último punto exacto usado por tipo de insulina.
    *   Sugiere automáticamente el siguiente punto siguiendo un orden lógico.
*   **Integración:**
    *   Disponible en **Bolo** (Rápida).
    *   Disponible en **Basal** (Lenta).
    *   Página dedicada **"Mapa Corporal"** para consultar historial y corregir errores.

---

## 3. 🛡️ Seguridad Basal: Calculadora de Olvido
**Problema:** Olvidar la hora habitual de la basal (Lenta) genera duda: *"¿Me la pongo entera o la reduzco para no solapar con mañana?"*.

✅ **ESTADO: COMPLETADO**
*   **Calculadora "Late Dose":**
    *   Calcula el retraso exacto respecto a tu hora habitual.
    *   **< 30 min:** Sugiere Dosis Completa.
    *   **Retraso Medio:** Reduce la dosis proporcionalmente para cubrir solo las horas restantes hasta la próxima dosis programada.
    *   **> 12h:** Alerta de riesgo y sugiere saltar o consultar médico.

---

## 4. 📦 Próximos Pasos: Gestión de Suministros
**Propuesta:** 
*   **Caducidades:** Recordatorios para Sensores (14 días), Catéteres (3 días) y Plumas abiertas (30 días).
*   **Inventario (Control de Stock):** 
    *   **Agujas:** Sistema de descuento automático.
        *   Entrada fácil de stock (ej: +3 cajas de 100u).
        *   Descuento automático de 1 unidad con cada bolo confirmado.
        *   Opción manual de "Reset" o ajuste de inventario.

---

## 5. 📄 Informes y Modo Enfermedad
**Propuesta:** Informes tipo AGP para el médico y modo "Días Enfermos".
