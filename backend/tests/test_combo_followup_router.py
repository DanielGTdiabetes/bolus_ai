from types import SimpleNamespace

import pytest

from app.bot.llm import router


def _allow_event(monkeypatch):
    monkeypatch.setattr(
        router.rules,
        "check_silence",
        lambda _event: SimpleNamespace(
            should_silence=False,
            reason=None,
            remaining_min=0,
            window_min=0,
        ),
    )
    monkeypatch.setattr(router.rules, "mark_event_sent", lambda _event: None)


@pytest.mark.asyncio
async def test_structured_combo_followup_uses_planned_later_amount(monkeypatch):
    _allow_event(monkeypatch)

    reply = await router.handle_event(
        username="tester",
        chat_id=1,
        event_type="combo_followup",
        payload={
            "reason_hint": "eligible_candidate",
            "structured_plan": True,
            "plan_id": "plan-1",
            "treatment_id": "tx-1",
            "planned_later_u": 1.5,
            "upfront_u": 4.0,
            "total_recommended_u": 5.5,
            "bolus_at": "2026-08-10T08:00:00+00:00",
            "bg": 120,
            "trend": "Flat",
            "delta": 0,
            "iob": 1.2,
        },
    )

    assert reply is not None
    assert "1.5 U" in reply.text
    assert "¿Revisamos el plan?" in reply.text
    assert "¿Registramos?" not in reply.text
    callbacks = [button.callback_data for row in reply.buttons for button in row]
    assert "combo_review|plan-1" in callbacks
    assert "combo_yes|tx-1" not in callbacks


@pytest.mark.asyncio
async def test_legacy_combo_followup_never_relabels_first_bolus_as_second(monkeypatch):
    _allow_event(monkeypatch)

    reply = await router.handle_event(
        username="tester",
        chat_id=1,
        event_type="combo_followup",
        payload={
            "treatment_id": "legacy-tx",
            "bolus_units": 6.0,
            "bolus_at": "2026-08-10T08:00:00+00:00",
            "bg": 120,
            "trend": "Flat",
            "delta": 0,
        },
    )

    assert reply is not None
    assert "no existe un plan estructurado" in reply.text
    assert "2ª parte (6" not in reply.text
    callbacks = [button.callback_data for row in reply.buttons for button in row]
    assert "run_cmd|status" in callbacks
    assert all(not callback.startswith("combo_yes|") for callback in callbacks)
