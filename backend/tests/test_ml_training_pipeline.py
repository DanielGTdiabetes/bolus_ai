from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import text

from app.core.db import get_db_session_context
from app.models.basal import BasalEntry
from app.models.settings import UserSettings
from app.models.treatment import Treatment
from app.models.schemas import NightscoutSGV, Treatment as NSTreatment
from app.services.nightscout_secrets_service import upsert_ns_config
from app.services.settings_service import get_user_settings_service, update_user_settings_service
from app.services.ml_training_pipeline import collect_and_persist_training_snapshot


class DummyNightscoutClient:
    def __init__(self, base_url, api_secret, timeout_seconds=10):
        self.base_url = base_url
        self.api_secret = api_secret

    async def get_latest_sgv(self):
        ts = int((datetime.now(timezone.utc) - timedelta(minutes=4)).timestamp() * 1000)
        return NightscoutSGV(sgv=123, direction="Flat", date=ts)

    async def get_sgv_range(self, start_dt, end_dt, count=20):
        now = datetime.now(timezone.utc)
        return [
            NightscoutSGV(sgv=125, direction="Flat", date=int((now - timedelta(minutes=5)).timestamp() * 1000)),
            NightscoutSGV(sgv=123, direction="Flat", date=int((now - timedelta(minutes=10)).timestamp() * 1000)),
        ]

    async def get_recent_treatments(self, hours=24, limit=200):
        now = datetime.now(timezone.utc) - timedelta(minutes=10)
        return [
            NSTreatment(
                id="ns-1",
                eventType="Meal Bolus",
                created_at=now,
                insulin=1.0,
                carbs=20.0,
                notes="",
            )
        ]

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_ml_training_snapshot_inserts_row(monkeypatch):
    monkeypatch.setattr(
        "app.services.ml_training_pipeline.NightscoutClient",
        DummyNightscoutClient,
    )
    now = datetime.now(timezone.utc) + timedelta(minutes=10)

    async with get_db_session_context() as session:
        settings = UserSettings.default().model_dump()
        current = await get_user_settings_service("admin", session)
        await update_user_settings_service("admin", settings, current["version"], session)

        await upsert_ns_config(session, "admin", "https://example.com/", "secret", enabled=True)

        treatment = Treatment(
            id="db-1",
            user_id="admin",
            event_type="Meal Bolus",
            created_at=(now - timedelta(minutes=20)).replace(tzinfo=None),
            insulin=1.0,
            carbs=20.0,
            fat=0.0,
            protein=0.0,
            fiber=0.0,
            glucose=None,
            duration=0.0,
            notes="",
            entered_by="test",
            is_uploaded=False,
            nightscout_id="ns-1",
        )
        session.add(treatment)

        basal = BasalEntry(
            user_id="admin",
            dose_u=12.0,
            created_at=(now - timedelta(hours=2)),
            effective_hours=24,
            basal_type="glargine",
        )
        session.add(basal)

        await session.commit()

        snapshot = await collect_and_persist_training_snapshot("admin", session, now_utc=now)
        assert snapshot is not None

        res = await session.execute(
            text("SELECT baseline_bg_30m, source_overlap_count FROM ml_training_data_v2 WHERE user_id = :u"),
            {"u": "admin"},
        )
        row = res.fetchone()
        assert row is not None
        assert row.baseline_bg_30m is not None
        assert row.source_overlap_count == 1


class StaleNightscoutClient(DummyNightscoutClient):
    async def get_latest_sgv(self):
        ts = int((datetime.now(timezone.utc) - timedelta(minutes=30)).timestamp() * 1000)
        return NightscoutSGV(sgv=130, direction="Flat", date=ts)

    async def get_recent_treatments(self, hours=24, limit=200):
        now = datetime.now(timezone.utc) - timedelta(minutes=10)
        return [
            NSTreatment(
                id="ns-2",
                eventType="Meal Bolus",
                created_at=now,
                insulin=2.0,
                carbs=10.0,
                notes="",
            )
        ]


@pytest.mark.asyncio
async def test_ml_training_snapshot_flags(monkeypatch):
    monkeypatch.setattr(
        "app.services.ml_training_pipeline.NightscoutClient",
        StaleNightscoutClient,
    )
    now = datetime.now(timezone.utc) + timedelta(minutes=10)

    async with get_db_session_context() as session:
        settings = UserSettings.default().model_dump()
        current = await get_user_settings_service("admin", session)
        await update_user_settings_service("admin", settings, current["version"], session)

        await upsert_ns_config(session, "admin", "https://example.com/", "secret", enabled=True)

        treatment = Treatment(
            id="db-2",
            user_id="admin",
            event_type="Meal Bolus",
            created_at=(now - timedelta(minutes=10)).replace(tzinfo=None),
            insulin=1.0,
            carbs=25.0,
            fat=0.0,
            protein=0.0,
            fiber=0.0,
            glucose=None,
            duration=0.0,
            notes="",
            entered_by="test",
            is_uploaded=False,
            nightscout_id="different-id",
        )
        session.add(treatment)
        await session.commit()

        await session.execute(text("DELETE FROM ml_training_data_v2 WHERE user_id = :u"), {"u": "admin"})
        await session.commit()

        snapshot = await collect_and_persist_training_snapshot("admin", session, now_utc=now)
        assert snapshot is not None
        assert snapshot["bg_age_min"] is not None
        assert snapshot["flag_bg_stale"] is True

        res = await session.execute(
            text(
                """
                SELECT flag_bg_stale, flag_source_conflict
                FROM ml_training_data_v2
                WHERE user_id = :u AND feature_time = :t
                """
            ),
            {"u": "admin", "t": snapshot["feature_time"]},
        )
        row = res.fetchone()
        assert row is not None
        assert bool(row.flag_bg_stale) is True
        assert bool(row.flag_source_conflict) is True
