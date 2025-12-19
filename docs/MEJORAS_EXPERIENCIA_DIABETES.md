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
*   **Aprendizaje de Estrategia:** Si detecta que con una comida usas **Bolo Dual**, te lo sugerirá la próxima vez que la anotes. ✅ **(IMPLEMENTADO v1)**

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

## 4. 📦 Gestión de Suministros
✅ **ESTADO: COMPLETADO (v1)**

*   **Agujas:** 
    *   **Control Automático:** Descuenta 1 unidad con cada Bolo o registro de Basal.
    *   **Botón Rápido:** "Añadir Caja (+100)" para reposiciones fáciles.
    *   **Alertas:** Verde (>50), Ámbar (<50), Rojo (<20).
*   **Sensores:**
    *   **Control Manual:** Botones simples (+1/-1) para gestionar el inventario.
    *   **Alertas:** Aviso cuando quedan menos de 4 unidades.

---

## 5. 🤒 Modo Enfermedad
✅ **ESTADO: COMPLETADO (v1)**

*   **Interruptor Simple:** Activable desde Perfil > Enfermedad.
*   **Lógica Automática:**
    *   **+20% Dosis:** Aumenta automáticamente los ratios (ICR/ISF).
    *   **Alertas:** Avisa de riesgo de Cetonas si Glucosa > 250.
    *   **Indicador Visual:** Icono de estado en la home y calculadoras.

---

## 6. 📝 Gestión Avanzada de Historial
✅ **ESTADO: COMPLETADO (v1)**

*   **Edición de Entradas:** Botón lápiz (✏️) para corregir errores en Dosis, Carbohidratos o Fecha/Hora. Actualiza directamente Nightscout.
*   **Visualización de Comidas:** Muestra el nombre del plato ("🍕 Pizza") destacado en el listado si se usó el Smart Input.
