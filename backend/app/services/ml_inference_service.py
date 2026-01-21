
import logging
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

# Attempt to import CatBoost
try:
    from catboost import CatBoostRegressor
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False

from app.core.settings import get_settings
from app.models.forecast import ForecastPoint

logger = logging.getLogger(__name__)

@dataclass
class MLPredictionResult:
    predicted_series: List[ForecastPoint]
    p10_series: Optional[List[ForecastPoint]] = None
    p90_series: Optional[List[ForecastPoint]] = None
    ml_ready: bool = False
    confidence_score: float = 0.0
    used_model_version: Optional[str] = None
    warnings: List[str] = None

class MLInferenceService:
    _instance = None
    _models: Dict[int, Dict[str, Any]] = {}  # {horizon: {'p10': model, 'p50': model, 'p90': model}}
    _model_version: Optional[str] = None
    _metadata: Optional[Dict] = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = MLInferenceService()
        return cls._instance

    def __init__(self):
        self.settings = get_settings()
        self.models_loaded = False
        # Do strictly nothing heavy in init. Load on first use or explicit reload.

    def _locate_models(self) -> Optional[Path]:
        """
        Find the best available model directory.
        Priority:
        1. Configured ML_MODEL_PATH env var
        2. backend/ml_training_output/latest_ready (symlink or conceptual)
        3. Scan backend/ml_training_output for newest folder with 'ml_ready' in report
        """
        # 1. Explicit Path
        manual_path = self.settings.ml_model_path # Assuming added to settings or os.getenv
        if manual_path: 
            p = Path(manual_path)
            if p.exists() and p.is_dir():
                return p
        
        # 2. Scan default output dir
        base_dir = Path(self.settings.data.data_dir).parent / "ml_training_output"
        # Or relative to repo root if data_dir is absolute: /app/backend/data -> /app/backend/ml_training_output
        # Fallback to local typical path
        if not base_dir.exists():
            base_dir = Path("backend/ml_training_output")
        
        if not base_dir.exists():
            return None
        
        # Find subdirs starting with "residual_"
        candidates = sorted(list(base_dir.glob("residual_*")), key=lambda f: f.stat().st_mtime, reverse=True)
        
        for d in candidates:
            # Check if it has a metadata.json
            meta_path = d / "metadata.json"
            if meta_path.exists():
                return d
        
        return None

    def load_models(self, force_reload: bool = False):
        if self.models_loaded and not force_reload:
            return

        if not HAS_CATBOOST:
            logger.warning("CatBoost not installed. ML inference disabled.")
            return

        model_dir = self._locate_models()
        if not model_dir:
            logger.info("No ML models found. Skipping load.")
            return

        try:
            logger.info(f"Loading ML models from {model_dir}...")
            
            # Load metadata
            with open(model_dir / "metadata.json", "r") as f:
                self._metadata = json.load(f)
                self._model_version = self._metadata.get("version", "unknown")

            horizons = self._metadata.get("horizons", [30, 60, 120, 240, 360])
            quantiles = [0.1, 0.5, 0.9] # p10, p50, p90
            
            loaded_count = 0
            new_models = {}

            for h in horizons:
                new_models[h] = {}
                for q in quantiles:
                    fname = f"catboost_residual_{h}m_p{int(q*100)}.cbm"
                    fpath = model_dir / fname
                    if fpath.exists():
                        model = CatBoostRegressor()
                        model.load_model(str(fpath))
                        
                        key = "p50"
                        if q == 0.1: key = "p10"
                        if q == 0.9: key = "p90"
                        
                        new_models[h][key] = model
                        loaded_count += 1
            
            self._models = new_models
            self.models_loaded = True
            logger.info(f"Successfully loaded {loaded_count} ML models (Version: {self._model_version})")

        except Exception as e:
            logger.error(f"Failed to load ML models: {e}")

    def _interpolate_series(self, 
                          horizons: List[int], 
                          predictions: Dict[int, float], 
                          start_val: float,
                          steps_per_hour: int = 12) -> List[ForecastPoint]:
        """
        Interpolate point predictions (residuals or absolute) into a 5-min series.
        horizons: [30, 60, 120...]
        predictions: {30: val, 60: val...}
        start_val: value at t=0
        """
        # Create X, Y points for interpolation
        # X=0, Y=0 (Start residual is 0 by definition, deviation grows over time)
        # Actually start_val passed here is likely the residual at t=0 which is 0.
        
        x_points = [0] + sorted(horizons)
        y_points = [start_val] + [predictions[h] for h in sorted(horizons)]
        
        # Max horizon
        max_h = max(horizons)
        
        # Linear Interp
        series = []
        for t in range(0, max_h + 5, 5):
            val = np.interp(t, x_points, y_points)
            series.append(ForecastPoint(t_min=t, bg=float(val)))
            
        return series

    def predict(
        self, 
        features: Dict[str, Any], 
        baseline_series: List[ForecastPoint]
    ) -> MLPredictionResult:
        """
        Run inference.
        features: Dict matching training features structure.
        baseline_series: The physics-based forecast series.
        """
        if not self.models_loaded or not self._models:
            return MLPredictionResult([], ml_ready=False, warnings=["Models not loaded"])

        # Validate Features
        # CatBoost handles missing values (NaN) if configured, but cleaner to fill defaults
        # We assume caller formatted features roughly correct.
        
        # Prepare Dataframe Row (Single prediction)
        # We need to construct the baseline_bg_{h}m features from the provided baseline_series
        
        row = features.copy()
        
        # Extract baseline points
        baseline_map = {p.t_min: p.bg for p in baseline_series}
        
        # Add baseline_bg_Xm features
        horizons = sorted(list(self._models.keys()))
        valid_horizons = []
        
        for h in horizons:
            # Find closest point in baseline series
            val = baseline_map.get(h)
            if val is None:
                # Interpolate/Nearest
                # assuming baseline_series is sorted and 5min steps
                # simple find
                closest = min(baseline_map.keys(), key=lambda t: abs(t-h))
                if abs(closest - h) <= 15:
                    val = baseline_map[closest]
                else:
                    # Baseline missing for this horizon?
                    val = None
            
            if val is not None:
                row[f"baseline_bg_{h}m"] = val
                valid_horizons.append(h)
            else:
                row[f"baseline_bg_{h}m"] = np.nan

        # Convert to DataFrame (CatBoost expectation)
        df_row = pd.DataFrame([row])
        
        # Ensure categorical columns are strings
        cat_cols = [
            "trend", "iob_status", "cob_status", "source_consistency_status"
        ]
        for col in cat_cols:
            if col in df_row.columns:
                df_row[col] = df_row[col].fillna("unknown").astype(str)
        
        # Run Inference per horizon
        residuals_p50 = {}
        residuals_p10 = {}
        residuals_p90 = {}
        
        for h in valid_horizons:
            models = self._models.get(h)
            if not models: continue
            
            # Predict P50
            if "p50" in models:
                try:
                    pred_res = models["p50"].predict(df_row)[0]
                    residuals_p50[h] = pred_res
                except Exception as e:
                    logger.warning(f"Inference error H{h} p50: {e}")
            
            # Predict P10/P90
            if "p10" in models and "p90" in models:
                 try:
                    r10 = models["p10"].predict(df_row)[0]
                    r90 = models["p90"].predict(df_row)[0]
                    residuals_p10[h] = r10
                    residuals_p90[h] = r90
                 except: pass

        if not residuals_p50:
            return MLPredictionResult([], ml_ready=False, warnings=["Inference produced no results"])

        # Reconstruct Absolute Values
        # Pred = Baseline + Residual
        
        series_p50 = []
        series_p10 = []
        series_p90 = []
        
        # We implement Safety Clamping here
        # Max deviation allowed from baseline?
        # e.g. If residual demands +200 mg/dL, maybe dampen it?
        # Let's start raw, interpolate residuals, then add to baseline.
        
        interp_res_p50 = self._interpolate_series(list(residuals_p50.keys()), residuals_p50, start_val=0.0)
        
        # For band, if we have enough points, interpolate. Else skip band.
        has_band = len(residuals_p10) == len(residuals_p50)
        interp_res_p10 = self._interpolate_series(list(residuals_p10.keys()), residuals_p10, start_val=0.0) if has_band else []
        interp_res_p90 = self._interpolate_series(list(residuals_p90.keys()), residuals_p90, start_val=0.0) if has_band else []
        
        baseline_lookup = {p.t_min: p.bg for p in baseline_series}
        max_t = baseline_series[-1].t_min if baseline_series else 0
        
        final_series_p50 = []
        final_series_p10 = []
        final_series_p90 = []
        
        for pt in interp_res_p50:
            t = pt.t_min
            if t > max_t: break
            base = baseline_lookup.get(t)
            if base is None: continue
            
            # Safety Clamp on Residual
            # Example: Max surge +100, max drop -100
            residual = max(-100, min(100, pt.bg))
            
            val_p50 = base + residual
            # Physio Clamp
            val_p50 = max(20, min(400, val_p50))
            
            final_series_p50.append(ForecastPoint(t_min=t, bg=round(val_p50, 1)))
            
            if has_band:
                # Same logic for bands
                # P10
                pt10_res = next((p.bg for p in interp_res_p10 if p.t_min == t), 0)
                val_p10 = max(20, min(400, base + pt10_res))
                final_series_p10.append(ForecastPoint(t_min=t, bg=round(val_p10, 1)))
                
                # P90
                pt90_res = next((p.bg for p in interp_res_p90 if p.t_min == t), 0)
                val_p90 = max(20, min(400, base + pt90_res))
                # Ensure p90 >= p10
                if val_p90 < val_p10: val_p90 = val_p10
                final_series_p90.append(ForecastPoint(t_min=t, bg=round(val_p90, 1)))

        return MLPredictionResult(
            predicted_series=final_series_p50,
            p10_series=final_series_p10 if has_band else None,
            p90_series=final_series_p90 if has_band else None,
            ml_ready=True,
            confidence_score=0.8 if has_band else 0.5, # Placeholder Logic
            used_model_version=self._model_version
        )

