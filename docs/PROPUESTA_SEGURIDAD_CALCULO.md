# Propuesta Técnica: Mecanismo de Verificación y Seguridad Bolus AI

**Estado:** Propuesta para implementación futura  
**Objetivo:** Garantizar paridad total (100%) entre los cálculos del Bot de Telegram y la Calculadora de la App, evitando discrepancias por latencia de datos o configuración.

---

## 1. Auditoría de Doble Cálculo (Calibración Cruzada)
Implementar una capa de validación obligatoria antes de que el Bot emita cualquier recomendación de insulina.

- **Mecanismo:** Cada vez que el Bot invoque `calculate_bolus_v2`, el sistema realizará automáticamente una segunda llamada idéntica simulando el entorno de la App (Stateless Calc).
- **Umbral de Tolerancia:** Si la diferencia entre el cálculo del Bot y el "clon" de la App es mayor a **0.05 U**, el Bot abortará la respuesta.
- **Feedback al Usuario:** En lugar de dar una cifra errónea, dirá: *"⚠️ Discrepancia de seguridad detectada. Por favor, realiza el cálculo directamente en la App para mayor precisión."*

## 2. Token de Integridad de Ajustes (Settings Hash)
Asegurar que el Bot y la App estén "viendo" la misma configuración de usuario (CR, ISF, DIA, etc.).

- **Implementación:** Generar un `hash` único (ej. SHA-256) basado en el objeto de ajustes del usuario.
- **Validación:** El Bot solo permitirá cálculos si el `hash` de los ajustes cargados en su memoria coincide exactamente con el `hash` de los ajustes más recientes en la base de datos de la App.
- **Prevención:** Evita el error de "ajustes antiguos" que ocurrió anteriormente, donde el Bot usaba ratios por defecto mientras la App ya tenía los personalizados.

## 3. Sincronización de Contexto de Tiempo Real (Snapshotting)
Evitar que la glucosa o el IOB cambien entre el inicio y el fin del cálculo.

- **ID de Contexto:** Al iniciar un cálculo, se captura un "Snapshot" (foto) de Nightscout (BG, Tendencia, IOB).
- **Consistencia:** Todas las sub-funciones del cálculo usarán ese Snapshot fijo en lugar de consultar la red varias veces durante el proceso.
- **Transparencia:** El Bot indicará: *"Cálculo basado en datos de las 10:35:01"*.

## 4. Sistema de Log de Discrepancias (Observability)
Crear una tabla de auditoría en la base de datos para análisis forense de cálculos.

- **Campos:** `timestamp`, `input_data`, `bot_result`, `app_result`, `diff`.
- **Utilidad:** Identificar si hay errores lógicos en casos borde (edge cases) como comidas con muchísima grasa o situaciones de alcohol, permitiendo mejorar el algoritmo de forma científica.

---

## 5. Implementación del "Interruptor de Seguridad" (Failsafe)
Un comando o ajuste que permita:
- Bloquear el cálculo del Bot si la calidad de los datos de Nightscout es inferior al 90% (muchas lagunas de datos).
- Forzar al Bot a pedir confirmación manual de la glucosa si detecta que el sensor está en periodo de calentamiento o es ruidoso.

---
*Este documento sirve como hoja de ruta para la próxima gran actualización de seguridad del motor de Bolus AI.*
