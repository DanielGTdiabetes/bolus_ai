from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.db import get_db_session_context
from app.models.companion import CompanionEpisode
from app.services.companion_service import (
    _sustained_high_guidance,
    _upsert_episode,
    _utcnow,
    act_on_episode,
    list_active_episodes,
    evaluate_companion_state,
    record_meal_episode,
    resolve_episode_by_fingerprint,
)
from app.models.schemas import NightscoutSGV


def test_sustained_high_guidance_waits_when_insulin_is_active():
    message, route, context = _sustained_high_guidance(1.2)

    assert route == "#/forecast"
    assert context["action_label"] == "Ver tendencia"
    assert context["correction_status"] == "wait_active_insulin"
    assert "No añadas ahora otra dosis de corrección" in message
    assert "calculadora" not in message


def test_sustained_high_guidance_opens_correction_only_with_low_iob():
    message, route, context = _sustained_high_guidance(0.2)

    assert route == "#/bolus"
    assert context["action_label"] == "Valorar corrección"
    assert context["correction_status"] == "review_possible"
    assert "calculadora" in message


@pytest.mark.asyncio
async def test_dismissed_episode_does_not_return_until_condition_resets():
    user_id = f"companion-{uuid4()}"
    async with get_db_session_context() as db:
        row = await _upsert_episode(
            user_id, "sustained_high:active", "sustained_high", "high",
            "Glucosa alta mantenida", "Revisa antes de corregir", "#/bolus",
            {"bg": 210}, db,
        )
        await db.commit()
        episode_id = row.id

        await act_on_episode(user_id, episode_id, "dismiss", db)
        assert await list_active_episodes(user_id, db) == []

        # The same still-active condition updates context but must not resurrect.
        row = await _upsert_episode(
            user_id, "sustained_high:active", "sustained_high", "high",
            "Glucosa alta mantenida", "Sigue alta", "#/bolus", {"bg": 220}, db,
        )
        await db.commit()
        assert row.status == "dismissed"

        # Once the condition resolves, a later distinct occurrence can reopen.
        row.status = "resolved"
        row.resolved_at = _utcnow()
        await db.commit()
        row = await _upsert_episode(
            user_id, "sustained_high:active", "sustained_high", "high",
            "Glucosa alta mantenida", "Nueva situación", "#/bolus", {"bg": 205}, db,
        )
        await db.commit()
        assert row.status == "open"
        assert row.last_notified_at is None


@pytest.mark.asyncio
async def test_snooze_is_persistent_and_expires():
    user_id = f"companion-{uuid4()}"
    async with get_db_session_context() as db:
        row = CompanionEpisode(
            user_id=user_id,
            fingerprint="rapid_drop:active",
            kind="rapid_drop",
            severity="high",
            title="Bajada rápida",
            message="Revisa pronto",
            route="#/forecast",
            context={},
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        await act_on_episode(user_id, row.id, "snooze", db, snooze_minutes=30)
        stored = (await db.execute(select(CompanionEpisode).where(CompanionEpisode.id == row.id))).scalar_one()
        assert stored.status == "snoozed"
        assert stored.snoozed_until is not None

        stored.snoozed_until = _utcnow() - timedelta(minutes=1)
        await db.commit()
        active = await list_active_episodes(user_id, db)
        assert active[0].status == "open"


@pytest.mark.asyncio
async def test_sustained_high_creates_one_episode_and_resolves(monkeypatch):
    user_id = f"companion-{uuid4()}"
    now = _utcnow()

    class FakeClient:
        values = [185, 192, 205, 212]

        def __init__(self, *args, **kwargs):
            pass

        async def get_sgv_range(self, *args, **kwargs):
            return [
                NightscoutSGV(
                    sgv=value,
                    direction="Flat",
                    date=now - timedelta(minutes=15 - index * 5),
                )
                for index, value in enumerate(self.values)
            ]

        async def aclose(self):
            pass

    async def fake_ns_config(*args, **kwargs):
        return SimpleNamespace(enabled=True, url="https://example.test", api_secret="secret")

    monkeypatch.setattr("app.services.companion_service.NightscoutClient", FakeClient)
    monkeypatch.setattr("app.services.companion_service.get_ns_config", fake_ns_config)

    async with get_db_session_context() as db:
        first = await evaluate_companion_state(user_id, db)
        second = await evaluate_companion_state(user_id, db)
        highs = [item for item in second["episodes"] if item["kind"] == "sustained_high"]
        assert first["snapshot"]["state"] == "needs_attention"
        assert len(highs) == 1
        assert "micro" not in highs[0]["message"].lower()

        FakeClient.values = [115, 112, 110, 108]
        resolved = await evaluate_companion_state(user_id, db)
        assert not any(item["kind"] == "sustained_high" for item in resolved["episodes"])


@pytest.mark.asyncio
async def test_meal_episode_tracks_confirmation_lifecycle():
    user_id = f"companion-{uuid4()}"
    origin_id = str(uuid4())
    async with get_db_session_context() as db:
        row = await record_meal_episode(
            user_id,
            origin_id,
            "Espera orientativa tras confirmar el bolo: 15 min (tu perfil).",
            {"carbs_g": 45, "wait_minutes": 15},
            db,
        )
        assert row.status == "monitoring"
        assert row.context["wait_minutes"] == 15

        assert await resolve_episode_by_fingerprint(
            user_id, f"meal_detected:{origin_id}", db
        ) is True
        assert await list_active_episodes(user_id, db) == []
