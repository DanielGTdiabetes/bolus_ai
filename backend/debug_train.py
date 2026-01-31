
import asyncio
import logging
import sys
import os
from sqlalchemy import text
from app.core.db import get_engine
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.ml_trainer_service import MLTrainerService
from app.core.settings import get_settings

# Configure Logging to Stdout
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger("debug_train")

async def main():
    print("--- STARTING MANUAL ML TRAINING DEBUG ---")
    
    settings = get_settings()
    print(f"DEBUG: ML_TRAINING_ENABLED = {settings.ml.training_enabled}")
    print(f"DEBUG: ML_MODEL_DIR = {settings.ml.model_dir}")
    print(f"DEBUG: MIN_SAMPLES = {settings.ml.min_training_samples}")
    
    # Force enable if false, just for this run? No, let's respect env but warn.
    if not settings.ml.training_enabled:
        print("WARNING: Training is DISABLED in settings. Forcing it temporarily for this script...")
        settings.ml.training_enabled = True

    engine = get_engine()
    if not engine:
        print("ERROR: database.url not found or invalid.")
        return

    async with AsyncSession(engine) as session:
        # Get users
        print("DEBUG: Fetching users...")
        try:
            res = await session.execute(text("SELECT username FROM users"))
            users = [r[0] for r in res.fetchall()]
        except Exception as e:
            print(f"ERROR: Could not fetch users: {e}")
            # Fallback for dev
            users = ["admin"]

        print(f"DEBUG: Found users: {users}")

        trainer = MLTrainerService(session)
        
        for user in users:
            print(f"--- Processing User: {user} ---")
            try:
                res = await trainer.train_user_model(user)
                print(f"RESULT: {res}")
                
                if res.get("status") == "success":
                    print("SUCCESS! Model trained and saved.")
                    # Inspect output dir
                    out_dir = settings.ml.model_dir
                    if out_dir:
                        print(f"CHECK: Please check directory: {out_dir}")
                else:
                    print(f"FAILURE/SKIP: {res.get('reason')}")
                    
            except Exception as e:
                print(f"CRITICAL ERROR during training: {e}")
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    # Fix import paths if running as script
    sys.path.append(os.getcwd())
    asyncio.run(main())
