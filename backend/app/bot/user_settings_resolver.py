import logging
from copy import deepcopy
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import text

from app.core import config
from app.core.db import AsyncSession, get_engine
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
    if not res or not res.get("settings"):
        return None

    payload = deepcopy(res["settings"])
    try:
        ns_secret = await svc_ns_secrets.get_ns_config(session, user_id)
        if ns_secret:
            payload.setdefault("nightscout", {})
            payload["nightscout"]["url"] = ns_secret.url
            payload["nightscout"]["token"] = ns_secret.api_secret
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bot resolver: failed to overlay NS secrets for %s: %s", user_id, exc)

    try:
        return UserSettings.migrate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.error("Bot resolver: invalid settings for %s: %s", user_id, exc)
        return None


async def resolve_bot_user_settings(preferred_username: Optional[str] = None) -> Tuple[UserSettings, str]:
    """
    Resolve which user's settings the bot should use.

    Priority:
    1) Explicit preferred username (e.g., Telegram username)
    2) BOT_DEFAULT_USERNAME env (defaults to 'admin')
    3) Any non-default settings in DB, preferring freshest updated rows
    4) Default-like settings from DB
    5) File store (data_dir) using the same priority order
    """
    settings = get_settings()
    engine = get_engine()

    # Ordered preference list (no duplicates)
    preferred = []
    if preferred_username:
        preferred.append(preferred_username)
    bot_default = config.get_bot_default_username() or "admin"
    if bot_default not in preferred:
        preferred.append(bot_default)
    if "admin" not in preferred:
        preferred.append("admin")

    if engine:
        async with AsyncSession(engine) as session:
            default_like_fallback: Optional[Tuple[UserSettings, str]] = None

            # 1) Preferred users first
            for user_id in preferred:
                candidate = await _load_settings_for_user(user_id, session)
                if candidate:
                    if not _is_default_like(candidate):
                        logger.info("Bot resolver selected preferred user settings for '%s'", user_id)
                        return candidate, user_id
                    default_like_fallback = default_like_fallback or (candidate, user_id)

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

            if default_like_fallback:
                user_id = default_like_fallback[1]
                logger.info("Bot resolver falling back to default-like settings for '%s'", user_id)
                return default_like_fallback

    # 3) File store fallback (legacy/offline)
    store = DataStore(Path(settings.data.data_dir))

    def _load_from_store(user_id: str) -> UserSettings:
        try:
            return store.load_settings(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bot resolver: failed to load file settings for %s: %s", user_id, exc)
            return UserSettings.default()

    for user_id in preferred:
        candidate = _load_from_store(user_id)
        if candidate and not _is_default_like(candidate):
            logger.info("Bot resolver selected file-based settings for '%s'", user_id)
            return candidate, user_id

    # Try other settings_<username>.json files if present
    try:
        for path in Path(settings.data.data_dir).glob("settings_*.json"):
            user_id = path.stem.replace("settings_", "")
            candidate = _load_from_store(user_id)
            if candidate and not _is_default_like(candidate):
                logger.info("Bot resolver selected discovered file-based settings for '%s'", user_id)
                return candidate, user_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bot resolver: error scanning data dir for settings files: %s", exc)

    # Last resort: return default-like (may still be customized if store has data)
    fallback_user = preferred[0] if preferred else "admin"
    logger.info("Bot resolver using last-resort settings for '%s'", fallback_user)
    return _load_from_store(fallback_user), fallback_user
