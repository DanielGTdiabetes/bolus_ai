import logging
from copy import deepcopy
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import config
from app.core.db import SessionLocal
from app.core.settings import get_settings
from app.models.settings import UserSettings
from app.services import nightscout_secrets_service as svc_ns_secrets
from app.services import settings_service as svc_settings
from app.services.store import DataStore

logger = logging.getLogger(__name__)


def _is_default_like(settings: UserSettings) -> bool:
    """Detect configs that match the factory defaults (likely placeholder/admin)."""
    defaults = UserSettings.default()
    return (
        settings.targets.low == defaults.targets.low
        and settings.targets.mid == defaults.targets.mid
        and settings.targets.high == defaults.targets.high
        and settings.cr.model_dump() == defaults.cr.model_dump()
        and settings.cf.model_dump() == defaults.cf.model_dump()
        and (settings.nightscout.url or "") == (defaults.nightscout.url or "")
    )


async def _load_settings_for_user(user_id: str, session: AsyncSession) -> Optional[UserSettings]:
    """Fetch and hydrate settings for a specific user (DB + NS secrets)."""
    res = await svc_settings.get_user_settings_service(user_id, session)
    
    if res and res.get("settings"):
        payload = deepcopy(res["settings"])
    else:
        # If no DB settings found, check if this user exists in any capacity 
        # (e.g. has NS secrets or is a known fallback)
        payload = UserSettings.default().model_dump()

    # Hydrate with Nightscout Secrets (The true source for URLs)
    try:
        ns_secret = await svc_ns_secrets.get_ns_config(session, user_id)
        if ns_secret:
            payload.setdefault("nightscout", {})
            payload["nightscout"]["url"] = ns_secret.url
            payload["nightscout"]["token"] = ns_secret.api_secret
            payload["nightscout"]["enabled"] = ns_secret.enabled
        elif not res:
            # If no settings AND no secrets, this user is truly unknown to DB
            return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bot resolver: failed to overlay NS secrets for %s: %s", user_id, exc)

    try:
        settings_obj = UserSettings.migrate(payload)
        # Force bot enabled if using default/fallback logic to ensure jobs run
        if not res and not settings_obj.bot.enabled:
             settings_obj.bot.enabled = True
        return settings_obj
    except Exception as exc:  # noqa: BLE001
        logger.error("Bot resolver: invalid settings for %s: %s", user_id, exc)
        return None



from app.bot.context_vars import bot_user_context

async def resolve_bot_user_settings(preferred_username: Optional[str] = None) -> Tuple[UserSettings, str]:
    """
    Resolve which user's settings the bot should use.

    Priority:
    0) Context Variable (Implicit context from Service)
    1) Explicit preferred username (e.g., Telegram username)
    2) BOT_DEFAULT_USERNAME env (defaults to 'admin')
    3) Any non-default settings in DB, preferring freshest updated rows
    4) Default-like settings from DB
    5) File store (data_dir) using the same priority order
    """
    settings = get_settings()
    # Ordered preference list (no duplicates)
    preferred = []
    
    # 0. Context Var (Highest Priority if implicit)
    ctx_user = bot_user_context.get()
    if ctx_user:
        preferred.append(ctx_user)

    if preferred_username and preferred_username not in preferred:
        preferred.append(preferred_username)
    # Only add defaults to preferred if we have an explicit request or if we want to force them.
    # If preferred_username is None, we want to allow "freshest non-default" (Step 2) to win 
    # BEFORE falling back to admin/defaults.
    
    # However, if env var is set, we might want to respect it?
    # Let's add them to a fallback list or only add if preferred_username was provided?
    # Actually, the logic below checks 'if user_id in preferred: continue'.
    # So if we put admin in preferred, Step 2 skips it.
    
    # We WANT Step 2 to run for 'Daniel' (freshest) and return it.
    # So 'admin' should NOT be in preferred list if it's not the requested user.
    
    fallback_users = []
    bot_default = config.get_bot_default_username() or "admin"
    if bot_default not in preferred:
        fallback_users.append(bot_default)
    if "admin" not in preferred and "admin" not in fallback_users:
        fallback_users.append("admin")

    try:
        async with SessionLocal() as session:
            default_like_fallback: Optional[Tuple[UserSettings, str]] = None

            # 0.5) Alias Lookup (Reverse Mapping)
            # Check if any user explicitly allows this Telegram username
            if preferred_username:
                try:
                    # Fetch all settings (optimization: could filter by JSON path)
                    # For personal app scale, iterating is fine and DB-agnostic
                    stmt_alias = text("SELECT user_id, settings FROM user_settings")
                    rows_alias = (await session.execute(stmt_alias)).fetchall()
                    
                    for row in rows_alias:
                        uid = row.user_id if hasattr(row, "user_id") else row[0]
                        s_raw = row.settings if hasattr(row, "settings") else row[1]
                        
                        bot_cfg = s_raw.get("bot", {})
                        if not isinstance(bot_cfg, dict): continue
                        
                        allowed = bot_cfg.get("allowed_usernames", [])
                        if isinstance(allowed, list) and preferred_username in allowed:
                            logger.info("Bot resolver found alias match: '%s' maps to user '%s'", preferred_username, uid)
                            candidate = await _load_settings_for_user(uid, session)
                            if candidate:
                                return candidate, uid
                except Exception as e:
                    logger.warning(f"Alias lookup failed: {e}")

            # 1) Preferred users first
            for user_id in preferred:
                candidate = await _load_settings_for_user(user_id, session)
                if candidate:
                    # STRICT CHECK: Only accept "preferred" user if they have saved settings 
                    # that are NOT just defaults. If they don't exist in DB, _load returns None.
                    # If they exist but are default-like, we treat as "maybe not fully set up".
                    if not _is_default_like(candidate):
                        logger.info("Bot resolver selected preferred user settings for '%s'", user_id)
                        return candidate, user_id
                    
                    # If it IS default-like, we keep it as a fallback, but continue searching 
                    # for a "real" user (like 'admin') who might have data.
                    if not default_like_fallback:
                         default_like_fallback = (candidate, user_id)

            # 2) Any other users ordered by recency
            stmt = text("SELECT user_id FROM user_settings ORDER BY updated_at DESC NULLS LAST LIMIT 50")
            rows = (await session.execute(stmt)).fetchall()
            for row in rows:
                user_id = row.user_id if hasattr(row, "user_id") else row[0]
                if user_id in preferred:
                    continue

                candidate = await _load_settings_for_user(user_id, session)
                if candidate:
                    if not _is_default_like(candidate):
                        logger.info("Bot resolver selected freshest non-default settings for '%s'", user_id)
                        return candidate, user_id
                    if not default_like_fallback:
                        default_like_fallback = (candidate, user_id)

            # 3) Fallback Users (Admin/Default) - Check them inside the session loop if we found nothing yet
            for user_id in fallback_users:
                 candidate = await _load_settings_for_user(user_id, session)
                 if candidate and not _is_default_like(candidate):
                      logger.info("Bot resolver falling back to configured default user '%s'", user_id)
                      return candidate, user_id

            if default_like_fallback:
                user_id = default_like_fallback[1]
                logger.info("Bot resolver falling back to default-like settings for '%s'", user_id)
                return default_like_fallback
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Bot resolver: DB lookup failed ({exc}). Continuing to file store fallback.")

    # 3) File store fallback (legacy/offline)
    store = DataStore(Path(settings.data.data_dir))

    def _load_from_store(user_id: str) -> UserSettings:
        try:
            return store.load_settings(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bot resolver: failed to load file settings for %s: %s", user_id, exc)
            return UserSettings.default()

    # Check preferred files
    for user_id in preferred:
        candidate = _load_from_store(user_id)
        if candidate and not _is_default_like(candidate):
            logger.info("Bot resolver selected file-based settings for '%s'", user_id)
            return candidate, user_id

    # Check discovered files
    try:
        for path in Path(settings.data.data_dir).glob("settings_*.json"):
            user_id = path.stem.replace("settings_", "")
            if user_id in preferred: continue
            
            candidate = _load_from_store(user_id)
            if candidate and not _is_default_like(candidate):
                logger.info("Bot resolver selected discovered file-based settings for '%s'", user_id)
                return candidate, user_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bot resolver: error scanning data dir for settings files: %s", exc)

    # Simplification: Just load store for fallback user
    target_fallback = fallback_users[0]
    logger.info("Bot resolver using last-resort settings for '%s'", target_fallback)
    return _load_from_store(target_fallback), target_fallback
