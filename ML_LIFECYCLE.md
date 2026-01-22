# ML Lifecycle & Safety Policy

**Version:** 1.0 (2026-01-22)
**Scope:** Bolus AI (Backend/Bot)

This document defines the strict lifecycle states for Machine Learning features to ensure transparency, safety, and lack of "phantom AI".

## 1. Lifecycle States

The ML system can be in one of three states for any given user/horizon.

### State A: `DATA_GATHERING` (Default)

- **Condition:** No trained model exists, or data volume is below `ml.min_training_samples` (default: 1000 samples / ~3.5 days).
- **Behavior:**
  - `predict()` returns `ml_ready=False` and `source="physics"`.
  - UI/Bot shows "Heuristic Forecast" or similar, relying purely on math models (ISF/ICR/IOB).
  - Background jobs collect metrics but do **not** attempt training.
- **Logging:** "ML: No model directory found (not trained yet). State: DATA_GATHERING." (Once at startup).

### State B: `TRAINING` (Transient)

- **Condition:**
  - Data accumulates > `ml.min_training_samples`
  - `ml.training_enabled` is set to `True` (default False).
- **Behavior:**
  - Scheduled job `run_ml_training` (Daily 03:00 AM) triggers via `MLTrainerService`.
  - Checks quality gates (RMSE < 40, history > 3 days).
  - Generates model artifacts (`catboost_residual_*.cbm`) in `ML_MODEL_DIR`.
  - Persists `metadata.json` and loads model into memory.

### State C: `ACTIVE`

- **Condition:** Valid model artifacts exist in `ML_MODEL_DIR` AND pass validation checks.
- **Behavior:**
  - `predict()` returns `ml_ready=True`.
  - Inference runs on `catboost` models.
  - Output is clamped by `settings.ml.safety_clamp_mgdl`.
- **UI Indication:** "ML Forecast (v1.0)" displayed.

## 2. Anti-Smoke Policy (Anti-Humo)

**It is strictly forbidden to:**

1. Return random or "placeholder" predictions when ML is unavailable.
2. Label a heuristic forecast as "AI" or "ML".
3. Silently swallow "missing model" errors during *inference* (startup logs are fine).

### Verification

If `MLInferenceService.models_loaded` is `False`, any call to `predict(...)` MUST return:

```python
MLPredictionResult(
    predicted_series=[], 
    ml_ready=False, 
    warnings=["Models not loaded"]
)
```

The consuming service (ForecastEngine) MUST fallback to physics-based calculation and flag the result source as `physics`.

## 3. Persistent Storage

The ML system uses a persistent directory for trained models:

- `ML_MODEL_DIR` (default: `/app/backend/data/ml_models`)

This directory is automatically created at runtime if missing.
For NAS deployments, it MUST be mounted to persistent storage.

## 4. Configuration & Persistence

- **ML_MODEL_DIR:**
  - **NAS:** Mounted volume `/app/data/ml_models` (preserves training across restarts).
  - **Render:** Ephemeral. Training disabled by default (`ml.training_enabled=False`). If enabled, models are lost on restart unless external storage (S3/GCS) is configured (future scope).
  
- **Thresholds:**
  - `min_training_samples`: 1000 (~3.5 days).
  - `retrain_interval_hours`: 24.
  - `min_days_history`: 3.

## 5. Gating Logic

```python
def can_train_model(sample_count: int) -> bool:
    return sample_count >= settings.ml.min_training_samples

def can_use_model(model_path: Path) -> bool:
    return model_path.exists() and (model_path / "metadata.json").exists()
```
