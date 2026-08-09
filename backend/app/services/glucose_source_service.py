from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.glucose_reading import GlucoseReadingDB
from app.models.settings import UserSettings
from app.services.dexcom_client import DexcomClient
from app.services.glucose_ingest_service import (
    GlucoseIngestData,
    as_utc,
    ingest_glucose_reading,
    latest_local_readings,
)
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config
from app.services.settings_service import get_user_settings_service
from app.services.smart_filter import CompressionDetector, FilterConfig


logger = logging.getLogger(__name__)

SOURCE_PRIORITY = {
    "dexcom_android": 5,
    "g7_direct_watch": 4,
    "nightscout": 3,
    "dexcom_share": 2,
    "manual": 6,
}

TREND_ARROWS = {
    "DoubleUp": "↑↑",
    "SingleUp": "↑",
    "FortyFiveUp": "↗",
    "Flat": "→",
    "FortyFiveDown": "↘",
    "SingleDown": "↓",
    "DoubleDown": "↓↓",
    "NOT COMPUTABLE": "---",
    "RATE OUT OF RANGE": "---",
    "NONE": "---",
}


@dataclass(slots=True)
class ResolvedGlucose:
    bg_mgdl: Optional[float]
    source: str
    status: str
    measured_at: Optional[datetime]
    age_minutes: Optional[float]
    trend: Optional[str] = None
    trend_arrow: Optional[str] = None
    usable_for_dosing: bool = False
    historical: bool = False
    timestamp_uncertain: bool = False
    is_compression: bool = False
    compression_reason: Optional[str] = None
    fallback_used: bool = False
    configured_mode: str = "nightscout"
    errors: list[str] = field(default_factory=list)
    conflict_sources: list[str] = field(default_factory=list)
    reading_uid: Optional[str] = None


async def load_glucose_user_settings(
    session: AsyncSession, user_id: str
) -> UserSettings:
    payload = await get_user_settings_service(user_id, session)
    if payload and payload.get("settings"):
        return UserSettings.migrate(payload["settings"])
    return UserSettings.default()


async def _fetch_nightscout(
    session: AsyncSession,
    user_id: str,
    user_settings: UserSettings,
) -> tuple[Optional[GlucoseReadingDB], bool, Optional[str]]:
    ns_config = await get_ns_config(session, user_id)
    if not ns_config or not ns_config.enabled or not ns_config.url:
        return None, False, None

    client = NightscoutClient(ns_config.url, ns_config.api_secret, timeout_seconds=7)
    is_compression = False
    compression_reason = None
    try:
        now = datetime.now(timezone.utc)
        entries = await client.get_sgv_range(
            now - timedelta(minutes=60), now + timedelta(minutes=10), count=12
        )
        if not entries:
            entries = [await client.get_latest_sgv()]
        entries.sort(key=lambda item: item.date)
        latest = entries[-1]

        if user_settings.nightscout.filter_compression and len(entries) > 1:
            filter_config = FilterConfig(
                enabled=True,
                night_start_hour=user_settings.nightscout.filter_night_start_hour,
                night_end_hour=user_settings.nightscout.filter_night_end_hour,
                treatments_lookback_minutes=user_settings.nightscout.treatments_lookback_minutes,
            )
            lookback_hours = max(1, filter_config.treatments_lookback_minutes // 60 or 1)
            treatments = await client.get_recent_treatments(hours=lookback_hours, limit=10)
            processed = CompressionDetector(config=filter_config).detect(
                [entry.model_dump() for entry in entries],
                [treatment.model_dump() for treatment in treatments],
            )
            if processed:
                item = processed[-1]
                is_compression = bool(item.get("is_compression"))
                compression_reason = item.get("compression_reason")

        result = await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=int(latest.sgv),
                measured_at=datetime.fromtimestamp(latest.date / 1000, tz=timezone.utc),
                source="nightscout",
                trend_arrow=latest.direction,
                historical=False,
            ),
            sync_to_nightscout=False,
        )
        return result.reading, is_compression, compression_reason
    finally:
        await client.aclose()


async def _fetch_dexcom_share(
    session: AsyncSession,
    user_id: str,
    user_settings: UserSettings,
) -> Optional[GlucoseReadingDB]:
    config = user_settings.dexcom
    if not config.enabled or not config.username or not config.password:
        return None
    reading = await DexcomClient(
        username=config.username,
        password=config.password,
        region=config.region or "ous",
    ).get_latest_sgv()
    if not reading:
        return None
    result = await ingest_glucose_reading(
        session,
        user_id,
        GlucoseIngestData(
            glucose_mgdl=int(reading.sgv),
            measured_at=as_utc(reading.date),
            source="dexcom_share",
            trend_arrow=reading.trend,
        ),
        sync_to_nightscout=False,
    )
    return result.reading


def _source_allowed(source: str, settings: UserSettings) -> bool:
    mode = settings.glucose_sources.mode
    if source == "nightscout" and not settings.glucose_sources.nightscout_enabled:
        return False
    if source == "dexcom_share" and not (
        settings.glucose_sources.dexcom_share_enabled and settings.dexcom.enabled
    ):
        return False
    if source == "dexcom_android" and not settings.glucose_sources.android_direct_enabled:
        return False
    if source == "g7_direct_watch" and not settings.glucose_sources.watch_direct_enabled:
        return False
    if source == mode:
        return True
    if mode != "auto" and not settings.glucose_sources.fallback_enabled:
        return False
    if source in {"dexcom_android", "g7_direct_watch", "nightscout", "dexcom_share"}:
        return True
    return source == "manual"


def _choose_candidate(
    rows: list[GlucoseReadingDB], settings: UserSettings
) -> tuple[Optional[GlucoseReadingDB], list[str]]:
    allowed = [
        row
        for row in rows
        if row.validation_status == "accepted" and _source_allowed(row.source, settings)
    ]
    if not allowed:
        return None, []

    allowed.sort(
        key=lambda row: (as_utc(row.measured_at), SOURCE_PRIORITY.get(row.source, 0)),
        reverse=True,
    )
    mode = settings.glucose_sources.mode
    chosen: Optional[GlucoseReadingDB] = None
    if mode == "auto":
        chosen = allowed[0]
    else:
        preferred = [row for row in allowed if row.source == mode]
        preferred_latest = preferred[0] if preferred else None
        preferred_fresh = bool(
            preferred_latest
            and preferred_latest.usable_for_dosing
            and datetime.now(timezone.utc) - as_utc(preferred_latest.measured_at)
            <= timedelta(minutes=settings.glucose_sources.max_age_minutes)
        )
        if preferred_fresh or not settings.glucose_sources.fallback_enabled:
            chosen = preferred_latest
        else:
            fresh_fallbacks = [
                row
                for row in allowed
                if row.source != mode
                and row.usable_for_dosing
                and datetime.now(timezone.utc) - as_utc(row.measured_at)
                <= timedelta(minutes=settings.glucose_sources.max_age_minutes)
            ]
            chosen = fresh_fallbacks[0] if fresh_fallbacks else preferred_latest
            if chosen is None:
                chosen = allowed[0]

    if chosen is None:
        return None, []
    chosen_second = int(as_utc(chosen.measured_at).timestamp())
    conflicts = sorted(
        {
            row.source
            for row in allowed
            if row.id != chosen.id
            if int(as_utc(row.measured_at).timestamp()) == chosen_second
            and row.glucose_mgdl != chosen.glucose_mgdl
        }
        | ({chosen.source} if any(
            int(as_utc(row.measured_at).timestamp()) == chosen_second
            and row.glucose_mgdl != chosen.glucose_mgdl
            for row in allowed
            if row.id != chosen.id
        ) else set())
    )
    return chosen, conflicts


async def resolve_current_glucose(
    session: AsyncSession,
    user_id: str,
    *,
    user_settings: Optional[UserSettings] = None,
    refresh_remote: bool = True,
) -> ResolvedGlucose:
    settings = user_settings or await load_glucose_user_settings(session, user_id)
    mode = settings.glucose_sources.mode
    errors: list[str] = []
    compression = False
    compression_reason = None

    rows = await latest_local_readings(session, user_id, limit=100)

    def has_fresh_candidate(
        candidates: list[GlucoseReadingDB], required_source: Optional[str] = None
    ) -> bool:
        scoped = (
            [row for row in candidates if row.source == required_source]
            if required_source
            else candidates
        )
        candidate, conflicts = _choose_candidate(scoped, settings)
        if not candidate or conflicts:
            return False
        age = datetime.now(timezone.utc) - as_utc(candidate.measured_at)
        return bool(
            candidate.usable_for_dosing
            and age <= timedelta(minutes=settings.glucose_sources.max_age_minutes)
        )

    preferred_is_fresh = has_fresh_candidate(rows, None if mode == "auto" else mode)
    should_try_nightscout = settings.glucose_sources.nightscout_enabled and (
        mode in {"auto", "nightscout"}
        or (settings.glucose_sources.fallback_enabled and not preferred_is_fresh)
    )
    if refresh_remote and should_try_nightscout:
        try:
            _, compression, compression_reason = await _fetch_nightscout(
                session, user_id, settings
            )
        except Exception as exc:
            errors.append(f"nightscout:{type(exc).__name__}")
            logger.warning("Nightscout glucose refresh failed for %s: %s", user_id, type(exc).__name__)
    if refresh_remote and should_try_nightscout:
        rows = await latest_local_readings(session, user_id, limit=100)

    fresh_after_nightscout = has_fresh_candidate(rows)
    should_try_dexcom = settings.glucose_sources.dexcom_share_enabled and (
        mode == "dexcom_share"
        or (settings.glucose_sources.fallback_enabled and not fresh_after_nightscout)
    )
    if refresh_remote and should_try_dexcom:
        try:
            await _fetch_dexcom_share(session, user_id, settings)
        except Exception as exc:
            errors.append(f"dexcom_share:{type(exc).__name__}")
            logger.warning("Dexcom Share refresh failed for %s: %s", user_id, type(exc).__name__)

    await session.commit()
    rows = await latest_local_readings(session, user_id, limit=100)
    chosen, conflicts = _choose_candidate(rows, settings)
    if chosen is None:
        return ResolvedGlucose(
            bg_mgdl=None,
            source="none",
            status="unavailable",
            measured_at=None,
            age_minutes=None,
            configured_mode=mode,
            errors=errors,
        )

    measured_at = as_utc(chosen.measured_at)
    age_minutes = max(
        0.0, (datetime.now(timezone.utc) - measured_at).total_seconds() / 60.0
    )
    stale = age_minutes > settings.glucose_sources.max_age_minutes
    if conflicts:
        status = "conflict"
    elif stale or chosen.historical:
        status = "stale"
    elif chosen.timestamp_uncertain or not chosen.usable_for_dosing:
        status = "unavailable"
    else:
        status = "ok"
    usable = bool(chosen.usable_for_dosing and not stale and not conflicts)
    fallback_used = mode not in {"auto", chosen.source}

    return ResolvedGlucose(
        bg_mgdl=float(chosen.glucose_mgdl),
        source=chosen.source,
        status=status,
        measured_at=measured_at,
        age_minutes=age_minutes,
        trend=chosen.trend_arrow,
        trend_arrow=TREND_ARROWS.get(chosen.trend_arrow or "NONE", chosen.trend_arrow),
        usable_for_dosing=usable,
        historical=bool(chosen.historical),
        timestamp_uncertain=bool(chosen.timestamp_uncertain),
        is_compression=compression if chosen.source == "nightscout" else False,
        compression_reason=compression_reason if chosen.source == "nightscout" else None,
        fallback_used=fallback_used,
        configured_mode=mode,
        errors=errors,
        conflict_sources=conflicts,
        reading_uid=chosen.reading_uid,
    )
