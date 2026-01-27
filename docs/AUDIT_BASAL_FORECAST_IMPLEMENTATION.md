# Implementación de Neutralidad Basal Condicional

## Resumen del Cambio

Se ha implementado un mecanismo para **eliminar el sesgo positivo artificial** (drift hacia arriba) en la gráfica de predicción, que ocurría cuando el sistema detectaba un déficit teórico de basal incluso si el usuario estaba estable.

## Archivos Modificados

1. **`app/models/forecast.py`**:
    * Nuevo campo en `SimulationParams`: `basal_drift_handling` (Literal: "standard", "neutral", "alert_only").
    * Default: "standard" (para mantener compatibilidad si no se especifica).

2. **`app/services/forecast_engine.py`**:
    * En el bucle de simulación, si `params.basal_drift_handling == "neutral"`, el impacto basal (`step_basal_impact`) se fuerza a `0.0`.
    * Esto elimina la subida causada por `(Actividad < Referencia)`, pero también elimina la bajada si hubiera exceso. Por eso es **condicional**.

3. **`app/api/forecast.py`**:
    * Se añadió lógica de **auto-detección** en `get_current_forecast` y `simulate_forecast`.
    * **Condiciones para activar modo "neutral":**
        1. **Glucosa Segura:** BG actual <= (Objetivo + 40 mg/dL).
        2. **Tendencia:** Estable o Bajando (pendiente <= 0.2).
        3. **Sin Bolos Activos:** < 0.5 U en las últimas 5 horas.
        4. **Sin Carbs Activos:** < 5.0 g en las últimas 3 horas.
        5. **Basal Configurada:** Existe una basal de referencia > 1.0 U (para evitar ocultar alertas reales de falta total de insulina).
    * Si se cumplen TODAS, se activa `basal_drift_handling = "neutral"`.

## Tests

Se creó el test unitario `backend/tests/test_basal_neutrality.py` que verifica:

1. **Modo Neutral:** Con déficit de basal (0.5 vs 1.0 U/h), la glucosa permanece plana (100 -> 100).
2. **Modo Estándar:** Con el mismo déficit, la glucosa sube incorrectamente (100 -> 125).

## Cómo validar en Producción

1. Observar la gráfica cuando estés estable en rango (ej. 100 mg/dL) y sin comida reciente.
2. **Antes:** La línea punteada subía suavemente hacia 120-130 constantemente.
3. **Ahora:** La línea punteada debería mantenerse plana o seguir levemente la tendencia real (Momentum), sin la fuerza invisible hacia arriba.

## Rollback

Para desactivar esta funcionalidad sin deploy, se requeriría código. Como es una mejora de lógica dura, el "fallback" es que las condiciones no se cumplan (ej. si tienes IOB, el sistema vuelve a modo Standard y calcula el drift normal).
