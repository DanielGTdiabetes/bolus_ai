import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot_leader_lock import BotLeaderLock

BOT_LEADER_KEY = "telegram_bot"


def build_instance_id() -> str:
    explicit = os.environ.get("BOT_INSTANCE_ID")
    if explicit:
        return explicit
    render_id = os.environ.get("RENDER_INSTANCE_ID")
    if render_id:
        return f"render-{render_id}"
    return f"{socket.gethostname()}-{os.getpid()}"


async def try_acquire_bot_leader(
    session: AsyncSession,
    instance_id: str,
    ttl_seconds: int,
    now: Optional[datetime] = None,
) -> Tuple[bool, dict[str, Any]]:
    now_ts = now or datetime.now(timezone.utc)
    if now_ts.tzinfo is not None:
        now_ts = now_ts.astimezone(timezone.utc).replace(tzinfo=None)
    expires_at = now_ts + timedelta(seconds=ttl_seconds)

    result = await session.execute(
        select(BotLeaderLock).where(BotLeaderLock.key == BOT_LEADER_KEY)
    )
    existing = result.scalars().first()

    if existing is None:
        lock = BotLeaderLock(
            key=BOT_LEADER_KEY,
            owner_id=instance_id,
            acquired_at=now_ts,
            expires_at=expires_at,
            updated_at=now_ts,
        )
        session.add(lock)
        await session.commit()
        return True, {
            "action": "acquired",
            "owner_id": instance_id,
            "expires_at": expires_at,
        }

    if existing.owner_id == instance_id:
        existing.expires_at = expires_at
        existing.updated_at = now_ts
        await session.commit()
        return True, {
            "action": "renewed",
            "owner_id": instance_id,
            "expires_at": expires_at,
        }

    if existing.expires_at <= now_ts:
        previous_owner = existing.owner_id
        existing.owner_id = instance_id
        existing.acquired_at = now_ts
        existing.expires_at = expires_at
        existing.updated_at = now_ts
        await session.commit()
        return True, {
            "action": "stolen",
            "owner_id": instance_id,
            "previous_owner": previous_owner,
            "expires_at": expires_at,
        }

    return False, {
        "action": "held",
        "owner_id": existing.owner_id,
        "expires_at": existing.expires_at,
    }


async def release_bot_leader(
    session: AsyncSession,
    instance_id: str,
    now: Optional[datetime] = None,
) -> bool:
    now_ts = now or datetime.now(timezone.utc)
    if now_ts.tzinfo is not None:
        now_ts = now_ts.astimezone(timezone.utc).replace(tzinfo=None)
    result = await session.execute(
        select(BotLeaderLock).where(BotLeaderLock.key == BOT_LEADER_KEY)
    )
    existing = result.scalars().first()
    if not existing or existing.owner_id != instance_id:
        return False
    existing.expires_at = now_ts
    existing.updated_at = now_ts
    await session.commit()
    return True
