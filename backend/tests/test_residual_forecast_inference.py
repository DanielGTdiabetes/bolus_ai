from pathlib import Path

from app.models.forecast import ForecastPoint
from app.services.residual_forecast import (
    ResidualModelBundle,
    apply_residual_adjustment,
)


def test_residual_inference_without_model_falls_back_to_baseline():
    baseline = [ForecastPoint(t_min=0, bg=110.0), ForecastPoint(t_min=30, bg=120.0)]
    result = apply_residual_adjustment(baseline, None, {"baseline_points": {30: 120.0}})

    assert result.applied is False
    assert result.adjusted_series == baseline
    assert result.ml_prediction is None
    assert result.ml_band is None


def test_residual_inference_without_features_falls_back_to_baseline():
    baseline = [ForecastPoint(t_min=0, bg=110.0), ForecastPoint(t_min=30, bg=120.0)]
    bundle = ResidualModelBundle(
        root=Path("/tmp/residual_missing"),
        models={},
        ml_ready=True,
        metrics=None,
        confidence_score=None,
    )

    result = apply_residual_adjustment(baseline, bundle, None)

    assert result.applied is False
    assert result.adjusted_series == baseline
    assert result.ml_prediction is None
    assert result.ml_band is None
