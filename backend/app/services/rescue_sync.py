
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, text

from app.core.db import SessionLocal
from app.core.settings import get_settings
from app.models.treatment import Treatment
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config

logger = logging.getLogger(__name__)


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

            count_new = 0
            
            for t_ns in treatments:
                # 2. Check existence (by ID or approximate match?)
                # Nightscout IDs are usually Mongo ObjectIDs.
                # If created in Render/BolusAI, they might be UUIDs.
                
                # Try finding by ID first
                stmt = select(Treatment).where(Treatment.id == t_ns.id)
                res = await session.execute(stmt)
                existing = res.scalars().first()
                
                if existing:
                    # Optional: Update if modified? 
                    # For safety in rescue, we assume NS is truth for recent data.
                    # But if we blindly overwrite, we might lose local notes?
                    # Let's skip if exists for now, unless we want to be very aggressive.
                    continue
                
                # Check for "fuzzy" duplicate (same time, same insulin/carbs) to avoid
                # re-importing something that has a different ID but same data.
                # Window: +/- 1 minute
                delta_window = timedelta(minutes=1)
                t_msg_time = t_ns.created_at.replace(tzinfo=None)
                
                stmt_fuzzy = select(Treatment).where(
                    Treatment.created_at >= t_msg_time - delta_window,
                    Treatment.created_at <= t_msg_time + delta_window,
                    Treatment.insulin == t_ns.insulin,
                    Treatment.carbs == t_ns.carbs
                )
                res_fuzzy = await session.execute(stmt_fuzzy)
                fuzzy = res_fuzzy.scalars().first()
                
                if fuzzy:
                    continue

                # 3. Insert New
                new_t = Treatment(
                    id=t_ns.id, # Keep NS ID/UUID
                    user_id="admin", # Default owner
                    event_type=t_ns.event_type or "Bolus",
                    created_at=t_msg_time,
                    insulin=t_ns.insulin,
                    carbs=t_ns.carbs,
                    fat=t_ns.fat,
                    protein=t_ns.protein,
                    fiber=t_ns.fiber, # If supported by schema
                    notes=f"{t_ns.notes or ''} [Rescue]",
                    entered_by=t_ns.entered_by or "NightscoutRescue",
                    is_uploaded=True # It came from NS, so it is uploaded
                )
                session.add(new_t)
                count_new += 1
            
            await session.commit()
            logger.info(f"🚑 Rescue Sync Completed: {count_new} new treatments imported.")

        except Exception as e:
            logger.error(f"🚑 Rescue Sync Failed: {e}")
        finally:
            await client.aclose()
