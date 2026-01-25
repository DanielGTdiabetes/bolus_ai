
import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, text

from app.core.db import SessionLocal
from app.core.settings import get_settings
from app.models.treatment import Treatment
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config

logger = logging.getLogger(__name__)


def _safe_get_ns_field(treatment, *names, default=None):
    for name in names:
        if hasattr(treatment, name):
            value = getattr(treatment, name)
            if value is not None:
                return value
        if isinstance(treatment, dict) and name in treatment:
            value = treatment.get(name)
            if value is not None:
                return value
    return default


async def _get_single_user_id(session) -> Optional[str]:
    result = await session.execute(text("SELECT username FROM users"))
    usernames = [row[0] for row in result.fetchall()]
    if len(usernames) == 1:
        return usernames[0]
    return None


async def run_rescue_sync(hours: int = 6):
    """
    Fetches treatments from Nightscout for the last N hours and upserts them locally.
    Critial for NAS recovery to regain IOB/COB context.
    """
    settings = get_settings()
    if settings.emergency_mode:
        logger.warning("🚑 Rescue Sync skipped: EMERGENCY_MODE enabled.")
        return

    logger.info(f"🚑 Starting Rescue Sync (Last {hours}h from Nightscout)...")
    
    async with SessionLocal() as session:
        user_id = await _get_single_user_id(session)
        if not user_id:
            logger.info("Rescue Sync skipped: no Nightscout configured")
            return

        ns_config = await get_ns_config(session, user_id)
        if not ns_config or not ns_config.url or not ns_config.enabled:
            logger.info("Rescue Sync skipped: no Nightscout configured")
            return

        client = NightscoutClient(ns_config.url, ns_config.api_secret)

        try:
            # 1. Fetch from Nightscout
            treatments = await client.get_recent_treatments(hours=hours)
            if not treatments:
                logger.info("🚑 No recent treatments found in Nightscout.")
                return

            fetched = len(treatments)
            processed = 0
            skipped = 0
            
            for t_ns in treatments:
                try:
                    # 2. Check existence (by ID or approximate match?)
                    # Nightscout IDs are usually Mongo ObjectIDs.
                    # If created in Render/BolusAI, they might be UUIDs.
                    ns_id = _safe_get_ns_field(t_ns, "id", "_id")
                    if not ns_id:
                        skipped += 1
                        continue

                    stmt = select(Treatment).where(Treatment.id == ns_id)
                    res = await session.execute(stmt)
                    existing = res.scalars().first()
                    
                    if existing:
                        skipped += 1
                        continue
                    
                    # Check for "fuzzy" duplicate (same time, same insulin/carbs) to avoid
                    # re-importing something that has a different ID but same data.
                    # Window: +/- 1 minute
                    delta_window = timedelta(minutes=1)
                    created_at = _safe_get_ns_field(t_ns, "created_at", "timestamp")
                    if not created_at:
                        skipped += 1
                        continue
                    if isinstance(created_at, datetime):
                        t_msg_time = created_at.replace(tzinfo=None)
                    else:
                        skipped += 1
                        continue
                    insulin = _safe_get_ns_field(t_ns, "insulin", default=0.0)
                    carbs = _safe_get_ns_field(t_ns, "carbs", default=0.0)
                    
                    stmt_fuzzy = select(Treatment).where(
                        Treatment.created_at >= t_msg_time - delta_window,
                        Treatment.created_at <= t_msg_time + delta_window,
                        Treatment.insulin == insulin,
                        Treatment.carbs == carbs,
                    )
                    res_fuzzy = await session.execute(stmt_fuzzy)
                    fuzzy = res_fuzzy.scalars().first()
                    
                    if fuzzy:
                        skipped += 1
                        continue

                    event_type = _safe_get_ns_field(t_ns, "event_type", "eventType", default="Bolus")
                    notes = _safe_get_ns_field(t_ns, "notes", default="")
                    entered_by = _safe_get_ns_field(t_ns, "entered_by", "enteredBy", default="NightscoutRescue")

                    # 3. Insert New
                    new_t = Treatment(
                        id=ns_id, # Keep NS ID/UUID
                        user_id="admin", # Default owner
                        event_type=event_type or "Bolus",
                        created_at=t_msg_time,
                        insulin=insulin,
                        carbs=carbs,
                        fat=_safe_get_ns_field(t_ns, "fat", default=0.0),
                        protein=_safe_get_ns_field(t_ns, "protein", default=0.0),
                        fiber=_safe_get_ns_field(t_ns, "fiber", default=0.0), # If supported by schema
                        notes=f"{notes or ''} [Rescue]",
                        entered_by=entered_by or "NightscoutRescue",
                        is_uploaded=True # It came from NS, so it is uploaded
                    )
                    session.add(new_t)
                    processed += 1
                except Exception as item_exc:
                    skipped += 1
                    t_id = _safe_get_ns_field(t_ns, "id", "_id", default="unknown")
                    tb_short = traceback.format_exc(limit=2)
                    logger.error(
                        "🚑 Rescue Sync item failed: treatment_id=%s error=%s traceback=%s",
                        t_id,
                        item_exc,
                        tb_short,
                    )
            
            await session.commit()
            logger.info(
                "Rescue Sync completed: fetched %s, processed %s, skipped %s",
                fetched,
                processed,
                skipped,
            )

        except Exception as e:
            logger.error(f"🚑 Rescue Sync Failed: {e}")
        finally:
            await client.aclose()
