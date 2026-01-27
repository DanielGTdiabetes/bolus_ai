# Auditoría del Motor de Predicción: Sesgo Positivo por Deriva Basal

## 1. Diagrama de la Lógica Actual

El motor de predicción (`ForecastEngine`) calcula el impacto de la basal mediante un modelo diferencial (comparación entre lo que hay y lo que "debería" haber).

**Flujo de Cálculo:**

1. **Referencia (Settings):** Se obtiene `basal_daily_units` desde la configuración del usuario (o fallbacks). Se asume que esta cantidad es la necesaria para mantener la glucosa plana (Drift = 0).
    * `reference_rate = basal_daily_units / 1440` (U/min).
2. **Actividad Real (Inyecciones):** Se suman las curvas de actividad de las inyecciones vivas (Lantus, Tresiba, etc.).
    * `current_activity = BasalModels.get_activity(...)`.
3. **Cálculo del Déficit/Superávit:**
    * `net_basal = current_activity - reference_rate`.
4. **Impacto en Glucosa:**
    * `impact = -1 * net_basal * ISF`.

**El Problema:**

* Si `current_activity` (lo que te pusiste) es **menor** que `reference_rate` (lo que dice tu configuración), el resultado de `net_basal` es **negativo**.
* Impacto = `-1 * (-) * ISF` = **POSITIVO (+)**.
* **Resultado:** La gráfica se curva hacia arriba sistemáticamente.

---

## 2. Hallazgos Críticos

### A. Fallo de Referencia Estática (`app/api/forecast.py`)

En las líneas ~1450-1471, el sistema intenta adivinar la `Ref`. Si el usuario tiene configurado un perfil de basal (Schedule) que suma 20u, pero hoy decidió ponerse 18u (o está en el final de la vida de la dosis), el sistema entra en modo "Déficit Constante".

* **Consecuencia:** El motor cree que te falta insulina basal todo el tiempo y añade una subida artificial (Liver Drift) infinita.

### B. Curvas de Insulina No Planas (`app/services/math/basal.py`)

Aunque se intentó "aplanar" curvas como Glargine (comentario en línea 25), si se usan curvas con picos o colas (Levemir, NPH, o incluso la ligera caída de Glargine), habrá momentos del día donde `Actividad < Promedio`.

* **Consecuencia:** En esos valles, el forecast subirá erróneamente, aunque la glucosa real esté estable.

### C. Conflicto con Momentum

El Momentum (inercia de la glucosa real) intenta corregir esto a corto plazo (primera hora), pero el `forecast_engine` diluye el momentum en 30 minutos (Línea 145: `momentum_duration = 30`).

* **Consecuencia:** Después de los 30-45 min, el "Drift Basal" toma el control total y la curva se dispara hacia arriba, ignorando que la glucosa real estaba bajando.

---

## 3. Conclusiones

El tratamiento actual de la basal actúa como una **fuerza correctora rígida**. Asume que la configuración del usuario es la "Verdad Absoluta" fisiológica.

* **¿Es fisiológicamente razonable?** No en la práctica. La necesidad basal del hígado varía, y la dosis inyectada también. Asumir que `Dosis < Configuración` implica `Subida Inmediata` es demasiado agresivo para un sistema de lazo abierto (Open Loop) o predicción.
* **Riesgo:** Genera ansiedad en el usuario (predicciones de hiperglucemia falsas) y desconfianza en el sistema.

---

## 4. Alternativas Propuestas

### Solución A: Neutralidad Basal (Recomendada)

**Concepto:** Asumir que la basal inyectada es *suficiente* para mantener la estabilidad, a menos que falte totalmente (olvido).

* **Lógica:** En `forecast_engine`, forzar `reference_rate = current_activity` (al inicio de la simulación t=0).
* **Efecto:** `net_basal` se vuelve 0. El impacto basal desaparece. La gráfica solo se mueve por Bolos, Carbs y Momentum.
* **Excepción:** Si `current_activity` es casi cero (ej. < 0.1 u/h), entonces sí usar la Referencia para alertar de la falta de basal.

### Solución B: Clamp de Seguridad

**Concepto:** Permitir drift negativo (bajada por exceso de basal) pero bloquear el drift positivo (subida por falta teórica) si la glucosa actual es normal/baja.

* **Lógica:** `if net_basal < 0 and current_bg < target: net_basal = 0`.
* **Efecto:** Evita que la gráfica suba cuando la glucosa está bien, pero permite avisar si te pusiste demasiada insulina.

### Solución C: Calibración Dinámica (Complex)

**Concepto:** Calcular el "Drift Real" observado en las últimas 3 horas (sin bolos/comida) y usar ese valor como el verdadero basal drift, ignorando la configuración teórica.

* **Riesgo:** Requiere datos muy limpios. Difícil de implementar robustamente.

---

## 5. Recomendación

Implementar la **Solución A (Neutralidad Basal)**. Es la más segura para la experiencia de usuario ("Lo que veo es lo que hay"). Elimina el ruido teórico de "tu configuración dice 20 pero llevas 19".

### Tests Propuestos

1. **Caso Base:** Sin IOB, sin COB, Basal Activa normal. -> La curva debe ser **PLANA**. (Actualmente sube).
2. **Caso Déficit Leve:** Usuario configuró 20u, se puso 15u. -> La curva debe ser **PLANA** (o subir muy levemente, no dispararse).
3. **Caso Olvido:** Usuario tiene 0u activas. -> La curva debe **SUBIR** (alerta de cetoacidosis/falta de insulina).
