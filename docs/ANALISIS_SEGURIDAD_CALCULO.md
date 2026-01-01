# Análisis y Valoración: Propuesta de Seguridad de Cálculo

Tras estudiar a fondo el documento `PROPUESTA_SEGURIDAD_CALCULO.md` y contrastarlo con la arquitectura actual (`bolus.py`, `tools.py`, `context_builder.py`), presento mi valoración técnica y plan de acción.

## 1. Valoración General: ¿Vale la pena?

**SÍ, ABSOLUTAMENTE.**
La seguridad en el cálculo de insulina es crítica. La propuesta identifica correctamente vectores de riesgo reales en sistemas distribuidos (Bot vs App vs Nightscout):
*   **Discrepancia de Datos:** El Bot puede ver una glucosa (ej. 150 mg/dl) y la App otra (148 mg/dl) por milisegundos de diferencia.
*   **Estado de Configuración:** Si cambias tu ratio en la App y al segundo pides un bolo al Bot, este podría tener la configuración antigua en caché.

Sin embargo, **no recomiendo implementar la propuesta exactamente como está escrita** (especialmente el punto 1 de "Doble Cálculo"), ya que introduce latencia innecesaria. Propongo una **arquitectura de "Fuente Única de Verdad"** que es más rápida y segura.

---

## 2. Análisis Punto por Punto y Refinamiento

### Propuesta 1: Auditoría de Doble Cálculo (Run Twice)
> *Propuesta:* Ejecutar el cálculo en Bot y luego simularlo como App para ver si coinciden.
*   **Veredicto:** ⚠️ **Ineficiente.**
*   **Por qué:** Ambos sistemas usan la misma función Python (`calculate_bolus_v2`). Si les pasas los mismos datos, darán el mismo resultado. La discrepancia no está en la *lógica* (matemáticas), sino en los *inputs* (datos de entrada). Correrlo dos veces con los mismos inputs es desperdiciar CPU. Correrlo con inputs "frescos" introduce condiciones de carrera (race conditions).
*   **Mejora Sugerida:** **Validación de Inputs (Input Integrity).** En lugar de calcular dos veces, asegura criptográficamente que los *inputs* sean idénticos.

### Propuesta 2: Token de Integridad (Settings Hash)
> *Propuesta:* Comparar Hash de ajustes antes de calcular.
*   **Veredicto:** ✅ **IMPRESCINDIBLE.**
*   **Por qué:** Es la única forma de garantizar que el Bot "sabe" que tus ajustes han cambiado.
*   **Plan:** Añadir un campo `settings_hash` a `UserSettings`. El Bot verifica `local_settings.hash == db_settings.hash`. Si difieren, recarga forzosamente antes de calcular.

### Propuesta 3: Snapshotting (Contexto Congelado)
> *Propuesta:* Usar una "foto" fija de los datos (BG, IOB) para todo el proceso.
*   **Veredicto:** ✅ **CRÍTICO.**
*   **Por qué:** Evita que durante los 200ms del cálculo, entre una nueva glucosa y cambie el resultado a mitad de proceso.
*   **Plan:** Modificar `calculate_bolus` en `tools.py` para aceptar un objeto `ContextSnapshot`. Si no se provee, crea uno. Pero una vez creado, **ese objeto es inmutable** y se pasa a todas las sub-funciones.

### Propuesta 4: Log de Discrepancias
> *Propuesta:* Tabla SQL para auditoría.
*   **Veredicto:** ℹ️ **Útil pero secundario.**
*   **Plan:** Implementar primero las medidas preventivas (2 y 3). El log puede implementarse como un simple archivo de texto estructurado por ahora para no sobrecargar la DB.

### Propuesta 5: Interruptor de Seguridad (Failsafe)
> *Propuesta:* Bloquear si la calidad de datos es baja (<90%).
*   **Veredicto:** ✅ **Muy Recomendable.**
*   **Plan:** Añadir flag `strict_mode` en ajustes de IA. Si `true` y Nightscout tiene "gaps" o datos viejos (>10 min), el Bot se niega a calcular y pide que lo hagas manual.

---

## 3. Plan de Implementación Recomendado (La "Mejor Forma")

En lugar de "validar a posteriori" (calcular y comparar), vamos a **"asegurar a priori"** (garantizar la integridad de los datos antes de calcular).

### Fase 1: Integridad de Configuración (Settings Hash)
1.  Modificar `UserSettings` para calcular un Hash SHA256 de su contenido crítico (`cr`, `isf`, `targets`, `iob`) al cargarse.
2.  En `tools.py`, antes de `calculate_bolus`, hacer una consulta ligera a DB para ver el hash del usuario.
3.  Si no coinciden -> `await user_settings.reload()`.

### Fase 2: Snapshot Context
1.  Crear clase `BolusContext` que contenga: `bg`, `iob`, `cob`, `timestamp`, `settings_snapshot`.
2.  El Bot instancia esto **una sola vez** al recibir el comando.
3.  Pasa este objeto explícito a `calculate_bolus_v2`.
4.  El Bot responde: *"Cálculo basado en datos de las 14:05 (Hash #A1B2)"*.

### Fase 3: Modificación del Prompt
Instruir al LLM para que **siempre** reporte la hora de los datos usados.

---

### ¿Cómo proceder?

Si estás de acuerdo, puedo empezar con la **Fase 1 (Settings Hash)** ahora mismo. Es la mejora que más robustez aportará inmediatamente para evitar el problema de "ajustes viejos".

¿Te parece bien este enfoque refinado?
