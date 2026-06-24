import asyncio

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


def test_dexcom_bolus_types_include_nightscout_bolus_and_exclude_basal():
    assert "Bolus" in integrations.DEXCOM_BOLUS_EVENT_TYPES
    assert "basal" not in {event_type.lower() for event_type in integrations.DEXCOM_BOLUS_EVENT_TYPES}


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
