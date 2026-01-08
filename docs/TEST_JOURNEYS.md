# Test Journeys (Simulación T1D)

Este documento registra los recorridos simulados realizados por el auditor para validar la lógica y UX.

## Journey 1: "Precomida Estándar"
**Actor:** Usuario T1D, BG 110 mg/dL, Flecha →.
**Acción:** Va a comer 60g Carbs, 20g Grasa.
**Pasos:**
1. Abre App. Ve BG 110 (Reciente).
2. Entra a Calculadora.
3. Mete 60g Carbs.
4. Mete 20g Grasa.
5. **Observación:** La app sugiere "Bolo Normal" (~6U).
6. **Simulación:** Gráfico muestra curva subiendo a 160 y bajando a 110.
7. **Resultado:** OK. Feedback visual correcto.

## Journey 2: "Corrección con IOB Oculto" (Fallo Detectado)
**Actor:** Usuario T1D, BG 220 mg/dL, Flecha ↗. Se puso 3U hace 1 hora (con pluma, subido a Nightscout).
**Acción:** Abre Bolus AI para corregir lo que cree que es falta de insulina.
**Pasos:**
1. Abre App. Ve BG 220.
2. App consulta IOB local. **Resultado: 0.00 U** (Porque no lee NS).
3. App calcula corrección completa para 220 -> 100. Sugiere 4U.
4. **Realidad:** El usuario tiene 2U activas de la inyección anterior. Solo necesita 2U.
5. **Riesgo:** El usuario se pone 4U + 2U activas = 6U relativas. Hipo severa en 2 horas.
6. **Veredicto:** **FALLO CRÍTICO**.

## Journey 3: "Importación de Nutrición (Fibra)"
**Actor:** Usuario usando "Yazio" -> "Health Auto Export" -> Webhook Bolus AI.
**Datos:** 50g Carbs, 15g Fibra.
**Pasos:**
1. Webhook recibe payload.
2. `integrations.py` procesa. Detecta 50g Carb. Crea `Treatment` orphan.
3. Detecta 15g Fibra.
4. **Condición de Carrera:** Si Yazio envía primero "Carbs" y 2 seg después "Full Nutrition" con Fibra:
   - El primer request crea el Tratamiento.
   - El segundo request cae en `dedup_window` (L519 `integrations.py`).
   - Lógica de update: `if fiber_provided ... is_duplicate = True`.
   - **Resultado:** Parece que el código SÍ intenta actualizar (`c.fiber = float(...)`).
   - **Verificación:** El log debe confirmar "Updated fiber on existing nutrition entry". Si falla, es por `tolerance` o porque el ID no coincide.

## Journey 4: "Predicción Fantasma"
**Actor:** Usuario solo mirando.
**Acción:** Entra a "Forecast".
**Pasos:**
1. No hay IOB local.
2. No hay Carbs activos.
3. Predicción muestra línea plana en BG actual.
4. **Confusión:** "Nightscout dice que bajaré (porque NS sí tiene el IOB)".
5. **Disonancia:** Bolus AI dice "Plano", Nightscout dice "Bajando". El usuario desconfía de la App.
