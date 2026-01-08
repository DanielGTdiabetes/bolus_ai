# Auditoría de Producto T1D: Bolus AI

**Fecha:** 2026-01-08  
**Auditor:** Antigravity (Simulación Rol T1D/QA)  
**Versión Auditada:** HEAD (Repo Actual)

---

## 1. Resumen Ejecutivo

Bolus AI presenta una base sólida de cálculo de bolos con características avanzadas ("Warsaw Mode", "Autosens", Detección de Compresión). Sin embargo, **existe un riesgo crítico de seguridad** debido a la falta de sincronización bidireccional real con Nightscout.

Actualmente, el sistema opera en modo "Silo Local": solo conoce los tratamientos que el usuario introduce directamente en la app. Si el usuario utiliza otros dispositivos (plumas inteligentes, bombas Loop/APS) que suben datos a Nightscout, **Bolus AI los ignora por completo**, calculando IOB=0 y COB=0 erróneamente. Esto puede llevar a recomendaciones de sobredosis severas (Stacking).

Desde el punto de vista de UI/UX, la aplicación es clara, pero la gráfica de predicción puede resultar confusa al mostrar una caída inminente (por falta de input de carbs en la vista previa) antes de que el usuario termine de introducir los datos.

## 2. Hallazgos Clave (Priorizados)

### 🔴 P0: Ceguera a Tratamientos Externos (Riesgo de Hipo Severa)
- **Descripción:** El backend (`iob.py`, `treatment_retrieval.py`) fuerza la lectura de tratamientos en modo `local_only` o simplemente no tiene lógica para importar desde Nightscout.
- **Impacto:** Si un T1D se pone 5U con su pluma y lo registra en Nightscout, y 15 min después consulta Bolus AI, la app mostrará IOB: 0.00 U. Si calcula un nuevo bolo, no restará la insulina activa.
- **Ubicación:** `backend/app/services/iob.py` (L139-148), `backend/app/api/nightscout.py` (L477 - lógica legacy deshabilitada).

### 🟠 P1: Importación de Nutrición (Fibra) Desincronizada
- **Descripción:** Aunque existe lógica en `integrations.py` para parsear fibra, reportes previos y la revisión indican que el "Force Now" y la deduplicación agresiva pueden descartar actualizaciones de fibra si llegan segundos después del primer payload (común en Health Auto Export).
- **Impacto:** Cálculos avanzados (descuento de fibra) fallan silenciosamente.
- **Ubicación:** `backend/app/api/integrations.py`.

### 🟡 P2: Confusión Visual en Gráfica de Predicción
- **Descripción:** La gráfica de predicción en la página principal (`MainGlucoseChart`) y en el simulador asume IOB actual. Si el usuario está pre-visualizando un bolo pero no ha rellenado carbs, la curva se desploma (simulación de "sobredosis" o "ayuno con insulina").
- **Impacto:** Ansiedad innecesaria ("¿Por qué voy a tener hipo?"). Falta claridad visual sobre qué es "simulación con lo que has escrito" vs "predicción actual".

## 3. Recomendaciones Inmediatas

1.  **Reactivar Sync Inbound de Nightscout:** Crear un worker o modificar `iob.py` para que, si falta data local reciente, consulte Nightscout en tiempo real antes de devolver el IOB.
2.  **Banner de "Datos Externos":** Si la app detecta que no tiene datos recientes (hueco > 2h) pero hay conexión a NS, debe avisar o forzar fetch.
3.  **UI de Predicción:** En el calculador, diferenciar visualmente entre "Predicción Actual" (línea punteada gris) y "Simulación del Nuevo Bolo" (línea sólida de color).

## 4. Estado de UX/Accesibilidad
- **Contraste:** Adecuado en general.
- **Textos:** Claros, aunque el uso de términos técnicos ("Warsaw Trend", "Autosens") requiere educación previa del paciente.
- **Feedback:** Los tooltips en la gráfica son útiles pero difíciles de acertar en móvil (touch targets).

---
**Firma:** Auditoría Automática Antigravity
