# Fórmula de Autosens Híbrido

## Resumen

El sistema calcula un factor de ajuste de sensibilidad combinando dos métodos:
1. **TDD Ratio**: Basado en la Dosis Total Diaria de insulina
2. **Local Ratio**: Basado en desviaciones de glucosa vs modelo

## Fórmula Principal

```
autosens_ratio = TDD_ratio × Local_ratio
```

El ratio resultante se aplica a los parámetros base:
```
CR_efectivo = CR_base / autosens_ratio
ISF_efectivo = ISF_base / autosens_ratio
```

## Interpretación

| Ratio | Significado | Efecto |
|-------|-------------|--------|
| > 1.0 | Más resistencia | CR e ISF disminuyen → necesitas más insulina |
| < 1.0 | Más sensibilidad | CR e ISF aumentan → necesitas menos insulina |
| = 1.0 | Normal | Sin ajuste |

## 1. TDD Ratio (Dynamic ISF)

### Fuentes de Datos

**Boluses**: Tabla `treatments` (últimos 7 días)

**Basal** (prioridad):
1. `basal_dose` tabla (dosis reales registradas) ✅ **PRIORIDAD**
2. `settings.bot.proactive.basal.schedule` (configuración)
3. `settings.tdd_u × 0.45` (heurística)

### Cálculo

```python
# TDD de últimas 24h
recent_tdd = sum(boluses_24h) + basal_today

# Promedio semanal
week_tdd_avg = sum(tdd_7_days) / days_with_data

# TDD ponderado (60% reciente, 40% tendencia)
weighted_tdd = (recent_tdd × 0.6) + (week_tdd_avg × 0.4)

# Ratio
tdd_ratio = weighted_tdd / baseline_tdd
```

### Seguridad

- Si la desviación de TDD reciente vs promedio > 30% → ratio = 1.0
- Si baseline_tdd < 5.0 → ratio = 1.0

## 2. Local Ratio (Autosens Clásico)

### Análisis de Desviaciones

Analiza intervalos de 5 minutos durante 24h:

```python
delta_real = BG_actual - BG_anterior
delta_modelo = (carb_rate × CS - insulin_rate × ISF) × dt_min
desviación = delta_real - delta_modelo
```

Donde `CS = ISF / ICR` (Carb Sensitivity)

### Filtros de Exclusión

- COB activo (carbs en digestión)
- BG < 70 o > 250 mg/dL
- Cambios bruscos > 15 mg/dL en 5 min
- Compresión de CGM detectada

### Agregación

```python
# Mediana de desviaciones
median_8h = statistics.median(deviaciones_8h)
median_24h = statistics.median(deviaciones_24h)

# Factor k (sensibilidad)
k = 0.05

# Ratio por ventana
ratio_8h = 1.0 + (k × median_8h)
ratio_24h = 1.0 + (k × median_24h)

# Combinación conservadora
if ratio_8h > 1 and ratio_24h > 1:
    local_ratio = min(ratio_8h, ratio_24h)
elif ratio_8h < 1 and ratio_24h < 1:
    local_ratio = max(ratio_8h, ratio_24h)
else:
    local_ratio = 1.0  # Desacuerdo → neutro
```

## 3. Clampeo de Seguridad

```python
autosens_ratio = max(min_ratio, min(max_ratio, autosens_ratio))
# Típicamente: min_ratio = 0.7, max_ratio = 1.3
```

## Ejemplo Práctico

### Datos de Entrada
- Carbohidratos: 23.9g
- Glucosa actual: 125 mg/dL
- Glucosa objetivo: 110 mg/dL
- Base I:C ratio: 9.0
- Base ISF: 78 mg/dL/U

### Escenario A (App)
```
TDD Ratio: 0.88 (usando menos insulina que referencia)
Local Ratio: 1.00 (neutro)
Híbrido: 0.88 × 1.00 = 0.88

CR ajustado: 9.0 / 0.88 = 10.2
ISF ajustado: 78 / 0.88 = 89

Bolo comida: 23.9 / 10.2 = 2.34 U
Corrección: (125 - 110) / 89 = 0.17 U
Total: 2.51 U
```

### Escenario B (Bot)
```
TDD Ratio: 0.95 (más insulina que Escenario A)
Local Ratio: 1.04 (ligera resistencia detectada)
Híbrido: 0.95 × 1.04 = 0.99

CR ajustado: 9.0 / 0.99 = 9.1
ISF ajustado: 78 / 0.99 = 79

Bolo comida: 23.9 / 9.1 = 2.63 U
Corrección: (125 - 110) / 79 = 0.19 U
Total: 2.82 U
```

### Causa de la Diferencia

La diferencia de 0.31 U se debe a:
1. **TDD diferente**: El bot tiene más tratamientos registrados en las últimas 24h
2. **Local ratio**: El bot detectó ligera resistencia en los datos CGM
3. **Timing**: Los cálculos se hicieron en momentos diferentes

## Referencias

- [OpenAPS Autosens](https://openaps.readthedocs.io/en/latest/docs/Customize-Iterate/autosens.html)
- [AndroidAPS Dynamic ISF](https://androidaps.readthedocs.io/en/latest/Usage/DynamicISF.html)

## Archivos Relevantes

- `services/dynamic_isf_service.py` - Cálculo de TDD ratio
- `services/autosens_service.py` - Cálculo de Local ratio
- `services/bolus_calc_service.py` - Combinación híbrida
- `services/bolus_engine.py` - Aplicación a CR/ISF
