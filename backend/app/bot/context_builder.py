import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from app.utils.timezone import to_local

from app.core.settings import get_settings
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient
from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.models.settings import UserSettings
from pathlib import Path
from app.bot.user_settings_resolver import resolve_bot_user_settings
from app.services.treatment_retrieval import get_recent_treatments_db, get_visible_treatment_name

logger = logging.getLogger(__name__)

async def get_bot_user_settings_safe() -> UserSettings:
    """
    Independent fetcher for user settings to avoid circular imports.
    Follows same logic as service.py: App Config -> DB (Admin/Fallback) -> FileStore
    """
    resolved_settings, resolved_user = await resolve_bot_user_settings()
    logger.info("CtxBuilder using settings for user_id='%s'", resolved_user)
    return resolved_settings

async def build_context(username: str, chat_id: int) -> Dict[str, Any]:
    """
    Aggregates realtime context for the AI.
    Never fails completely; returns quality='degraded' if errors occur.
    """
    t0 = time.time()
    # Use Local Time for AI Context so it understands "Now" relative to User
    now_utc = datetime.now(timezone.utc)
    now_local = to_local(now_utc)
    
    ctx = {
        "timestamp": now_local.isoformat(),
        "bg": None,
        "trend": None,
        "delta": None,
        "iob": None,
        "cob": None,
        "settings": {},
        "recent_treatments": [],
        "quality": "ok",
        "errors": []
    }

    try:
        user_settings, resolved_user = await resolve_bot_user_settings(username)
        
        # 1. Settings Snapshot
        ctx["settings"] = {
            "target_bg": user_settings.targets.mid,
            "cr": user_settings.cr.dict(),
            "isf": user_settings.cf.dict(), # correction factors
            "units": user_settings.nightscout.units,
            "autonomy_mode": user_settings.learning.auto_apply_safe
        }

        # 2. Nightscout Connection
        ns_client = None
        if user_settings.nightscout.url:
            ns_client = NightscoutClient(
                base_url=user_settings.nightscout.url,
                token=user_settings.nightscout.token,
                timeout_seconds=5
            )

        if ns_client:
            # 3. BG Data
            try:
                sgv = await ns_client.get_latest_sgv()
                ctx["bg"] = sgv.sgv
                ctx["trend"] = sgv.direction
                ctx["delta"] = sgv.delta
                bg_ts = datetime.fromtimestamp(sgv.date / 1000.0, timezone.utc)
                ctx["bg_age_min"] = int((datetime.now(timezone.utc) - bg_ts).total_seconds() / 60)
            except Exception as e:
                ctx["errors"].append(f"NS_BG_ERROR: {e}")
                ctx["quality"] = "degraded"

            # 4. IOB/COB
            try:
                # We need data store for local history fallback
                settings = get_settings()
                store = DataStore(Path(settings.data.data_dir))
                now_utc = datetime.now(timezone.utc)
                
                iob_u, _, iob_info, _ = await compute_iob_from_sources(
                    now_utc,
                    user_settings,
                    ns_client,
                    store,
                    user_id=resolved_user,
                )
                cob_g, cob_info, _ = await compute_cob_from_sources(
                    now_utc,
                    ns_client,
                    store,
                    user_id=resolved_user,
                )
                
                ctx["iob"] = round(iob_u or 0.0, 2) if iob_u is not None else None
                ctx["cob"] = round(cob_g or 0.0, 1) if cob_g is not None else None
                if iob_info.status in ["unavailable", "stale"]:
                    ctx["errors"].append(f"IOB_STATUS:{iob_info.status}")
                if cob_info.status in ["unavailable", "stale"]:
                    ctx["errors"].append(f"COB_STATUS:{cob_info.status}")
            except Exception as e:
                ctx["errors"].append(f"IOB_COB_ERROR: {e}")
                # Don't degrade quality just for IOB if BG is ok, but AI needs to know
        
            # 5. Recent Treatments (Last 4h)
            try:
                treatments = await get_recent_treatments_db(hours=4, username=resolved_user, limit=25)
                if not treatments:
                    treatments = await ns_client.get_recent_treatments(hours=4)
                
                # Simplify for AI
                summaries = []
                for t in treatments[:5]: # Top 5 recent
                    name_hint = get_visible_treatment_name(t)
                    desc = f"{name_hint or t.eventType or 'Comida'}"
                    if t.insulin: desc += f" {t.insulin}U"
                    if t.carbs: desc += f" {t.carbs}g"
                    if t.created_at:
                        minutes_ago = int((datetime.now(timezone.utc) - t.created_at).total_seconds() / 60)
                        desc += f" ({minutes_ago}m ago)"
                    if t.notes:
                        desc += f" [{t.notes}]"
                    summaries.append(desc)
                ctx["recent_treatments"] = summaries
            except Exception as e:
                ctx["errors"].append(f"TREATMENTS_ERROR: {e}")

            await ns_client.aclose()
        else:
            ctx["quality"] = "degraded"
            ctx["errors"].append("NO_NIGHTSCOUT_URL")

    except Exception as e:
        logger.error(f"Context build failed: {e}")
        ctx["quality"] = "degraded"
        ctx["errors"].append(str(e))

    # 6. Basal Context (Proactive)
    try:
        from app.services import basal_context_service
        # Infer timezone offset from settings or default to 0
        offset = 0 # Todo: deduce from user_settings locale if available
        basal_ctx = await basal_context_service.get_basal_status("admin", offset)
        ctx["basal"] = basal_ctx.to_dict()
    except Exception as e:
        ctx["warnings"] = ctx.get("warnings", [])
        ctx["warnings"].append(f"BASAL_CTX_ERROR: {e}")

    ctx["build_ms"] = int((time.time() - t0) * 1000)
    return ctx
