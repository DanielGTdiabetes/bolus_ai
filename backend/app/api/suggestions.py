
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
import uuid

from app.core.db import get_db_session
from app.core.security import get_current_user
from app.services.suggestion_engine import generate_suggestions_service, get_suggestions_service, resolve_suggestion_service

router = APIRouter(prefix="/suggestions", tags=["suggestions"])

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
    # ... other fields

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
    result = await generate_suggestions_service(user.id, valid_payload.days, db)
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

@router.post("/{id}/evaluate")
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

@router.get("/evaluations")
async def list_evaluations(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns list of evaluations"""
    return await list_evaluations_service(user.id, db)
