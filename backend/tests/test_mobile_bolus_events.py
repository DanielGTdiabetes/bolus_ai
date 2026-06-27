import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from starlette.requests import Request

from app.api import integrations


class _ScalarResult:
    def first(self):
        return None


class _MissingCursorSession:
    def __init__(self):
        self.execute_count = 0

    async def execute(self, _statement):
        self.execute_count += 1
        return self

    def scalars(self):
        return _ScalarResult()


def test_dexcom_rapid_types_include_nightscout_bolus():
    assert "Bolus" in integrations.DEXCOM_BOLUS_EVENT_TYPES
    assert "basal" not in {event_type.lower() for event_type in integrations.DEXCOM_BOLUS_EVENT_TYPES}


def test_treatment_produces_separate_rapid_and_rounded_carbs_events():
    row = SimpleNamespace(
        id="meal-1",
        event_type="Meal Bolus",
        insulin=3.25,
        carbs=42.5,
        glucose=123.4,
        created_at=datetime(2026, 6, 25, 12, 0, 0),
    )

    events = integrations._dexcom_events_from_treatment(row)

    assert [event.id for event in events] == [
        "treatment:meal-1:rapid",
        "treatment:meal-1:carbs",
    ]
    assert events[0].event_kind == "INSULIN"
    assert events[0].insulin_type == "FAST_ACTING"
    assert events[0].insulin_units == 3.25
    assert events[0].glucose_mgdl == 123
    assert events[1].event_kind == "CARBS"
    assert events[1].carbs_grams == 43
    assert events[1].glucose_mgdl == 123


def test_treatment_export_omits_invalid_glucose_for_dexcom_events():
    row = SimpleNamespace(
        id="meal-1",
        event_type="Meal Bolus",
        insulin=3.0,
        carbs=28.0,
        glucose=0.0,
        created_at=datetime(2026, 6, 25, 12, 0, 0),
    )

    events = integrations._dexcom_events_from_treatment(row)

    assert [event.glucose_mgdl for event in events] == [None, None]


def test_carbs_only_treatment_is_exported_and_half_rounds_up():
    row = SimpleNamespace(
        id="carbs-1",
        event_type="Meal",
        insulin=0.0,
        carbs=10.5,
        notes="Manual carbs",
        entered_by="TelegramBot",
        created_at=datetime(2026, 6, 25, 12, 0, 0),
    )

    events = integrations._dexcom_events_from_treatment(row)

    assert len(events) == 1
    assert events[0].id == "treatment:carbs-1:carbs"
    assert events[0].carbs_grams == 11


def test_pending_imported_meal_does_not_export_carbs_to_dexcom():
    row = SimpleNamespace(
        id="imported-1",
        event_type="Meal Bolus",
        insulin=0.0,
        carbs=42.0,
        notes="Imported from Health: abc #imported",
        entered_by="webhook-integration",
        created_at=datetime(2026, 6, 25, 12, 0, 0),
    )

    assert integrations._dexcom_events_from_treatment(row) == []


def test_carbs_events_with_same_grams_28_minutes_apart_are_deduped():
    first = integrations.MobileBolusEventResponse(
        id="treatment:first:carbs",
        event_kind="CARBS",
        carbs_grams=42,
        timestamp=1_000_000,
    )
    second = integrations.MobileBolusEventResponse(
        id="treatment:second:carbs",
        event_kind="CARBS",
        carbs_grams=42,
        timestamp=1_000_000 + 28 * 60 * 1000,
    )
    insulin = integrations.MobileBolusEventResponse(
        id="treatment:second:rapid",
        event_kind="INSULIN",
        insulin_type="FAST_ACTING",
        insulin_units=3.0,
        timestamp=second.timestamp,
    )

    events = integrations._dedupe_dexcom_carbs_events([first, second, insulin])

    assert [event.id for event in events] == ["treatment:first:carbs", "treatment:second:rapid"]


def test_basal_produces_long_acting_event():
    basal_id = uuid.uuid4()
    row = SimpleNamespace(
        id=basal_id,
        dose_u=16.0,
        created_at=datetime(2026, 6, 25, 22, 30, tzinfo=timezone.utc),
    )

    event = integrations._dexcom_event_from_basal(row)

    assert event is not None
    assert event.id == f"basal:{basal_id}:long"
    assert event.event_kind == "INSULIN"
    assert event.insulin_type == "LONG_ACTING"
    assert event.insulin_units == 16.0


def test_missing_legacy_cursor_without_timestamp_returns_empty(monkeypatch):
    monkeypatch.setenv("NUTRITION_INGEST_SECRET", "test-key")

    async def fake_settings(_session):
        return None, "admin", None

    monkeypatch.setattr(integrations, "_load_mobile_bolus_settings", fake_settings)
    session = _MissingCursorSession()
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    result = asyncio.run(
        integrations.mobile_bolus_events(
            request=request,
            after_id="missing-cursor",
            after_timestamp=None,
            latest_only=False,
            ingest_key_header="test-key",
            session=session,
        )
    )

    assert result == []
    assert session.execute_count == 1
