import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_engine
from app.core.settings import get_settings
from app.models.treatment import Treatment
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config
from app.services.store import DataStore

logger = logging.getLogger(__name__)


@dataclass
class TreatmentLogResult:
    ok: bool
    treatment_id: Optional[str]
    insulin: Optional[float] = None
    carbs: Optional[float] = None
    ns_uploaded: bool = False
    ns_error: Optional[str] = None
    saved_db: bool = False
    saved_local: bool = False


async def log_treatment(
    user_id: str,
    *,
    insulin: float = 0.0,
    carbs: float = 0.0,
    notes: Optional[str] = None,
    entered_by: str = "BolusAI",
    event_type: Optional[str] = None,
    duration: float = 0.0,
    fat: float = 0.0,
    protein: float = 0.0,
    fiber: float = 0.0,
    created_at: Optional[datetime] = None,
    store: Optional[DataStore] = None,
    session: Optional[AsyncSession] = None,
    ns_url: Optional[str] = None,
    ns_token: Optional[str] = None,
) -> TreatmentLogResult:
    """
    Centralized logger for treatments used by API and bot flows.
    Persists locally, DB (if available), and Nightscout when configured.
    """

    treatment_id = str(uuid.uuid4())
    created_dt = created_at or datetime.now(timezone.utc)
    created_iso = created_dt.isoformat()
    event_type = event_type or ("Correction Bolus" if carbs == 0 else "Meal Bolus")
    notes = notes or ""

    saved_local = False
    saved_db = False
    ns_uploaded = False
    ns_error: Optional[str] = None
    db_treatment: Optional[Treatment] = None

    # Local backup
    try:
        ds = store or DataStore(Path(get_settings().data.data_dir))
        events = ds.load_events()
        events.append(
            {
                "_id": treatment_id,
                "id": treatment_id,
                "eventType": event_type,
                "created_at": created_iso,
                "insulin": insulin,
                "duration": duration,
                "carbs": carbs,
                "fat": fat,
                "protein": protein,
                "fiber": fiber,
                "notes": notes,
                "enteredBy": entered_by,
                "type": "bolus",
                "ts": created_iso,
                "units": insulin,
            }
        )
        if len(events) > 1000:
            events = events[-1000:]
        ds.save_events(events)
        saved_local = True
    except Exception as exc:
        logger.error("Failed to save treatment locally: %s", exc)

    # Database persistence (if available)
    engine = get_engine()
    created_session = False
    active_session = session
    if not active_session and engine:
        active_session = AsyncSession(engine)
        created_session = True

    if active_session:
        try:
            created_naive = created_dt.astimezone(timezone.utc).replace(tzinfo=None)
            db_treatment = Treatment(
                id=treatment_id,
                user_id=user_id,
                event_type=event_type,
                created_at=created_naive,
                insulin=insulin,
                duration=duration,
                carbs=carbs,
                fat=fat,
                protein=protein,
                fiber=fiber,
                notes=notes,
                entered_by=entered_by,
                is_uploaded=False,
            )
            active_session.add(db_treatment)
            await active_session.commit()
            saved_db = True
        except Exception as db_err:
            logger.error("Failed to save treatment to DB: %s", db_err)
            try:
                await active_session.rollback()
            except Exception:
                logger.debug("Rollback failed after DB error")

        # Fetch NS config if not provided
        if not ns_url:
            try:
                ns_cfg = await get_ns_config(active_session, user_id)
                if ns_cfg and ns_cfg.enabled and ns_cfg.url:
                    ns_url = ns_cfg.url
                    ns_token = ns_cfg.api_secret
            except Exception as exc:
                logger.error("Failed to fetch NS config: %s", exc)

    # Nightscout upload
    if ns_url:
        try:
            client = NightscoutClient(ns_url, ns_token, timeout_seconds=5)
            ns_payload = {
                "eventType": event_type,
                "created_at": created_iso,
                "insulin": insulin,
                "duration": duration,
                "carbs": carbs,
                "fat": fat,
                "protein": protein,
                "fiber": fiber,
                "notes": notes,
                "enteredBy": entered_by,
            }
            await client.upload_treatments([ns_payload])
            await client.aclose()
            ns_uploaded = True
        except Exception as exc:
            logger.error("Failed to upload treatment to Nightscout: %s", exc)
            ns_error = str(exc)

        if ns_uploaded and active_session and db_treatment:
            try:
                db_treatment.is_uploaded = True
                await active_session.commit()
            except Exception as exc:
                logger.error("Failed to flag DB treatment as uploaded: %s", exc)

    if created_session and active_session:
        try:
            await active_session.close()
        except Exception:
            logger.debug("Failed to close DB session after treatment log")

    ok = saved_local or saved_db or ns_uploaded
    return TreatmentLogResult(
        ok=ok,
        treatment_id=treatment_id,
        insulin=insulin,
        carbs=carbs,
        ns_uploaded=ns_uploaded,
        ns_error=ns_error,
        saved_db=saved_db,
        saved_local=saved_local,
    )
