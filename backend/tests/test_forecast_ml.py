
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from app.api.ml_features import build_runtime_features
from app.services.ml_inference_service import MLInferenceService
from app.models.forecast import ForecastPoint

@pytest.fixture
def clean_ml_service():
    # Reset singleton
    MLInferenceService._instance = None
    yield
    MLInferenceService._instance = None

def test_build_runtime_features():
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    feats = build_runtime_features(
        user_id="test_user",
        now_utc=now,
        bg_mgdl=120.0,
        trend="Flat",
        bg_age_min=5.0,
        iob_u=1.5,
        cob_g=20.0,
        to_utc_func=lambda x: x,
        basal_rows=[],
        treatment_rows=[],
        iob_status="ok",
        cob_status="ok",
        source_ns_enabled=True,
        ns_treatments_count=5
    )
    
    assert feats["bg_mgdl"] == 120.0
    assert feats["iob_u"] == 1.5
    assert feats["flag_bg_missing"] is False
    assert feats["hour_of_day"] == 12
    assert "baseline_bg_30m" not in feats # Added later by predict

def test_ml_inference_service_fallback(clean_ml_service):
    svc = MLInferenceService.get_instance()
    svc.models_loaded = False
    
    res = svc.predict({}, [])
    assert res.ml_ready is False
    assert not res.predicted_series

def test_ml_inference_logic_mocked(clean_ml_service):
    svc = MLInferenceService.get_instance()
    
    # Mock Loaded Models
    svc.models_loaded = True
    
    # Mock CatBoost Regressors
    mock_p50 = MagicMock()
    mock_p50.predict.return_value = [10.0] # Predict +10 residual
    
    mock_p10 = MagicMock()
    mock_p10.predict.return_value = [5.0] # +5
    
    mock_p90 = MagicMock()
    mock_p90.predict.return_value = [15.0] # +15
    
    # Inject models for horizon 30
    svc._models = {
        30: {'p50': mock_p50, 'p10': mock_p10, 'p90': mock_p90}
    }
    
    baseline = [
        ForecastPoint(t_min=0, bg=100.0),
        ForecastPoint(t_min=5, bg=100.0),
        ForecastPoint(t_min=30, bg=100.0)
    ]
    
    features = {"some": 1, "trend": "Flat"} 
    
    res = svc.predict(features, baseline)
    
    assert res.ml_ready is True
    assert len(res.predicted_series) > 0
    
    # Check 30m point
    # Baseline 100 + Residual 10 = 110
    p30 = next((p for p in res.predicted_series if p.t_min == 30), None)
    assert p30 is not None
    assert p30.bg == 110.0
    
    # Check Band
    p30_10 = next((p for p in res.p10_series if p.t_min == 30), None)
    assert p30_10.bg == 105.0 # 100 + 5

    p30_90 = next((p for p in res.p90_series if p.t_min == 30), None)
    assert p30_90.bg == 115.0 # 100 + 15
    
    # Check interpolation at 5m
    # 0m = 0 residual, 30m = 10 residual.
    # 5m = 5/30 * 10 = 1.666
    # Baseline 100 + 1.666 = 101.7
    p5 = next(p for p in res.predicted_series if p.t_min == 5)
    assert 101.6 < p5.bg < 101.8
