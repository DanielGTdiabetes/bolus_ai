
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
import uuid

from app.core.db import get_db_session
from app.core.security import get_current_user
from app.services.suggestion_engine import generate_suggestions_service, get_suggestions_service, resolve_suggestion_service
from app.services.settings_service import get_user_settings_service, update_user_settings_service
from app.models.settings import UserSettings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/suggestions", tags=["suggestions"])

# --- Models ---

# --- Models ---
class GenerateRequest(BaseModel):
    days: int = 30

class ResolveRequest(BaseModel):
    note: Optional[str] = ""
    proposed_change: Optional[dict] = None

class SuggestionResponse(BaseModel):
    id: uuid.UUID
    meal_slot: str
    parameter: str
    direction: str
    reason: str
    evidence: dict
    status: str
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None
    
    class Config:
        from_attributes = True

class EvaluationResponse(BaseModel):
    id: uuid.UUID
    suggestion_id: uuid.UUID
    analysis_days: int
    status: str
    result: Optional[str] = None
    summary: Optional[str] = None
    evidence: Optional[dict] = None
    evaluated_at: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

# --- Endpoints ---

@router.post("/generate")
async def generate_suggestions(
    payload: GenerateRequest = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    valid_payload = payload or GenerateRequest()
    
    # Fetch settings context
    from app.services.settings_service import get_user_settings_service
    from app.models.settings import UserSettings
    
    data = await get_user_settings_service(user.id, db)
    settings_obj = None
    if data and data.get("settings"):
         settings_obj = UserSettings.migrate(data["settings"])
         dt = data.get("updated_at")
         if dt:
             settings_obj.updated_at = dt
             
    result = await generate_suggestions_service(user.id, valid_payload.days, db, settings=settings_obj)
    return result

@router.get("", response_model=List[SuggestionResponse])
async def list_suggestions(
    status: str = "pending",
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    results = await get_suggestions_service(user.id, status, db)
    return results

@router.post("/{id}/accept")
async def accept_suggestion(
    id: uuid.UUID,
    payload: ResolveRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    
    # 1. Attempt to apply settings change if provided
    if payload.proposed_change:
        try:
            pc = payload.proposed_change
            slot = pc.get("meal_slot")
            param = pc.get("parameter")
            val = pc.get("new_value")
            
            if slot and param and val is not None:
                # Fetch current
                s_data = await get_user_settings_service(user.id, db)
                if s_data and s_data.get("settings"):
                    current_settings = UserSettings.migrate(s_data["settings"])
                    ver = s_data.get("version", 0)
                    
                    updated = False
                    # Map params (frontend uses 'icr', 'isf', 'target')
                    if param == "icr" and hasattr(current_settings.cr, slot):
                        setattr(current_settings.cr, slot, float(val))
                        updated = True
                    elif param == "isf" and hasattr(current_settings.cf, slot):
                        setattr(current_settings.cf, slot, float(val))
                        updated = True
                    elif param == "target":
                        # Try specific slot first, else ignored or global logic needed (schema v2 has per-slot targets)
                        if hasattr(current_settings.targets, slot):
                            # Slot specific target (if supported by model)
                            # UserSettings.targets is TargetRange which has breakfast, lunch etc optional
                            setattr(current_settings.targets, slot, int(float(val)))
                            updated = True
                    
                    if updated:
                        new_dict = current_settings.model_dump()
                        # Save
                        await update_user_settings_service(user.id, new_dict, ver, db)
                        logger.info(f"Auto-applied suggestion settings change for {user.id}: {slot} {param} -> {val}")

        except Exception as e:
            logger.error(f"Failed to auto-apply suggestion settings: {e}")
            # We continue to resolve the suggestion even if settings update fails
            # preventing the UI from getting stuck, but logging the error.

    res = await resolve_suggestion_service(id, user.id, "accept", payload.note, db, payload.proposed_change)
    if not res:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"status": "accepted", "id": res.id}

@router.post("/{id}/reject")
async def reject_suggestion(
    id: uuid.UUID,
    payload: ResolveRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    res = await resolve_suggestion_service(id, user.id, "reject", payload.note, db)
    if not res:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"status": "rejected", "id": res.id}

# --- Evaluation Endpoints ---

from app.services.evaluation_engine import evaluate_suggestion_service, list_evaluations_service

@router.post("/{id}/evaluate", response_model=EvaluationResponse)
async def evaluate_suggestion(
    id: uuid.UUID,
    days: int = 7,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    res = await evaluate_suggestion_service(id, user.id, days, db)
    if isinstance(res, dict) and "error" in res:
         raise HTTPException(status_code=400, detail=res["error"])
    return res

@router.get("/evaluations", response_model=List[EvaluationResponse])
async def list_evaluations(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns list of evaluations"""
    return await list_evaluations_service(user.id, db)

@router.delete("/{id}")
async def delete_suggestion(
    id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Hard delete of a suggestion and its linked evaluation.
    Only allows deleting requests owned by the user.
    """
    from sqlalchemy import delete
    from app.models.suggestion import ParameterSuggestion
    from app.models.evaluation import SuggestionEvaluation
    
    # 1. Delete linked evaluation
    stmt_eval = delete(SuggestionEvaluation).where(
        SuggestionEvaluation.suggestion_id == id
    )
    await db.execute(stmt_eval)
    
    # 2. Delete suggestion with ownership check
    # Ensure user.id is string for comparison with String column
    user_id_str = str(user.id)
    
    stmt = delete(ParameterSuggestion).where(
        ParameterSuggestion.id == id,
        ParameterSuggestion.user_id == user_id_str
    )
    res = await db.execute(stmt)
    
    await db.commit()
    
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Suggestion not found or access denied")
        
    return {"status": "deleted", "id": id}

