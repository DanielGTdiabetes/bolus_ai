
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.db import get_db_session

# ... inside functions replace get_db with get_db_session if needed.
# But wait, replace_file_content must be exact.
# I will do two replaces.

# 1. Fix import
from app.core.db import get_db_session

# ... skipping to next ...


from app.core.settings import get_settings, Settings
from app.services.store import DataStore
from app.models.settings import UserSettings
from app.services.nightscout_client import NightscoutClient
from app.services.pattern_analysis import run_analysis_service, get_summary_service

router = APIRouter()

def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))

@router.post("/bolus/run", summary="Run post-bolus pattern analysis")
async def run_analysis_endpoint(
    payload: dict = Body(...),
    current_user: Any = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
    db: AsyncSession = Depends(get_db_session)
):
    from app.services.settings_service import get_user_settings_service
    
    # Helper to load settings from DB with fallback
    async def _load_settings() -> UserSettings:
        # DB first
        data = await get_user_settings_service(current_user.username, db)
        s_obj = None
        if data and data.get("settings"):
            s_obj = UserSettings.migrate(data["settings"])
            # Inject updated_at for analysis optimization
            dt = data.get("updated_at")
            if dt:
                 s_obj.updated_at = dt
        
        if not s_obj:
            # Fallback to file Store
            s_obj = store.load_settings()
        return s_obj

    days = payload.get("days", 30)
    
    settings = await _load_settings()

    # Resolve Nightscout Credentials (DB Priority)
    from app.services.nightscout_secrets_service import get_ns_config
    
    db_ns_config = await get_ns_config(db, current_user.username)
    
    final_url = None
    final_token = None
    
    if db_ns_config and db_ns_config.enabled and db_ns_config.url:
        final_url = db_ns_config.url
        final_token = db_ns_config.api_secret
    else:
        # Fallback to local settings in store? Actually no, local file store is being deprecated in favor of DB.
        # But let's check store['nightscout'] just in case for legacy transition
        legacy_ns = settings.get("nightscout")
        if legacy_ns and legacy_ns.get("url"):
             final_url = legacy_ns.get("url")
             final_token = legacy_ns.get("token")
        
    client = None
    if final_url:
        client = NightscoutClient(base_url=final_url, token=final_token)
    elif not final_url:
         # If truly no config found anywhere, warn but proceed with DB-only analysis
         pass
    
    try:
        user_id = current_user.username
        
        result = await run_analysis_service(
            user_id=user_id,
            days=days,
            settings=settings,
            ns_client=client,
            db=db
        )
        if "error" in result:
             raise HTTPException(status_code=502, detail=result["error"])
        return result
    finally:
        if client:
            await client.aclose()

@router.get("/bolus/summary", summary="Get post-bolus analysis summary")
async def get_summary_endpoint(
    days: int = 30,
    current_user: Any = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
    db: AsyncSession = Depends(get_db_session)
):
    from app.services.settings_service import get_user_settings_service
    
    # Helper (duplicated locally for now or we could move it, but this is simple enough)
    async def _load_settings_summary() -> UserSettings:
        data = await get_user_settings_service(current_user.username, db)
        s_obj = None
        if data and data.get("settings"):
            s_obj = UserSettings.migrate(data["settings"])
            dt = data.get("updated_at")
            if dt:
                 s_obj.updated_at = dt
        if not s_obj:
            s_obj = store.load_settings()
        return s_obj

    user_id = current_user.username
    settings = await _load_settings_summary()
    return await get_summary_service(user_id=user_id, days=days, db=db, settings=settings)


@router.get("/shadow/logs", summary="Get learning history logs")
async def get_shadow_logs(
    limit: int = 50,
    current_user: Any = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
    db: AsyncSession = Depends(get_db_session)
):
    from app.models.learning import ShadowLog, MealEntry, MealOutcome
    from sqlalchemy import select

    def _shadow_log_payload(log: ShadowLog) -> dict:
        return {
            "id": log.id,
            "user_id": log.user_id,
            "created_at": log.created_at,
            "meal_name": log.meal_name,
            "scenario": log.scenario,
            "suggestion": log.suggestion,
            "is_better": log.is_better,
            "improvement_pct": log.improvement_pct,
            "status": log.status,
        }

    def _format_learning_summary(outcome: MealOutcome) -> tuple[str, str, bool]:
        if outcome.score is None:
            summary = outcome.notes or "Resultado sin puntuar"
            return summary, "neutral", False

        summary_parts = [f"Score {outcome.score}/10"]
        if outcome.max_bg is not None:
            summary_parts.append(f"Max {int(outcome.max_bg)}")
        if outcome.min_bg is not None:
            summary_parts.append(f"Min {int(outcome.min_bg)}")
        if outcome.final_bg is not None:
            summary_parts.append(f"Final {int(outcome.final_bg)}")

        status = "neutral"
        if outcome.hypo_occurred or outcome.hyper_occurred:
            status = "failed"
        elif outcome.score >= 8:
            status = "success"

        return " · ".join(summary_parts), status, status == "success"
    
    # 1. Fetch DB Logs
    stmt = (
        select(ShadowLog)
        .where(ShadowLog.user_id == current_user.username)
        .order_by(ShadowLog.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    db_logs = result.scalars().all()

    # 1b. Fetch learning outcomes (MealEntry + MealOutcome) for history
    stmt_learning = (
        select(MealEntry, MealOutcome)
        .join(MealOutcome, MealOutcome.meal_entry_id == MealEntry.id)
        .where(MealEntry.user_id == current_user.username)
        .order_by(MealOutcome.evaluated_at.desc())
        .limit(limit)
    )
    learning_rows = (await db.execute(stmt_learning)).all()
    learning_logs = []
    for entry, outcome in learning_rows:
        created_at = outcome.evaluated_at or entry.created_at
        meal_name = "Comida"
        if entry.items and isinstance(entry.items, list):
            first_item = next((str(item).strip() for item in entry.items if str(item).strip()), None)
            if first_item:
                meal_name = first_item

        summary, status, is_better = _format_learning_summary(outcome)

        learning_logs.append({
            "id": outcome.id,
            "user_id": entry.user_id,
            "created_at": created_at,
            "meal_name": meal_name,
            "scenario": "Evaluación de aprendizaje",
            "suggestion": summary,
            "is_better": is_better,
            "improvement_pct": None,
            "status": status,
        })
    
    # 2. Fetch "Learning Records" from JSON Store (The new Feedback system)
    # This bridges the gap so the user sees their feedback actions here.
    events = store.load_events()
    learning_events = [e for e in events if e.get("type") in ["learning_record", "post_meal_feedback"]]
    
    memory_logs = []
    seen_ids = {l.id for l in db_logs}
    
    for e in learning_events:
        # Create a transient ShadowLog for display
        # "post_meal_feedback" with "outcome" is a completed learning event
        if e.get("outcome"):
            # Avoid dupes if we sync them later
            eid = e.get("treatment_id") or e.get("created_at")
            if eid in seen_ids: continue
            
            outcome_map = {
                "ok": "✅ Acierto (Ratio OK)",
                "low": "📉 Hipo (Ratio Alto)",
                "high": "📈 Hiper (Ratio Bajo)"
            }
            
            sim_log = ShadowLog(
                id=eid,
                user_id=current_user.username,
                created_at=datetime.fromisoformat(e.get("created_at") or datetime.utcnow().isoformat()),
                meal_name="Comida (Feedback)",
                scenario="Feedback Usuario",
                suggestion=f"El usuario reportó: {e.get('outcome')}",
                is_better=e.get("outcome") == "ok",
                improvement_pct=0.0,
                status="success"
            )
            memory_logs.append(sim_log)

    # Combine and Sort
    all_logs = [_shadow_log_payload(log) for log in db_logs] + learning_logs + [
        _shadow_log_payload(log) for log in memory_logs
    ]
    all_logs.sort(key=lambda x: x["created_at"], reverse=True)

    return all_logs[:limit]
