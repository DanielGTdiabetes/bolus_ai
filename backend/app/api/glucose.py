from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.security import CurrentUser, get_current_user
from app.models.glucose_reading import GlucoseReadingDB
from app.services.glucose_ingest_service import GlucoseIngestData, as_utc, ingest_glucose_reading
from app.services.glucose_source_service import (
    SOURCE_PRIORITY,
    TREND_ARROWS,
    load_glucose_user_settings,
    resolve_current_glucose,
)
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config


router = APIRouter()


class CurrentGlucoseResponse(BaseModel):
    ok: bool
    configured: bool = True
    bg_mgdl: Optional[float] = None
    trend: Optional[str] = None
    trendArrow: Optional[str] = None
    age_minutes: Optional[float] = None
    date: Optional[int] = None
    stale: bool = False
    is_stale: bool = False
    source: str = "none"
    status: str = "unavailable"
    usable_for_dosing: bool = False
    historical: bool = False
    timestamp_uncertain: bool = False
    is_compression: bool = False
    compression_reason: Optional[str] = None
    configured_mode: str = "nightscout"
    fallback_used: bool = False
    conflict_sources: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class GlucoseHistoryItem(BaseModel):
    sgv: int
    date: int
    direction: Optional[str] = None
    trendArrow: Optional[str] = None
    source: str
    historical: bool = False


class GlucoseSourceState(BaseModel):
    source: str
    enabled: bool
    available: bool
    glucose_mgdl: Optional[int] = None
    measured_at: Optional[str] = None
    age_minutes: Optional[float] = None
    status: str
    pending_sync: int = 0


class GlucoseSourcesResponse(BaseModel):
    configured_mode: str
    fallback_enabled: bool
    active_source: str
    active_status: str
    pending_sync: int
    sources: list[GlucoseSourceState]


@router.get("/current", response_model=CurrentGlucoseResponse)
async def get_current_glucose(
    refresh: bool = Query(True),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    resolved = await resolve_current_glucose(
        session, user.username, refresh_remote=refresh
    )
    # Existing clients use the stale flags as their generic "do not trust this
    # for a current action" signal, including conflicts and unavailable data.
    stale = resolved.status != "ok"
    return CurrentGlucoseResponse(
        ok=resolved.bg_mgdl is not None,
        configured=resolved.configured_mode != "none",
        bg_mgdl=resolved.bg_mgdl,
        trend=resolved.trend,
        trendArrow=resolved.trend_arrow,
        age_minutes=resolved.age_minutes,
        date=int(resolved.measured_at.timestamp() * 1000) if resolved.measured_at else None,
        stale=stale,
        is_stale=stale,
        source=resolved.source,
        status=resolved.status,
        usable_for_dosing=resolved.usable_for_dosing,
        historical=resolved.historical,
        timestamp_uncertain=resolved.timestamp_uncertain,
        is_compression=resolved.is_compression,
        compression_reason=resolved.compression_reason,
        configured_mode=resolved.configured_mode,
        fallback_used=resolved.fallback_used,
        conflict_sources=resolved.conflict_sources,
        errors=resolved.errors,
    )


async def _backfill_nightscout_history(
    session: AsyncSession,
    user_id: str,
    *,
    start: datetime,
    end: datetime,
    count: int,
) -> None:
    ns = await get_ns_config(session, user_id)
    if not ns or not ns.enabled or not ns.url:
        return
    client = NightscoutClient(ns.url, ns.api_secret, timeout_seconds=10)
    try:
        entries = await client.get_sgv_range(start, end, count=count)
        for entry in entries:
            await ingest_glucose_reading(
                session,
                user_id,
                GlucoseIngestData(
                    glucose_mgdl=int(entry.sgv),
                    measured_at=datetime.fromtimestamp(entry.date / 1000, tz=timezone.utc),
                    source="nightscout",
                    trend_arrow=entry.direction,
                    # Old points are marked historical by age validation. The
                    # newest point can still be recognized as a live reading.
                    historical=False,
                ),
                sync_to_nightscout=False,
            )
        await session.commit()
    finally:
        await client.aclose()


@router.get("/history", response_model=list[GlucoseHistoryItem])
async def get_glucose_history(
    count: int = Query(288, ge=1, le=5000),
    hours: Optional[int] = Query(None, ge=1, le=168),
    refresh: bool = Query(True),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    end = datetime.now(timezone.utc)
    effective_hours = hours or max(1, min(168, int((count * 5 + 59) / 60)))
    start = end - timedelta(hours=effective_hours)
    if refresh:
        try:
            await _backfill_nightscout_history(
                session, user.username, start=start, end=end, count=count
            )
        except Exception:
            # Local direct/watch history remains available when Nightscout fails.
            pass

    rows = list(
        (
            await session.execute(
                select(GlucoseReadingDB)
                .where(
                    GlucoseReadingDB.user_id == user.username,
                    GlucoseReadingDB.validation_status == "accepted",
                    GlucoseReadingDB.measured_at >= start,
                )
                .order_by(GlucoseReadingDB.measured_at.desc())
                .limit(count * 4)
            )
        ).scalars().all()
    )

    # The same sensor sample can arrive through Android, watch and Nightscout.
    # Keep one canonical point for graphing, preferring the most direct source.
    canonical: dict[tuple[int, int], GlucoseReadingDB] = {}
    for row in rows:
        key = (int(as_utc(row.measured_at).timestamp()), row.glucose_mgdl)
        previous = canonical.get(key)
        if previous is None or SOURCE_PRIORITY.get(row.source, 0) > SOURCE_PRIORITY.get(previous.source, 0):
            canonical[key] = row

    selected = sorted(canonical.values(), key=lambda row: as_utc(row.measured_at), reverse=True)[:count]
    return [
        GlucoseHistoryItem(
            sgv=row.glucose_mgdl,
            date=int(as_utc(row.measured_at).timestamp() * 1000),
            direction=row.trend_arrow,
            trendArrow=TREND_ARROWS.get(row.trend_arrow or "NONE", row.trend_arrow),
            source=row.source,
            historical=row.historical,
        )
        for row in selected
    ]


@router.get("/sources/status", response_model=GlucoseSourcesResponse)
async def get_glucose_sources_status(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    settings = await load_glucose_user_settings(session, user.username)
    resolved = await resolve_current_glucose(
        session, user.username, user_settings=settings, refresh_remote=False
    )
    pending_sync = int(
        (
            await session.execute(
                select(func.count())
                .select_from(GlucoseReadingDB)
                .where(
                    GlucoseReadingDB.user_id == user.username,
                    GlucoseReadingDB.sync_status.in_(("pending", "failed")),
                )
            )
        ).scalar_one()
    )

    states = []
    source_enabled = {
        "dexcom_android": settings.glucose_sources.android_direct_enabled,
        "g7_direct_watch": settings.glucose_sources.watch_direct_enabled,
        "nightscout": settings.glucose_sources.nightscout_enabled,
        "dexcom_share": settings.glucose_sources.dexcom_share_enabled,
    }
    for source in ("dexcom_android", "g7_direct_watch", "nightscout", "dexcom_share"):
        row = (
            await session.execute(
                select(GlucoseReadingDB)
                .where(
                    GlucoseReadingDB.user_id == user.username,
                    GlucoseReadingDB.source == source,
                    GlucoseReadingDB.validation_status == "accepted",
                )
                .order_by(GlucoseReadingDB.measured_at.desc())
                .limit(1)
            )
        ).scalars().first()
        age = None
        status = "unavailable"
        if row:
            age = max(0.0, (datetime.now(timezone.utc) - as_utc(row.measured_at)).total_seconds() / 60)
            status = "ok" if age <= settings.glucose_sources.max_age_minutes else "stale"
        states.append(
            GlucoseSourceState(
                source=source,
                enabled=source_enabled[source],
                available=row is not None,
                glucose_mgdl=row.glucose_mgdl if row else None,
                measured_at=as_utc(row.measured_at).isoformat() if row else None,
                age_minutes=age,
                status=status,
                pending_sync=pending_sync if source in {"dexcom_android", "g7_direct_watch"} else 0,
            )
        )

    return GlucoseSourcesResponse(
        configured_mode=settings.glucose_sources.mode,
        fallback_enabled=settings.glucose_sources.fallback_enabled,
        active_source=resolved.source,
        active_status=resolved.status,
        pending_sync=pending_sync,
        sources=states,
    )
