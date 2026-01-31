
import logging
import json
import shutil
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.settings import get_settings
from app.services.ml_inference_service import MLInferenceService
from app.models.ml_store import MLModelStore

try:
    from catboost import CatBoostRegressor
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False

logger = logging.getLogger(__name__)

class MLTrainerService:
    """
    Handles automatic training of ML models with strict quality gates.
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    async def _fetch_training_data(self, user_id: str) -> pd.DataFrame:
        stmt = text("""
            SELECT * FROM ml_training_data_v2 
            WHERE user_id = :user_id 
            ORDER BY feature_time ASC
        """)
        result = await self.session.execute(stmt, {"user_id": user_id})
        rows = result.fetchall()
        
        if not rows:
            return pd.DataFrame()
            
        columns = result.keys()
        df = pd.DataFrame(rows, columns=columns)
        
        # Parse feature_time properly
        if not df.empty:
            df["feature_time"] = pd.to_datetime(df["feature_time"])
            
        return df

    def _prepare_target_columns(self, df: pd.DataFrame, horizons=[30, 60, 120, 240, 360]) -> pd.DataFrame:
        """
        Calculate target residuals for training.
        Target = (Actual Future BG) - (Baseline Physics Forecast at that future time)
        
        Note: The 'baseline_bg_Xm' columns in the DB are the forecasts made AT feature_time for feature_time+X.
        We need to match row[t] with row[t+X]['bg_mgdl'].
        """
        df = df.sort_values("feature_time").copy()
        df.set_index("feature_time", inplace=True)
        
        # Forward fill essential holes (small)
        # df["bg_mgdl"] = df["bg_mgdl"].interpolate(method="time", limit=3)
        
        for h in horizons:
            # Shift BG backwards to bring future value to current row
            # target_bg_h = BG at t+h
            # We can use shift(-h // 5) if data is perfectly 5 min, but better to reindex
            
            # Create a shifter series
            future_bg = df["bg_mgdl"].shift(periods=int(-h/5)) 
            # Note: this assumes uniform 5 min spacing. 
            # Ideally reindex to 5min frequency to be safe.
            
            # Calculate Residual
            # Target Residual = Actual Future - Baseline Forecast
            baseline_col = f"baseline_bg_{h}m"
            if baseline_col in df.columns:
                 df[f"target_residual_{h}m"] = future_bg - df[baseline_col]
        
        df.reset_index(inplace=True)
        return df


    async def _safe_create_store_table(self):
        """Create MLModelStore table if not exists (raw SQL to avoid Alembic issues)"""
        try:
            # Check if table exists
            table_name = MLModelStore.__tablename__
            check_sql = text(f"SELECT to_regclass('public.{table_name}')")
            res = await self.session.execute(check_sql)
            if res.scalar():
                return

            logger.info("ML: Auto-creating storage table...")
            create_sql = text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                model_name VARCHAR NOT NULL,
                user_id VARCHAR NOT NULL,
                model_data BYTEA NOT NULL,
                version VARCHAR,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                PRIMARY KEY (model_name, user_id)
            );
            """)
            await self.session.execute(create_sql)
            await self.session.commit()
        except Exception as e:
            logger.warning(f"ML: Could not ensure table: {e}")
            # Ignore error, maybe existing or permissions

    async def train_user_model(self, user_id: str) -> Dict[str, Any]:
        """
        Main entry point. Checks gates, trains, validates, persists.
        """
        ml_cfg = self.settings.ml
        
        # 1. Check Feature Flags
        if not ml_cfg.training_enabled:
             return {"status": "skipped", "reason": "settings.ml.training_enabled is False"}
             
        # 2. Check Environment Gating
        is_nas = bool(self.settings.nas_public_url) or ml_cfg.allow_training_on_ephemeral
        # If we are strictly on Render (no NAS URL) and allow_ephemeral is False -> Skip
        # But nas_public_url logic is weak. Let's rely on explicit config or safe default.
        # Safe default: Only train if allow_training_on_ephemeral is True OR we are sure we are persistent.
        # For now, rely on `training_enabled` which user must opt-in.
        
        # 3. Load Data
        df = await self._fetch_training_data(user_id)
        if df.empty:
            return {"status": "skipped", "reason": "No data found"}
            
        # 4. Check Sample Count Gate
        sample_count = len(df)
        if sample_count < ml_cfg.min_training_samples:
            return {
                "status": "skipped", 
                "reason": f"Insufficient samples: {sample_count} < {ml_cfg.min_training_samples}. State: DATA_GATHERING."
            }
            
        # 5. Check Time Span Gate
        min_date = df["feature_time"].min()
        max_date = df["feature_time"].max()
        days_covered = (max_date - min_date).total_seconds() / 86400
        
        if days_covered < ml_cfg.min_days_history:
             return {
                "status": "skipped", 
                "reason": f"Insufficient history duration: {days_covered:.1f} days < {ml_cfg.min_days_history} days"
            }

        # 6. Check Retrain Interval
        # Look for existing model metadata
        svc = MLInferenceService.get_instance()
        current_meta = svc._metadata
        if current_meta:
             created_ts = current_meta.get("created_at_ts")
             if created_ts:
                 last_train = datetime.fromtimestamp(created_ts, tz=timezone.utc)
                 hours_since = (datetime.now(timezone.utc) - last_train).total_seconds() / 3600
                 if hours_since < ml_cfg.retrain_interval_hours:
                      return {"status": "skipped", "reason": f"Recently trained ({hours_since:.1f}h ago)"}

        # 7. Prepare Training Data
        if not HAS_CATBOOST:
            return {"status": "error", "reason": "CatBoost not installed"}

        logger.info(f"ML: Starting training for {user_id}. Samples={sample_count}, Days={days_covered:.1f}")
        
        df_train = self._prepare_target_columns(df)
        
        # Features to use (exclude meta columns)
        feature_cols = [
            "bg_mgdl", "trend", "iob_u", "cob_g", "basal_active_u", 
            "basal_total_24h", "bolus_total_3h", "carbs_total_3h",
            "exercise_minutes_6h", "hour_of_day", "day_of_week"
        ]
        # Dynamically add available features from schema if needed (like baseline_bg_Xm)
        # We include baseline forecasts as inputs? Yes, correction model.
        horizons = [30, 60, 120, 240, 360]
        for h in horizons:
            feature_cols.append(f"baseline_bg_{h}m")
            
        # Clean Data (Drop rows where target is NaN)
        # We handle categorical Features
        cat_features = ["trend"]
        
        metrics = {}
        models = {}
        
        # Define output directory
        out_dir = self._ensure_model_dir()
        
        # Training Loop
        total_mae = 0
        valid_models_count = 0
        
        for h in horizons:
            target_col = f"target_residual_{h}m"
            if target_col not in df_train.columns: continue
            
            # Subset valid data
            train_subset = df_train.dropna(subset=[target_col] + feature_cols)
            if len(train_subset) < 500: # Min samples per horizon
                logger.warning(f"ML: Not enough aligned samples for H{h} ({len(train_subset)})")
                continue
                
            X = train_subset[feature_cols]
            y = train_subset[target_col]
            
            # Treat categorical
            for c in cat_features:
                 if c in X.columns:
                     X[c] = X[c].astype(str)
            
            # Train CatBoost
            model = CatBoostRegressor(
                iterations=500, 
                learning_rate=0.05, 
                depth=6, 
                loss_function='RMSE',
                verbose=False,
                allow_writing_files=False
            )
            model.fit(X, y, cat_features=cat_features if "trend" in X.columns else None)
            
            # Eval (simple in-sample for sanity check, or simple split)
            # For "Anti-Humo", we want to know if it learned ANYTHING.
            preds = model.predict(X)
            mae = np.mean(np.abs(preds - y))
            rmse = np.sqrt(np.mean((preds - y)**2))
            
            metrics[h] = {"mae": float(mae), "rmse": float(rmse), "n": len(X)}
            total_mae += mae
            
            # Save Artifact
            fname = f"catboost_residual_{h}m_p50.cbm"
            model.save_model(str(out_dir / fname))
            valid_models_count += 1
            
            # (Optional) We could train quantile models p10/p90 here too
        
        if valid_models_count == 0:
             return {"status": "failed", "reason": "Could not train any valid horizon model"}
             
        avg_mae = total_mae / valid_models_count
        
        # 8. Integrity/Quality Check
        if avg_mae > float(ml_cfg.model_quality_max_rmse): # Lazy using RMSE threshold for MAE check or similar
             logger.warning(f"ML: Model rejected due to high error. MAE={avg_mae:.1f}")
             # Cleanup artifacts?
             return {"status": "rejected", "reason": f"Quality too low (MAE {avg_mae:.1f} > {ml_cfg.model_quality_max_rmse})"}

        # 9. Save Metadata
        version = f"v1-{datetime.now().strftime('%Y%m%d%H%M')}"
        meta = {
            "version": version,
            "created_at": datetime.now().isoformat(),
            "created_at_ts": datetime.now(timezone.utc).timestamp(),
            "user_id": user_id,
            "samples_total": sample_count,
            "days_covered": days_covered,
            "horizons": horizons,
            "metrics": metrics,
            "avg_mae": avg_mae
        }
        
        with open(out_dir / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2)
            
        logger.info("ML: Training completed successfully. Uploading to DB...")

        # 10. Persist to DB (for Render Sync)
        await self._safe_create_store_table()
        
        # 10.1 Upload Metadata
        meta_json_str = json.dumps(meta).encode('utf-8')
        await self.session.merge(MLModelStore(
            model_name="metadata.json",
            user_id=user_id,
            model_data=meta_json_str,
            version=version
        ))

        # 10.2 Upload Models
        for h in metrics.keys(): # Only upload success horizons
            fname = f"catboost_residual_{h}m_p50.cbm"
            fpath = out_dir / fname
            if fpath.exists():
                with open(fpath, "rb") as f:
                    bin_data = f.read()
                await self.session.merge(MLModelStore(
                    model_name=fname,
                    user_id=user_id,
                    model_data=bin_data,
                    version=version
                ))
        
        await self.session.commit()
        logger.info("ML: Models synced to Database (accessible by Render)")

        # 11. Reload Inference Service
        svc.load_models(force_reload=True)
        
        return {"status": "success", "metadata": meta}

    def _ensure_model_dir(self) -> Path:
        """
        Guarantees that the ML model directory exists.
        """
        # Resolve path logic same as locate but for writing
        raw_path = self.settings.ml.model_dir
        if raw_path:
             out_dir = Path(raw_path)
             if not out_dir.is_absolute():
                  # Anchor to backend root if relative
                  base = Path(__file__).resolve().parent.parent.parent
                  out_dir = base / out_dir
        else:
             # Default fallback
             base = Path(__file__).resolve().parent.parent.parent
             out_dir = base / "ml_training_output"
             
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir
