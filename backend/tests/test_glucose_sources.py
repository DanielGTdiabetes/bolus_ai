from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core.db import SessionLocal
from app.models.settings import UserSettings
from app.services.glucose_ingest_service import GlucoseIngestData, ingest_glucose_reading
from app.services.glucose_source_service import resolve_current_glucose
from app.services.glucose_sync_service import sync_glucose_reading


def _user() -> str:
    return f"glucose-test-{uuid4()}"


@pytest.mark.asyncio
async def test_direct_glucose_is_persisted_and_idempotent():
    user_id = _user()
    measured_at = datetime.now(timezone.utc)
    payload = GlucoseIngestData(
        glucose_mgdl=123,
        measured_at=measured_at,
        source="g7_direct_watch",
        reading_uid="watch-session-1-sequence-42",
        sensor_session_id="watch-session-1",
        sequence=42,
        sensor_state="OK",
    )

    async with SessionLocal() as session:
        first = await ingest_glucose_reading(session, user_id, payload)
        await session.commit()
        second = await ingest_glucose_reading(session, user_id, payload)

    assert first.status == "accepted"
    assert first.reading.sync_status == "not_required"
    assert first.reading.usable_for_dosing is False
    assert first.reading.decision_eligible is False
    assert second.status == "duplicate"
    assert second.duplicate is True
    assert second.reading.id == first.reading.id


@pytest.mark.asyncio
async def test_display_only_reading_is_audited_but_not_usable():
    async with SessionLocal() as session:
        result = await ingest_glucose_reading(
            session,
            _user(),
            GlucoseIngestData(
                glucose_mgdl=118,
                measured_at=datetime.now(timezone.utc),
                source="g7_direct_watch",
                display_only=True,
                sensor_state="OK",
            ),
        )
        await session.commit()

    assert result.status == "rejected"
    assert result.reading.validation_reason == "display_only"
    assert result.reading.usable_for_dosing is False
    assert result.reading.sync_status == "not_required"


@pytest.mark.asyncio
async def test_auto_mode_keeps_watch_as_continuity_only():
    user_id = _user()
    settings = UserSettings.default()
    settings.glucose_sources.mode = "auto"
    settings.glucose_sources.watch_direct_enabled = True
    settings.glucose_sources.android_direct_enabled = True
    settings.nightscout.enabled = False
    settings.nightscout.url = ""
    settings.dexcom.enabled = False

    async with SessionLocal() as session:
        await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=131,
                measured_at=datetime.now(timezone.utc),
                source="g7_direct_watch",
                sensor_state="OK",
            ),
        )
        await session.commit()
        resolved = await resolve_current_glucose(
            session,
            user_id,
            user_settings=settings,
            refresh_remote=False,
        )

    assert resolved.status == "unavailable"
    assert resolved.source == "g7_direct_watch"
    assert resolved.bg_mgdl == 131
    assert resolved.usable_for_dosing is False


@pytest.mark.asyncio
async def test_same_timestamp_with_different_values_is_conflict():
    user_id = _user()
    measured_at = datetime.now(timezone.utc).replace(microsecond=0)
    settings = UserSettings.default()
    settings.glucose_sources.mode = "auto"
    settings.glucose_sources.watch_direct_enabled = True
    settings.glucose_sources.android_direct_enabled = True
    settings.nightscout.enabled = False
    settings.nightscout.url = ""
    settings.dexcom.enabled = False

    async with SessionLocal() as session:
        await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=120,
                measured_at=measured_at,
                source="dexcom_android",
                reading_uid="android-conflict",
            ),
        )
        await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=130,
                measured_at=measured_at,
                source="g7_direct_watch",
                reading_uid="watch-conflict",
            ),
        )
        await session.commit()
        resolved = await resolve_current_glucose(
            session,
            user_id,
            user_settings=settings,
            refresh_remote=False,
        )

    assert resolved.status == "conflict"
    assert resolved.usable_for_dosing is False
    assert set(resolved.conflict_sources) == {"dexcom_android", "g7_direct_watch"}


@pytest.mark.asyncio
async def test_nightscout_failure_keeps_direct_reading_pending():
    class FailingClient:
        async def upload_sgv(self, **_kwargs):
            raise RuntimeError("unavailable")

    async with SessionLocal() as session:
        result = await ingest_glucose_reading(
            session,
            _user(),
            GlucoseIngestData(
                glucose_mgdl=109,
                measured_at=datetime.now(timezone.utc),
                source="dexcom_android",
            ),
        )
        status = await sync_glucose_reading(session, result.reading, client=FailingClient())
        await session.commit()

    assert status == "failed"
    assert result.reading.sync_status == "failed"
    assert result.reading.sync_attempts == 1
    assert result.reading.sync_error == "RuntimeError"


@pytest.mark.asyncio
async def test_old_watch_backfill_is_never_usable_for_dosing():
    user_id = _user()
    settings = UserSettings.default()
    settings.glucose_sources.mode = "g7_direct_watch"
    settings.glucose_sources.watch_direct_enabled = True

    async with SessionLocal() as session:
        await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=115,
                measured_at=datetime.now(timezone.utc) - timedelta(minutes=30),
                source="g7_direct_watch",
                historical=True,
            ),
        )
        await session.commit()
        resolved = await resolve_current_glucose(
            session,
            user_id,
            user_settings=settings,
            refresh_remote=False,
        )

    assert resolved.status == "stale"
    assert resolved.historical is True
    assert resolved.usable_for_dosing is False


@pytest.mark.asyncio
async def test_live_duplicate_can_upgrade_recent_backfill_metadata():
    user_id = _user()
    uid = f"backfill-upgrade-{uuid4()}"
    measured_at = datetime.now(timezone.utc)

    async with SessionLocal() as session:
        first = await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=122,
                measured_at=measured_at,
                source="g7_direct_watch",
                reading_uid=uid,
                historical=True,
            ),
        )
        await session.commit()
        duplicate = await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=122,
                measured_at=measured_at,
                source="g7_direct_watch",
                reading_uid=uid,
                historical=False,
            ),
        )
        await session.commit()

    assert first.reading.id == duplicate.reading.id
    assert duplicate.duplicate is True
    assert duplicate.reading.historical is False
    assert duplicate.reading.usable_for_dosing is False


@pytest.mark.asyncio
async def test_manually_disconnected_source_is_not_selected():
    user_id = _user()
    settings = UserSettings.default()
    settings.glucose_sources.mode = "auto"
    settings.glucose_sources.fallback_enabled = True
    settings.glucose_sources.android_direct_enabled = False
    settings.glucose_sources.watch_direct_enabled = False
    settings.glucose_sources.nightscout_enabled = True
    settings.glucose_sources.dexcom_share_enabled = False

    async with SessionLocal() as session:
        await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=125,
                measured_at=datetime.now(timezone.utc),
                source="dexcom_android",
                reading_uid=f"disabled-android-{uuid4()}",
            ),
        )
        await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=124,
                measured_at=datetime.now(timezone.utc) - timedelta(seconds=5),
                source="nightscout",
                reading_uid=f"enabled-nightscout-{uuid4()}",
            ),
            sync_to_nightscout=False,
        )
        await session.commit()
        resolved = await resolve_current_glucose(
            session,
            user_id,
            user_settings=settings,
            refresh_remote=False,
        )

    assert resolved.source == "nightscout"
    assert resolved.bg_mgdl == 124
    assert resolved.usable_for_dosing is True


@pytest.mark.asyncio
async def test_selected_nightscout_wins_while_it_is_fresh():
    user_id = _user()
    settings = UserSettings.default()
    settings.glucose_sources.mode = "nightscout"
    settings.glucose_sources.fallback_enabled = True
    settings.glucose_sources.android_direct_enabled = True

    async with SessionLocal() as session:
        await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=119,
                measured_at=datetime.now(timezone.utc) - timedelta(seconds=15),
                source="nightscout",
                reading_uid=f"preferred-nightscout-{uuid4()}",
            ),
            sync_to_nightscout=False,
        )
        await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=120,
                measured_at=datetime.now(timezone.utc),
                source="dexcom_android",
                reading_uid=f"newer-android-{uuid4()}",
            ),
        )
        await session.commit()
        resolved = await resolve_current_glucose(
            session, user_id, user_settings=settings, refresh_remote=False
        )

    assert resolved.source == "nightscout"
    assert resolved.bg_mgdl == 119
    assert resolved.fallback_used is False


@pytest.mark.asyncio
async def test_selected_nightscout_falls_back_when_stale():
    user_id = _user()
    settings = UserSettings.default()
    settings.glucose_sources.mode = "nightscout"
    settings.glucose_sources.fallback_enabled = True
    settings.glucose_sources.android_direct_enabled = True

    async with SessionLocal() as session:
        await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=118,
                measured_at=datetime.now(timezone.utc) - timedelta(minutes=20),
                source="nightscout",
                reading_uid=f"stale-nightscout-{uuid4()}",
            ),
            sync_to_nightscout=False,
        )
        await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=121,
                measured_at=datetime.now(timezone.utc),
                source="dexcom_android",
                reading_uid=f"fallback-android-{uuid4()}",
            ),
        )
        await session.commit()
        resolved = await resolve_current_glucose(
            session, user_id, user_settings=settings, refresh_remote=False
        )

    assert resolved.source == "dexcom_android"
    assert resolved.bg_mgdl == 121
    assert resolved.fallback_used is True
