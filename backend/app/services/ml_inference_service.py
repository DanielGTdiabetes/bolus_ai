
import logging
import os # Added for env var
import json
import threading
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

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ml_store import MLModelStore

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
    source: str = "physics" # "ml" or "physics"

class MLInferenceService:
    _instance = None
    _lock = threading.Lock()
    _models: Dict[int, Dict[str, Any]] = {}  # {horizon: {'p10': model, 'p50': model, 'p90': model}}
    _model_version: Optional[str] = None
    _metadata: Optional[Dict] = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
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
        1. Configured ML_MODEL_DIR env var
        2. backend/ml_training_output (relative to repo root)
        3. /app/backend/ml_training_output (Docker standard)
        """
        # 1. Settings (Env Var already mapped to settings.ml.model_dir)
        if self.settings.ml.model_dir:
            p = Path(self.settings.ml.model_dir)
            if p.exists() and p.is_dir():
                return p
        
        # 2. Relative to this file (backend/app/services/../../ml_training_output)
        # This file is in backend/app/services
        current_file = Path(__file__)
        repo_root = current_file.parent.parent.parent # backend/
        
        candidates = [
            repo_root / "ml_training_output",
            Path("/app/backend/ml_training_output"),
            Path("backend/ml_training_output") # Fallback for cwd
        ]

        for base_dir in candidates:
            if not base_dir.exists():
                continue
            
            # Find subdirs starting with "residual_" (sorted new to old)
            subdirs = sorted(list(base_dir.glob("residual_*")), key=lambda f: f.stat().st_mtime, reverse=True)
            
            for d in subdirs:
                # Check if it has a metadata.json
                if (d / "metadata.json").exists():
                    return d
        
        return None


    async def sync_models_from_db(self, session: AsyncSession):
        """
        Check DB for a newer model version and download it if found.
        Use raw SQL check first to avoid errors if table doesn't exist yet.
        """
        try:
            # Check table existence first
            check = await session.execute(text(f"SELECT to_regclass('public.{MLModelStore.__tablename__}')"))
            if not check.scalar():
                logger.info("ML Sync: Table not found in DB. Skipping sync.")
                return

            # Get latest version from DB
            stmt = select(MLModelStore).where(MLModelStore.model_name == 'metadata.json').order_by(MLModelStore.updated_at.desc()).limit(1)
            res = await session.execute(stmt)
            row = res.scalar_one_or_none()
            
            if not row:
                logger.info("ML Sync: No trained models in DB yet.")
                return

            db_version = row.version
            
            # Compare with local
            if self._metadata and self._metadata.get("version") == db_version:
                logger.info(f"ML Sync: Local model {db_version} is up to date.")
                return

            logger.info(f"ML Sync: Found newer model {db_version} in DB. Downloading...")
            
            # Download all files for this user/version
            # Simple approach: Get all files for this user
            user_id = row.user_id # Assume model fits user
            files_stmt = select(MLModelStore).where(MLModelStore.user_id == user_id).where(MLModelStore.version == db_version)
            files_res = await session.execute(files_stmt)
            files = files_res.scalars().all()
            
            # Target Dir
            # Force use of local writable dir
            target_dir = Path("ml_training_output")
            if self.settings.ml.model_dir:
                target_dir = Path(self.settings.ml.model_dir)
            
            if not target_dir.is_absolute():
                 base = Path(__file__).resolve().parent.parent.parent
                 target_dir = base / target_dir
            
            target_dir.mkdir(parents=True, exist_ok=True)
            
            for file_row in files:
                out_path = target_dir / file_row.model_name
                # If metadata, parse json
                if file_row.model_name == "metadata.json":
                     # meta is bytes, decode
                     try:
                         data_str = file_row.model_data.decode('utf-8')
                         # validate json
                         json.loads(data_str)
                         with open(out_path, "w") as f:
                             f.write(data_str)
                     except:
                         with open(out_path, "wb") as f:
                             f.write(file_row.model_data)
                else:
                    with open(out_path, "wb") as f:
                        f.write(file_row.model_data)
            
            logger.info(f"ML Sync: Successfully downloaded model {db_version}.")
            # Trigger reload
            self.load_models(force_reload=True)
            
        except Exception as e:
            logger.error(f"ML Sync Failed: {e}")

    def load_models(self, force_reload: bool = False):
        if self.models_loaded and not force_reload:
            return

        if not HAS_CATBOOST:
            logger.warning("CatBoost not installed. ML inference disabled.")
            return

        model_dir = self._locate_models()
        if not model_dir:
            logger.info("ML: No model directory found (not trained yet). State: DATA_GATHERING.")
            return

        try:
            logger.info(f"ML: Found model directory at {model_dir}. Verifying artifacts...")
            
            # Load metadata
            if not (model_dir / "metadata.json").exists():
                 logger.warning("ML: metadata.json missing in model dir. Refusing to load partial models.")
                 return
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
            logger.info(f"Successfully loaded {loaded_count} ML models (Version: {self._model_version}). State: ACTIVE.")

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
            return MLPredictionResult([], ml_ready=False, warnings=["Models not loaded"], source="physics")

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

        # Remove non-feature columns that shouldn't be passed to CatBoost
        non_feature_cols = [
            "feature_time", "user_id", "source_ns_enabled",
            "source_ns_treatments_count", "source_db_treatments_count",
            "source_overlap_count", "source_conflict_count"
        ]
        for col in non_feature_cols:
            row.pop(col, None)

        # Convert boolean flags to int (CatBoost expects numeric)
        bool_cols = [
            "flag_bg_missing", "flag_bg_stale", "flag_iob_unavailable",
            "flag_cob_unavailable", "flag_source_conflict"
        ]
        for col in bool_cols:
            if col in row and isinstance(row[col], bool):
                row[col] = 1 if row[col] else 0

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
            return MLPredictionResult([], ml_ready=False, warnings=["Inference produced no results"], source="physics")

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
            clamp_val = self.settings.ml.safety_clamp_mgdl
            residual = max(-clamp_val, min(clamp_val, pt.bg))
            
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
            used_model_version=self._model_version,
            source="ml"
        )

