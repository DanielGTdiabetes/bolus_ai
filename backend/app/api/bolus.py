from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.datastore import EventStore
from app.core.security import auth_required
from app.core.settings import Settings, get_settings

router = APIRouter()


def _event_store(settings: Settings = Depends(get_settings)) -> EventStore:
    return EventStore(Path(settings.data.data_dir) / "events.json")


class BolusRequest(BaseModel):
    carbs: float = Field(ge=0)
    glucose: float = Field(ge=0)
    high_fat: bool = False
    exercise_type: str | None = None
    exercise_timing: str | None = None
    delay_minutes: int = 0


class BolusRecommendation(BaseModel):
    upfront: float
    later: float
    delay_minutes: int
    explanation: list[str]


@router.post("/recommend", response_model=BolusRecommendation, summary="Recommend bolus")
async def recommend(payload: BolusRequest, _: str = Depends(auth_required)):
    base = payload.carbs * 0.1
    adjustment = 0.0
    if payload.high_fat:
        adjustment += 0.5
    if payload.exercise_type:
        adjustment -= 0.2
    return BolusRecommendation(
        upfront=round(base + adjustment, 2),
        later=max(round(base * 0.2, 2), 0.0),
        delay_minutes=payload.delay_minutes,
        explanation=[
            "Cálculo simple basado en carbohidratos",
            "Ajuste manual para grasas/exercise",
        ],
    )


class EventRequest(BaseModel):
    title: str
    data: dict


@router.post("/events", summary="Guardar evento")
async def save_event(payload: EventRequest, _: str = Depends(auth_required), store: EventStore = Depends(_event_store)):
    events = store.load()
    events.append({"title": payload.title, "data": payload.data})
    store.save(events)
    return {"ok": True}
