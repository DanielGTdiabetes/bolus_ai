import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from app.core.settings import get_settings
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient
from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.services import settings_service as svc_settings
from app.services import nightscout_secrets_service as svc_ns_secrets
from app.models.settings import UserSettings
from app.core.db import get_engine, AsyncSession
from pathlib import Path

logger = logging.getLogger(__name__)

async def get_bot_user_settings_safe() -> UserSettings:
    """
    Independent fetcher for user settings to avoid circular imports.
    Follows same logic as service.py: App Config -> DB (Admin/Fallback) -> FileStore
    """
    settings = get_settings()
    
    # Try DB
    engine = get_engine()
    if engine:
        async with AsyncSession(engine) as session:
            # 1. Try 'admin'
            res = await svc_settings.get_user_settings_service("admin", session)
            db_settings = None
            
            if res and res.get("settings"):
                db_settings = res["settings"]
                # Overlay Nightscout Secrets
                try:
                    ns_secret = await svc_ns_secrets.get_ns_config(session, "admin")
                    if ns_secret:
                        if "nightscout" not in db_settings: db_settings["nightscout"] = {}
                        db_settings["nightscout"]["url"] = ns_secret.url
                        db_settings["nightscout"]["token"] = ns_secret.api_secret
                except Exception as e:
                    logger.warning(f"CtxBuilder: failed to fetch NS secrets: {e}")

            # 2. Fallback: Any user with URL
            if not db_settings:
                from sqlalchemy import text
                stmt = text("SELECT user_id, settings FROM user_settings LIMIT 20")
                rows = (await session.execute(stmt)).fetchall()
                for r in rows:
                    s = r.settings
                    if s.get("nightscout", {}).get("url"):
                        db_settings = s
                        break
            
            if db_settings:
                try:
                    return UserSettings.migrate(db_settings)
                except Exception as e:
                    logger.error(f"CtxBuilder: Validation failed: {e}")

    # Fallback to JSON Store
    store = DataStore(Path(settings.data.data_dir))
    return store.load_settings()

async def build_context(username: str, chat_id: int) -> Dict[str, Any]:
    """
    Aggregates realtime context for the AI.
    Never fails completely; returns quality='degraded' if errors occur.
    """
    t0 = time.time()
    ctx = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
        user_settings = await get_bot_user_settings_safe()
        
        # 1. Settings Snapshot
        ctx["settings"] = {
            "target_bg": user_settings.targets.mid,
            "cr": user_settings.cr.dict(),
            "isf": user_settings.cf.dict(), # correction factors
            "units": user_settings.nightscout.units
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
                ctx["bg_age_min"] = int((datetime.now(timezone.utc) - sgv.date).total_seconds() / 60)
            except Exception as e:
                ctx["errors"].append(f"NS_BG_ERROR: {e}")
                ctx["quality"] = "degraded"

            # 4. IOB/COB
            try:
                # We need data store for local history fallback
                settings = get_settings()
                store = DataStore(Path(settings.data.data_dir))
                now_utc = datetime.now(timezone.utc)
                
                iob_u, _, _, _ = await compute_iob_from_sources(now_utc, user_settings, ns_client, store)
                cob_g = await compute_cob_from_sources(now_utc, ns_client, store)
                
                ctx["iob"] = round(iob_u, 2)
                ctx["cob"] = col_g = round(cob_g, 1) # typo fix
                ctx["cob"] = round(cob_g, 1)
            except Exception as e:
                ctx["errors"].append(f"IOB_COB_ERROR: {e}")
                # Don't degrade quality just for IOB if BG is ok, but AI needs to know
        
            # 5. Recent Treatments (Last 4h)
            try:
                limit_dt = datetime.now(timezone.utc) - timedelta(hours=4)
                treatments = await ns_client.get_treatments(limit_dt, datetime.now(timezone.utc))
                
                # Simplify for AI
                summaries = []
                for t in treatments[:5]: # Top 5 recent
                    desc = f"{t.eventType}"
                    if t.insulin: desc += f" {t.insulin}U"
                    if t.carbs: desc += f" {t.carbs}g"
                    minutes_ago = int((datetime.now(timezone.utc) - t.created_at).total_seconds() / 60)
                    desc += f" ({minutes_ago}m ago)"
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
