# Entrenamiento offline de corrección residual (CatBoost)

## Objetivo
Entrenar un modelo que aprenda el residual del forecast físico, con targets:

```
residual_h = BG_real_h - baseline_forecast_h
```

Horizontes: 30, 60, 120, 240 y 360 minutos.

## Reglas operativas
- **Entrenamiento offline** (no se activa en producción).
- **No se modifican endpoints existentes**.
- **Se guardan métricas completas** (baseline vs modelo).
- **`ml_ready` se define por métricas** (no por conteo de muestras).

## Script
`backend/scripts/train_residual_forecast.py`

### Uso básico
```bash
python backend/scripts/train_residual_forecast.py \
  --db-url "$DATABASE_URL"
```

### Opciones principales
- `--user-id`: filtra por usuario.
- `--include-flagged`: incluye filas con flags de calidad.
- `--train-window-days`, `--test-window-days`, `--step-days`: backtesting rolling.
- `--mae-improvement`, `--rmse-improvement`, `--bias-threshold`: criterio `ml_ready`.

## Salidas (persistencia)
Cada ejecución crea una carpeta versionada en `backend/ml_training_output/`:

- `catboost_residual_<h>m_p10.cbm`
- `catboost_residual_<h>m_p50.cbm`
- `catboost_residual_<h>m_p90.cbm`
- `metrics.json` (resumen de métricas)
- `backtest_splits.csv` (detalle por split)
- `backtest_summary.csv` (resumen por horizonte)
- `report.md` (reporte legible)
- `metadata.json` (rango de datos, features y lógica `ml_ready`)

## Definición de ml_ready
El criterio está basado en métricas globales del backtest:
- **MAE** mejora al baseline ≥ `mae_improvement`.
- **RMSE** mejora al baseline ≥ `rmse_improvement`.
- **|Bias|** ≤ `bias_threshold`.

No se utiliza conteo de muestras para habilitar `ml_ready`.
