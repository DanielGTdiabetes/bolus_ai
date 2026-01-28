
# Auditoría y Mejora: Anti-Panic Gating (PR1)

Esta actualización aborda la inestabilidad y el sesgo observados en las predicciones post-comida, identificados durante la auditoría del módulo de Forecast.

## Problema Original

El mecanismo "Advanced Anti-Panic Gating" tenía un comportamiento binario:

- Reducía el impacto de la insulina en un 40% (factor 0.6) tras las comidas para evitar "falsos hipos".
- Se desactivaba **de golpe** si la pendiente de caída superaba `-2.5` mg/dL/min o si la predicción tocaba 80 mg/dL.
- **Resultado:** Saltos bruscos en la gráfica. Una caída de `-2.4` se frenaba artificialmente (mostrando una curva plana), y al pasar a `-2.6` la curva se desplomaba sin transición.

## Solución Implementada (PR1)

Hemos reemplazado la lógica binaria por una **Modulación Progresiva** (Continuous Gating).

### 1. Factor Continuo (`_compute_anti_panic_scale`)

La escala de insulina (`insulin_scale`) ya no salta de 0.6 a 1.0. Ahora se calcula interpolando suavemente:

- **Base:** Rampa temporal de 0.6 a 1.0 en 90 minutos (igual que antes).
- **Liberación por Inercia:** Si la caída real (`deviation_slope`) está entre `-1.0` y `-2.5`, liberamos progresivamente el freno.
  - `-1.0`: Usa factor base (ej. 0.6).
  - `-1.75`: Liberación al 50%.
  - `-2.5`: Liberación total (factor 1.0).
- **Liberación por Hipo:** Si la predicción futura (`min_bg`) está entre 90 y 80, liberamos progresivamente.
  - `90`: Usa factor base.
  - `80`: Liberación total.

### 2. Diagnóstico

Se ha añadido información de depuración en la respuesta de la API (`ForecastResponse.meta`) bajo la clave `anti_panic_debug_meta`. Esto permite auditar qué componente (tiempo, pendiente o hipo) está dominando la decisión.

Ejemplo de traza:

```json
{
    "anti_panic_trace": {
        "applied": true,
        "t_min": 30,
        "anti_panic_base_scale": 0.733,
        "anti_panic_final_scale": 0.911,
        "deviation_slope": -2.0,
        "min_bg_pred": 120.0,
        "release_components": {
            "slope_release": 0.667,
            "hypo_release": 0.0
        }
    }
}
```

## Verificación

Se han añadido tests unitarios en `tests/test_forecast_anti_panic.py` que cubren:

- Caídas moderadas (verificando liberación parcial).
- Transiciones suaves en el umbral crítico (-2.4 vs -2.6).
- Prioridad del riesgo de hipoglucemia.

## Archivos Modificados

- `app/services/forecast_engine.py`: Refactorización de la lógica y extracción de `_compute_anti_panic_scale`.
- `tests/test_forecast_anti_panic.py`: Nuevos tests.

## PR2: Fix feedback hypo_release

Se identificó una realimentación positiva ("feedback loop") donde la decisión de liberar la protección Anti-Panic por riesgo de hipoglucemia (`hypo_release`) se tomaba basándose en la predicción "cruda" (sin protección). Esto provocaba que, partiendo de niveles normales (ej. 110 mg/dL), el "dip" inicial de la insulina activara la alerta de hipoglucemia, desactivando la protección y causando una caída artificial en la gráfica.

**Solución:** Ahora se calcula una predicción "segura" (`predicted_bg_safety`) aplicando la protección base (rampa temporal) antes de evaluar el riesgo. Esto asegura que la protección solo se desactive si la hipoglucemia es inminente *incluso* con la protección activada.

- **Impacto:** Elimina falsas hipoglucemias en rangos normales sin ocultar hipoglucemias reales profundas.
- **Verificación:** Test `test_feedback_loop_fix` en `tests/test_forecast_anti_panic_pr2.py`.
