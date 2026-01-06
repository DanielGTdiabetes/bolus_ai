import logging
import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from app.services.store import DataStore
from app.models.draft import NutritionDraft
from app.models.treatment import Treatment
from app.core import config
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

DRAFT_FILE = "nutrition_drafts.json"

def _get_store_path() -> Path:
    settings = get_settings()
    return Path(settings.data.data_dir) / DRAFT_FILE

def _load_drafts() -> Dict[str, dict]:
    path = _get_store_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception as e:
        logger.error(f"Failed to load drafts: {e}")
        return {}

def _save_drafts(data: Dict[str, dict]):
    path = _get_store_path()
    try:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to save drafts: {e}")

class NutritionDraftService:
    @staticmethod
    def get_draft(user_id: str) -> Optional[NutritionDraft]:
        data = _load_drafts()
        raw = data.get(user_id)
        if not raw:
            return None
        
        try:
            draft = NutritionDraft.model_validate(raw)
            # Check expiry
            if draft.is_expired or draft.status != "active":
                # Lazy cleanup? Or return None?
                # If expired, we might want to auto-close it? 
                # For GET, just return it so UI can decide (or cleanup).
                # Logic: If expired, treat as None for "active" usage.
                if draft.is_expired:
                    return None
            return draft
        except Exception:
            return None

    @staticmethod
    def discard_draft(user_id: str):
        data = _load_drafts()
        if user_id in data:
            del data[user_id]
            _save_drafts(data)

    @staticmethod
    def close_draft_to_treatment(user_id: str) -> Optional[Treatment]:
        draft = NutritionDraftService.get_draft(user_id)
        if not draft:
            return None
        
        # Create Treatment
        import uuid
        tid = str(uuid.uuid4())
        
        # Treat as orphans for now, frontend will see them
        t = Treatment(
            id=tid,
            user_id=user_id,
            event_type="Meal Bolus",
            created_at=datetime.now(), # Local naive
            insulin=0.0,
            carbs=draft.carbs,
            fat=draft.fat,
            protein=draft.protein,
            fiber=draft.fiber,
            notes=f"Draft confirmed #draft",
            entered_by="draft-service",
            is_uploaded=False
        )
        
        # Remove draft
        NutritionDraftService.discard_draft(user_id)
        return t

    @staticmethod
    def update_draft(user_id: str, new_c: float, new_f: float, new_p: float, new_fib: float) -> Tuple[NutritionDraft, str]:
        """
        Returns (Draft, action_taken)
        action_taken: 'created', 'updated_replace', 'updated_add'
        """
        # Config
        try:
            window_min = int(os.environ.get("NUTRITION_DRAFT_WINDOW_MIN", 30))
        except:
            window_min = 30
            
        data = _load_drafts()
        raw = data.get(user_id)
        
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(minutes=window_min)
        
        # New Valid Draft Object
        # If no existing draft, create one
        if not raw:
            draft = NutritionDraft(
                user_id=user_id,
                carbs=new_c,
                fat=new_f,
                protein=new_p,
                fiber=new_fib,
                expires_at=expiry
            )
            data[user_id] = draft.model_dump()
            _save_drafts(data)
            return draft, "created"

        # Check existing validity
        try:
            current = NutritionDraft.model_validate(raw)
        except:
            current = None

        if not current or current.is_expired:
            # Overwrite expired
            draft = NutritionDraft(
                user_id=user_id,
                carbs=new_c,
                fat=new_f,
                protein=new_p,
                fiber=new_fib,
                expires_at=expiry
            )
            data[user_id] = draft.model_dump()
            _save_drafts(data)
            return draft, "created"

        # --- MERGE LOGIC ---
        # Constants
        SMALL_C = 20.0
        SMALL_F = 15.0
        EPSILON = 2.0
        
        is_small = (new_c < SMALL_C and new_f < SMALL_F and new_p < SMALL_F)
        
        # Similarity check (is it a duplicate/update of same data?)
        diff_c = abs(current.carbs - new_c)
        diff_f = abs(current.fat - new_f)
        
        is_similar = (diff_c < EPSILON and diff_f < EPSILON)
        
        # Decide
        action = "replace"
        final_c, final_f, final_p, final_fib = new_c, new_f, new_p, new_fib
        
        if is_similar:
             # It's an update/correction of existing (or duplicate) -> REPLACE
             action = "updated_replace"
             # Use new values (they might be slightly corrected)
             pass
        elif is_small:
             # Small payload and NOT similar -> ADD (Topping/Dessert)
             action = "updated_add"
             final_c = current.carbs + new_c
             final_f = current.fat + new_f
             final_p = current.protein + new_p
             final_fib = current.fiber + new_fib
        else:
             # Big payload and NOT similar -> REPLACE (Cumulative Update)
             action = "updated_replace"
        
        # Update current
        current.carbs = float(round(final_c, 1))
        current.fat = float(round(final_f, 1))
        current.protein = float(round(final_p, 1))
        current.fiber = float(round(final_fib, 1))
        current.updated_at = now
        current.expires_at = expiry # Extend window
        
        data[user_id] = current.model_dump()
        _save_drafts(data)
        
        return current, action
