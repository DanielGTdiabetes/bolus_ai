# Documentación del Motor de Predicción (Forecast Engine)

Este documento detalla el funcionamiento técnico, la lógica de simulación y las decisiones de modelado del motor de predicción de glucosa de BolusAI. 

Está diseñado como referencia para desarrolladores y para análisis clínico-técnico. Refleja el comportamiento exacto del código en `backend/app/services/forecast_engine.py`, `backend/app/services/math/curves.py` y `backend/app/api/forecast.py`.

---

## 1. Visión General

El motor simula la trayectoria futura de la glucosa basándose en principios fisiológicos deterministas. No es una caja negra; cada punto de la curva es el resultado de sumar vectores de impacto conocidos.

*   **Resolución**: Pasos de 1 minuto.
*   **Horizonte**: Configurable (típicamente 180–360 min).
*   **Inputs**:
    *   Glucosa inicial (`start_bg`).
    *   Eventos: Bolos, Carbohidratos, Inyecciones Basales.
    *   Parámetros: ISF, ICR, DIA, Perfil de Carbs, etc.
    *   Momentum: Pendiente de glucosa reciente (opcional).
*   **Outputs**:
    *   `series`: Predicción principal (incluyendo eventos propuestos/actuales).
    *   `baseline_series`: Predicción contrafactual ("¿Qué pasa si no hago nada?").
    *   `components`: Desglose de impacto (Insulina vs Carbs vs Momentum).

---

## 2. Flujo de Simulación

El motor opera en un bucle iterativo (`t=0` a `t=Horizonte`). En cada paso `t`:

1.  **Calcula Tiempo Efectivo**: Determina el tiempo transcurrido desde cada evento (`t_mid - time_offset`).
2.  **Calcula Actividad de Insulina (Insulin Effect)**: Suma la actividad instantánea de todos los bolos activos según su curva GIR.
3.  **Calcula Absorción de Carbs (Carb Effect)**: Suma la tasa de absorción de glucosa de las comidas activas (modelo biexponencial).
4.  **Calcula Impacto Basal (Basal Drift)**: Comparación entre basal activa vs basal de referencia (necesaria).
5.  **Calcula Momentum (Inercia)**: Proyección de la tendencia actual, que decae suavemente con el tiempo.
6.  **Integra**: Suma los impactos al BG anterior.
7.  **Aplica Reglas de Seguridad**: Límites duros (20-600 mg/dL), dampening en situaciones específicas (aunque minimizado).

---

## 3. Curvas de Hidratos (Carb Curves)

La absorción de carbohidratos **ya no utiliza perfiles rígidos** ("fast", "med", "slow" como cajas negras). Se emplea un modelo **biexponencial continuo** (`backend/app/services/math/curves.py`), definido por:

*   **Componente Rápida**: Pico en `t_max_r`.
*   **Componente Lenta**: Pico en `t_max_l`.
*   **Fracción Rápida (`f`)**: Porcentaje de carbs que entran por la vía rápida.

### Modulación Dinámica por Grasa/Proteína
El motor ajusta estos parámetros gramo a gramo si se detecta contenido graso (Grasa > 0):

*   **Retraso de Picos**: La grasa desplaza `t_max_r` y `t_max_l` hacia la derecha (retraso).
*   **Reducción de Velocidad**: Disminuye la fracción rápida `f`.
*   **Efecto**: Aplasita la curva y extiende la cola.

**IMPORTANTE:**
*   La Grasa y Proteína **NO generan glucosa extra** en la curva de absorción directamente.
*   Se usan para el "Auto-Ajuste" (sugerencia de bolo) o para modificar la *forma* de la curva de los carbohidratos, pero no suman gramos a la simulación por sí mismas (salvo lógica explicita de eCarbs en Warsaw Method, si está activo).
*   La fibra se usa para ralentizar, no para sumar.

---

## 4. Acción de la Insulina (Fiasp/GIR)

El modelo utiliza curvas de **tasa de infusión de glucosa (GIR)** basadas en estudios clínicos (polinomios interpolados o tablas de datos reales), no curvas teóricas simples de Walsh.

### Comportamiento Fiasp
Para el modelo Fiasp (y análogos ultrarrápidos):

1.  **Onset Real**: Se respeta la rampa de inicio fisiológica (~0-15 min son de baja actividad).
2.  **DIA Mínima Efectiva (5.5h)**:
    *   Si el usuario configura una DIA < 5.0h (ej. 3h o 4h), el motor la **eleva internamente a 5.5h** para la simulación.
    *   **Razón**: Las curvas GIR tienen colas largas. Cortarlas antes de tiempo (3h) provoca que la "insulina pendiente" desaparezca matemáticamente demasiado pronto, causando que el simulador prediga una subida falsa al final (la insulina "se acaba" antes que los carbs).
    *   Este override es **solo para la simulación gráficos**, no cambia la dosis ni el cálculo del Bolus Calculator.
    *   Se reporta en `response.meta.effective_dia_hours` y `dia_overridden: true`.

### Eliminación de "Onset Dampening"
Se ha eliminado cualquier lógica de *dampening* artificial (rampas forzadas de 0% a 100% en 20 min). Confiamos plenamente en la curva GIR del modelo seleccionado.

---

## 5. Orquestación Temporal (Event Timing)

El manejo del tiempo es crítico para evitar sesgos ("predicciones al alza" falsas).

### Definición de Offsets
*   `time_offset_min < 0`: Evento en el pasado (histórico).
*   `time_offset_min = 0`: Evento ocurriendo AHORA mismo.
*   `time_offset_min > 0`: Evento planificado en el futuro.

### Insulin Onset Delay (Lag Fisiológico)
El parámetro `insulin_onset_minutes` (ej. 10 min) simula el tiempo que tarda la insulina en empezar a circular tras la inyección.

**Regla de Aplicación Actual (CRÍTICA):**
*   **Bolos Históricos y Actuales (Offset <= 0)**: **NO SE APLICAN DESPLAZAMIENTOS.**
    *   Se asume que si el usuario registra el bolo ahora, la aguja ya ha entrado o está entrando. El reloj biológico empieza en t=0.
    *   Desplazar esto (ej. ponerle offset +10) causaría que durante los primeros 40 min, los carbs ganen la carrera injustamente, mostrando hiperglucemia falsa.
*   **Bolos Futuros (Offset > 0)**: **SÍ SE APLICA.**
    *   Si se planifica un bolo para "dentro de 10 min", se le suma el onset fisiológico.

---

## 6. IOB vs Actividad Real

El motor de simulación **NO utiliza el valor escalar de IOB** (ej. "3.5 U") para pintar la curva.

*   El IOB es un número "agregado".
*   La simulación requiere la **forma** de la curva.
*   Por tanto, la simulación **reconstruye** la actividad a partir de la lista de eventos (`events.boluses`).

**Implicación de Debugging**:
Si tienes un IOB de 5.0 U (calculado por Nightscout) pero la lista de `events` enviada al simulador está vacía (o no contiene los bolos de hace 2 horas), la gráfica mostrará que **NO hay insulina actuando**, provocando una predicción de subida masiva. El simulador es ciego al IOB numérico; solo ve eventos.

---

## 7. Baseline vs Predicción Principal

El endpoint `/simulate` devuelve dos series principales:

1.  **`series` (Línea Sólida)**: Es el escenario "Con Acción". Incluye todos los eventos, incluyendo el bolo propuesto y los carbs actuales.
    *   Responde a: "¿Qué pasará si me pongo este bolo y como esto?"
2.  **`baseline_series` (Línea Fantasma/Gris)**: Es el escenario "Sin Acción Nueva".
    *   Se calcula eliminando los eventos con `offset >= -5` (es decir, lo que acaba de pasar o va a pasar).
    *   Responde a: "¿Qué pasaría si NO me pongo el bolo y NO como nada ahora mismo?"
    *   **Nota**: Es normal que esta línea suba si hay falta de basal, o baje si hay IOB previo. Sirve de referencia visual.

---

## 8. Guía de Debugging y Errores Comunes de Interpretación

### A. "La gráfica sube mucho al principio (30-60 min) aunque me puse el bolo"
*   **Causa Probable**: Desequilibrio temporal Carbs vs Insulina.
*   **Diagnóstico**:
    1.  Verificar que el bolo tiene `time_offset_min <= 0`.
    2.  Verificar que `insulin_onset_minutes` no se esté aplicando a este bolo (revisar logs o código actualizado).
    3.  ¿Es Fiasp? Recordar que Fiasp tiene un inicio suave. Si los carbs son muy rápidos (azúcar, zumo), ganarán inicialmente.
    4.  ¿Falta insulina basal? Si `basal_daily_units` es bajo, la deriva basal suma glucosa.

### B. "La gráfica predice una subida al final (a las 4 horas)"
*   **Causa Probable**: DIA muy corta en configuración vs Absorción Lenta.
*   **Diagnóstico**:
    1.  Revisar `response.meta.effective_dia_hours`. Si es 3h, la insulina "muere" antes que los carbs (que pueden durar 4-5h si hay grasa).
    2.  Solución: El motor debería estar forzando DIA a 5.5h automáticamente si es Fiasp. Confirmar `dia_overridden: true`.

### C. "El IOB dice 5U pero la gráfica no baja"
*   **Causa Probable**: Eventos históricos faltantes.
*   **Diagnóstico**:
    1.  Revisar el JSON de la request `/simulate`.
    2.  ¿Están los bolos de hace 1h, 2h, 3h en `events.boluses`?
    3.  Si no están, el simulador asume IOB = 0 para efectos de proyección.

### D. Timeline Conceptual (Ejemplo Fiasp + Comida Normal)
```
Minuto | Carbs (Absorción)      | Insulina (Actividad) | Glucosa Neta
-------|------------------------|----------------------|-------------
0-20   | Inicio rápido          | Rampa lenta (inicio) | Sube suave
20-45  | PICO MÁXIMO            | Subiendo fuerte      | Sube (freno)
45-60  | Bajando                | PICO MÁXIMO          | Plana / Baja
60-120 | Cola media             | Meseta alta          | Baja fuerte
120+   | Cola larga (si grasa)  | Bajada lenta         | Estabiliza
```
Si la "Subida inicial" es > 50 mg/dL, revisar si los carbs están acelerados (falta de grasa/proteína en el input) o si la insulina está entrando tarde (bug de onset).
