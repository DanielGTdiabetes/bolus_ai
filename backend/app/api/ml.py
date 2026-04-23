import logging
from fastapi import APIRouter, Depends
from app.core.security import CurrentUser, get_current_user
from app.services.ml_inference_service import MLInferenceService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/status", summary="ML model status")
async def get_ml_status(
    user: CurrentUser = Depends(get_current_user),
):
    svc = MLInferenceService.get_instance()
    meta = svc._metadata or {}
    
    models_loaded = bool(svc._models)
    quantiles = meta.get("quantiles", [])
    
    return {
        "models_loaded": models_loaded,
        "snapshot_count": meta.get("samples_total", 0),
        "training_enabled": False,  # Would need settings access
        "last_training_status": "unknown",
        "model_version": meta.get("version", None),
        "confidence_score": None,
        "has_quantile_bands": len(quantiles) >= 3,
        "quantiles": quantiles,
        "horizons": meta.get("horizons", []),
        "avg_mae": meta.get("avg_mae", None),
        "is_first_model": meta.get("is_first_model", None),
    }
