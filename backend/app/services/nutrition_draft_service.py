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
    async def get_draft(user_id: str, session: Any) -> Optional[NutritionDraft]:
        from app.models.draft_db import NutritionDraftDB
        from sqlalchemy import select
        
        # Async query
        stmt = select(NutritionDraftDB).where(NutritionDraftDB.user_id == user_id, NutritionDraftDB.status == "active")
        res = await session.execute(stmt)
        draft_db = res.scalars().first()
        
        if not draft_db:
            return None
            
        # Check expiry
        now = datetime.now(timezone.utc)
        if draft_db.expires_at.tzinfo is None:
             draft_db.expires_at = draft_db.expires_at.replace(tzinfo=timezone.utc)
        
        if draft_db.expires_at < now:
             return None
             
        # Convert to Pydantic for API consistency
        return NutritionDraft(
            id=draft_db.id,
            user_id=draft_db.user_id,
            carbs=draft_db.carbs,
            fat=draft_db.fat,
            protein=draft_db.protein,
            fiber=draft_db.fiber,
            created_at=draft_db.created_at,
            updated_at=draft_db.updated_at,
            expires_at=draft_db.expires_at,
            status=draft_db.status,
            last_hash=draft_db.last_hash
        )

    @staticmethod
    async def discard_draft(user_id: str, session: Any, draft_id: Optional[str] = None):
        from app.models.draft_db import NutritionDraftDB
        from sqlalchemy import select
        
        # Soft delete or hard? Requirement says "discarded". Let's update status.
        # Actually API logic removed it. Let's mark as discarded or delete.
        # Prompt said "status: discarded".
        if draft_id:
            stmt = select(NutritionDraftDB).where(
                NutritionDraftDB.user_id == user_id,
                NutritionDraftDB.id == draft_id,
                NutritionDraftDB.status == "active",
            )
        else:
            stmt = select(NutritionDraftDB).where(
                NutritionDraftDB.user_id == user_id,
                NutritionDraftDB.status == "active",
            )
        res = await session.execute(stmt)
        draft = res.scalars().first()
        if draft:
            draft.status = "discarded"
            session.add(draft)
            await session.commit()

    @staticmethod
    async def close_draft_to_treatment(
        user_id: str,
        session: Any,
        draft_id: Optional[str] = None,
    ) -> Tuple[Optional[Treatment], bool, bool]:
        from app.models.draft_db import NutritionDraftDB
        from sqlalchemy import update
        from sqlalchemy import select
        
        # Atomic Update: "Claim" the draft by setting status to closed.
        # Only the request that actually changes status from 'active' to 'closed' will get a result.
        if draft_id:
            stmt = (
                update(NutritionDraftDB)
                .where(
                    NutritionDraftDB.user_id == user_id,
                    NutritionDraftDB.id == draft_id,
                    NutritionDraftDB.status == "active",
                )
                .values(status="closed")
                .returning(NutritionDraftDB)
            )
        else:
            stmt = (
                update(NutritionDraftDB)
                .where(NutritionDraftDB.user_id == user_id, NutritionDraftDB.status == "active")
                .values(status="closed")
                .returning(NutritionDraftDB)
            )
        
        res = await session.execute(stmt)
        draft_db = res.scalars().first()
        
        if not draft_db:
            if draft_id:
                existing = await session.execute(
                    select(Treatment).where(Treatment.draft_id == draft_id)
                )
                treatment = existing.scalars().first()
                if treatment:
                    logger.info(
                        "draft_close_idempotent_hit",
                        extra={"draft_id": draft_id, "treatment_id": treatment.id},
                    )
                    return treatment, False, False
            return None, False, False
            
        # Treat as orphans for now, frontend will see them
        import uuid
        tid = str(uuid.uuid4())
        
        existing = await session.execute(
            select(Treatment).where(Treatment.draft_id == draft_db.id)
        )
        existing_treatment = existing.scalars().first()
        if existing_treatment:
            logger.info(
                "draft_close_idempotent_exists",
                extra={"draft_id": draft_db.id, "treatment_id": existing_treatment.id},
            )
            return existing_treatment, False, True

        t = Treatment(
            id=tid,
            user_id=user_id,
            event_type="Meal Bolus",
            created_at=datetime.now(), # Local naive
            insulin=0.0,
            carbs=draft_db.carbs,
            fat=draft_db.fat,
            protein=draft_db.protein,
            fiber=draft_db.fiber,
            notes="Draft confirmed #draft",
            entered_by="draft-service",
            is_uploaded=False,
            draft_id=draft_db.id,
        )
        
        # Treatment is created but not yet added/committed. 
        # The DRAFT update IS in the session transaction pending commit.
        
        logger.info(
            "draft_closed_to_treatment",
            extra={"draft_id": draft_db.id, "treatment_id": tid},
        )
        return t, True, True

    @staticmethod
    async def update_draft(user_id: str, new_c: float, new_f: float, new_p: float, new_fib: float, session: Any) -> Tuple[NutritionDraft, str]:
        """
        Returns (Draft, action_taken)
        action_taken: 'created', 'updated_replace', 'updated_add'
        """
        from app.models.draft_db import NutritionDraftDB
        from sqlalchemy import select
        
        # Config
        try:
            window_min = int(os.environ.get("NUTRITION_DRAFT_WINDOW_MIN", 30))
        except:
            window_min = 30
            
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(minutes=window_min)
        
        # Fetch Active
        stmt = select(NutritionDraftDB).where(NutritionDraftDB.user_id == user_id, NutritionDraftDB.status == "active")
        res = await session.execute(stmt)
        current_db = res.scalars().first()
        
        # Check Expiry of existing
        if current_db:
             if current_db.expires_at.tzinfo is None:
                 current_db.expires_at = current_db.expires_at.replace(tzinfo=timezone.utc)

             if current_db.expires_at < now:
                # Expired -> Overwrite/Reset by treating as not found or closing old?
                # Let's reuse row or mark old expired and create new?
                # Reuse is cleaner for ID stability if needed, but logic says "if expired, create new".
                current_db.status = "expired"
                session.add(current_db)
                current_db = None
            
        if not current_db:
             # Create New
             new_draft = NutritionDraftDB(
                 user_id=user_id,
                 carbs=new_c,
                 fat=new_f,
                 protein=new_p,
                 fiber=new_fib,
                 expires_at=expiry,
                 status="active"
             )
             session.add(new_draft)
             await session.commit()
             await session.refresh(new_draft)
             
             return NutritionDraft(
                 id=new_draft.id,
                 user_id=user_id,
                 carbs=new_c,
                 fat=new_f,
                 protein=new_p,
                 fiber=new_fib,
                 created_at=new_draft.created_at,
                 updated_at=new_draft.updated_at,
                 expires_at=new_draft.expires_at,
                 status="active"
             ), "created"

        # --- MERGE LOGIC ---
        SMALL_C = 40.0
        SMALL_F = 20.0
        EPSILON = 5.0
        
        is_small = (new_c < SMALL_C and new_f < SMALL_F and new_p < SMALL_F)
        
        diff_c = abs(current_db.carbs - new_c)
        diff_f = abs(current_db.fat - new_f)
        is_similar = (diff_c < EPSILON and diff_f < EPSILON)
        
        action = "updated_replace"
        final_c, final_f, final_p, final_fib = new_c, new_f, new_p, new_fib
        
        if is_similar:
             action = "updated_replace"
        elif is_small:
             action = "updated_add"
             final_c = current_db.carbs + new_c
             final_f = current_db.fat + new_f
             final_p = current_db.protein + new_p
             final_fib = current_db.fiber + new_fib
        else:
             action = "updated_replace"
        
        current_db.carbs = float(round(final_c, 1))
        current_db.fat = float(round(final_f, 1))
        current_db.protein = float(round(final_p, 1))
        current_db.fiber = float(round(final_fib, 1))
        current_db.updated_at = now
        current_db.expires_at = expiry
        
        session.add(current_db)
        await session.commit()
        await session.refresh(current_db)
        
        return NutritionDraft(
            id=current_db.id,
            user_id=user_id,
            carbs=current_db.carbs,
            fat=current_db.fat,
            protein=current_db.protein,
            fiber=current_db.fiber,
            created_at=current_db.created_at,
            updated_at=current_db.updated_at,
            expires_at=current_db.expires_at,
            status="active",
        ), action
