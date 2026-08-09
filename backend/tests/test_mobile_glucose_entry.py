from datetime import datetime, timezone
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import integrations
from app.core.db import SessionLocal
from app.services.nightscout_client import NightscoutClient


def test_dexcom_trends_are_normalized_for_nightscout():
    assert integrations._nightscout_direction("FortyFiveUp") == "FortyFiveUp"
    assert integrations._nightscout_direction("SINGLE_DOWN") == "SingleDown"
    assert integrations._nightscout_direction("RISING_SLOWLY") == "FortyFiveUp"
    assert integrations._nightscout_direction("RISING_QUICKLY") == "DoubleUp"
    assert integrations._nightscout_direction("FALLING") == "SingleDown"
    assert integrations._nightscout_direction("unexpected") == "NONE"


@pytest.mark.asyncio
async def test_mobile_glucose_entry_uploads_epoch_seconds_as_milliseconds(monkeypatch):
    timestamp = int(datetime.now(timezone.utc).timestamp())
    captured = {}

    class FakeClient:
        async def upload_sgv(self, **kwargs):
            captured.update(kwargs)
            return {"status": "uploaded"}

        async def aclose(self):
            captured["closed"] = True

    async def fake_client(session, settings):
        return FakeClient()

    monkeypatch.setenv("NUTRITION_INGEST_SECRET", "secret")
    monkeypatch.setattr(integrations, "_mobile_nightscout_client", fake_client)
    response = await integrations.mobile_glucose_entry(
        payload=integrations.MobileGlucoseEntryRequest(
            glucose_mgdl=123,
            timestamp=timestamp,
            trend_arrow="Flat",
        ),
        request=SimpleNamespace(query_params={}),
        ingest_key_header="secret",
        session=object(),
        settings=object(),
    )

    assert captured["glucose_mgdl"] == 123
    assert captured["timestamp_ms"] == timestamp * 1000
    assert captured["direction"] == "Flat"
    assert captured["closed"] is True
    assert response.status == "uploaded"


@pytest.mark.asyncio
async def test_nightscout_upload_sgv_posts_expected_entry():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[], request=request)
        return httpx.Response(200, json=[{"_id": "created"}], request=request)

    http_client = httpx.AsyncClient(
        base_url="https://nightscout.example",
        transport=httpx.MockTransport(handler),
    )
    client = NightscoutClient("https://nightscout.example", "secret", client=http_client)

    result = await client.upload_sgv(123, 1_750_000_000_000, "Flat")

    assert result["status"] == "uploaded"
    assert requests[1].url.path == "/api/v1/entries"
    assert json.loads(requests[1].read()) == [{
        "type": "sgv",
        "sgv": 123,
        "date": 1_750_000_000_000,
        "dateString": "2025-06-15T15:06:40Z",
        "direction": "Flat",
        "device": "Dexcom G7 via Bolus AI",
    }]
    await client.aclose()


@pytest.mark.asyncio
async def test_nightscout_upload_sgv_skips_duplicate():
    post_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.method == "POST":
            post_count += 1
        return httpx.Response(
            200,
            json=[{"sgv": 123, "direction": "Flat", "date": 1_750_000_000_000}],
            request=request,
        )

    http_client = httpx.AsyncClient(
        base_url="https://nightscout.example",
        transport=httpx.MockTransport(handler),
    )
    client = NightscoutClient("https://nightscout.example", "secret", client=http_client)

    result = await client.upload_sgv(123, 1_750_000_000_000, "Flat")

    assert result["status"] == "duplicate"
    assert post_count == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_v2_watch_ingest_is_idempotent_and_stored_first(monkeypatch):
    monkeypatch.setenv("CGM_INGEST_KEY", "cgm-secret")
    timestamp = int(datetime.now(timezone.utc).timestamp())
    uid = f"watch-v2-{timestamp}"
    payload = integrations.MobileGlucoseEntryV2Request(
        schema_version=2,
        reading_uid=uid,
        glucose_mgdl=117,
        timestamp=timestamp,
        trend_arrow="Flat",
        sensor_state="OK",
        sensor_session_id="opaque-session",
        sequence=42,
        sensor_type="G7",
        source_package="org.wtachtsugar",
        source="g7_direct_watch",
    )

    async with SessionLocal() as session:
        first = await integrations.mobile_glucose_entry_v2(
            payload=payload,
            request=SimpleNamespace(query_params={}),
            ingest_key_header="cgm-secret",
            session=session,
        )
        second = await integrations.mobile_glucose_entry_v2(
            payload=payload,
            request=SimpleNamespace(query_params={}),
            ingest_key_header="cgm-secret",
            session=session,
        )

    assert first.status == "accepted"
    assert first.reading_uid == uid
    assert first.usable_for_dosing is False
    assert first.sync_status == "not_required"
    assert second.status == "duplicate"
    assert second.duplicate is True


def _watch_v1_payload(timestamp_ms: int, suffix: str):
    return integrations.WatchGlucoseEntryV1Request.model_validate({
        "schemaVersion": 1,
        "readingId": f"watch-reading-{suffix}",
        "originInstallationId": f"watch-installation-{suffix}",
        "outboxSequence": 17,
        "glucoseMgDl": 126,
        "measuredAtEpochMillis": timestamp_ms,
        "receivedAtWatchEpochMillis": timestamp_ms + 1_000,
        "receivedAtPhoneEpochMillis": timestamp_ms + 2_000,
        "trendRateMgDlPerMinute": 0.4,
        "trendArrow": "Flat",
        "sensorState": 0x06,
        "displayOnly": False,
        "sensorSequence": 88,
        "sessionId": f"sensor-session-{suffix}",
        "historical": False,
        "timestampUncertain": False,
        "source": "g7_direct_watch",
        "decisionEligible": False,
    })


def test_cgm_ingest_accepts_sha256_verifier(monkeypatch):
    monkeypatch.delenv("CGM_INGEST_KEY", raising=False)
    monkeypatch.delenv("NUTRITION_INGEST_SECRET", raising=False)
    monkeypatch.delenv("NUTRITION_INGEST_KEY", raising=False)
    monkeypatch.setenv(
        "CGM_INGEST_KEY_SHA256",
        "dc0ed4cef797aef89c3c220b8bf712a3f0f62479cbf22361ca2df4b4cbe6fe30",
    )
    request = SimpleNamespace(query_params={})

    integrations._authorize_cgm_ingest_key(
        request,
        "test-watch-secret",
    )

    with pytest.raises(HTTPException) as exc_info:
        integrations._authorize_cgm_ingest_key(request, "wrong-key")

    assert exc_info.value.status_code == 401


def test_cgm_ingest_accepts_non_ascii_secret(monkeypatch):
    monkeypatch.setenv("CGM_INGEST_KEY", "clave-segura-ñ")
    monkeypatch.delenv("NUTRITION_INGEST_SECRET", raising=False)
    monkeypatch.delenv("NUTRITION_INGEST_KEY", raising=False)
    request = SimpleNamespace(query_params={})

    integrations._authorize_cgm_ingest_key(request, "clave-segura-ñ")

    with pytest.raises(HTTPException) as exc_info:
        integrations._authorize_cgm_ingest_key(request, "clave-incorrecta-á")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_watch_v1_contract_stores_continuity_only_and_returns_conflict(monkeypatch):
    monkeypatch.setenv("CGM_INGEST_KEY", "watch-secret")
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    suffix = str(timestamp_ms)
    payload = _watch_v1_payload(timestamp_ms, suffix)
    request = SimpleNamespace(
        query_params={},
        headers={"x-forwarded-proto": "https"},
        url=SimpleNamespace(scheme="https"),
    )

    async with SessionLocal() as session:
        first = await integrations.mobile_glucose_entry(
            payload=payload,
            request=request,
            ingest_key_header="watch-secret",
            session=session,
            settings=object(),
        )
        duplicate_by_sensor_identity = await integrations.mobile_glucose_entry(
            payload=payload.model_copy(update={"reading_id": f"different-{suffix}"}),
            request=request,
            ingest_key_header="watch-secret",
            session=session,
            settings=object(),
        )

    assert first.status_code == 201
    first_body = json.loads(first.body)
    assert first_body["decisionEligible"] is False
    assert first_body["duplicate"] is False
    assert duplicate_by_sensor_identity.status_code == 409
    assert json.loads(duplicate_by_sensor_identity.body)["duplicate"] is True


@pytest.mark.asyncio
async def test_watch_v1_contract_requires_https(monkeypatch):
    monkeypatch.setenv("CGM_INGEST_KEY", "watch-secret")
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    payload = _watch_v1_payload(timestamp_ms, f"http-{timestamp_ms}")
    request = SimpleNamespace(
        query_params={},
        headers={},
        url=SimpleNamespace(scheme="http"),
    )

    async with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc_info:
            await integrations.mobile_glucose_entry(
                payload=payload,
                request=request,
                ingest_key_header="watch-secret",
                session=session,
                settings=object(),
            )

    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("invalid_value", [True, 0, "false", None])
def test_watch_v1_contract_requires_exact_false(invalid_value):
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    raw = _watch_v1_payload(timestamp_ms, "invalid").model_dump(by_alias=True)
    raw["decisionEligible"] = invalid_value

    with pytest.raises(ValidationError):
        integrations.WatchGlucoseEntryV1Request.model_validate(raw)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("sensorState", "6"),
        ("sensorState", 0x02),
        ("displayOnly", True),
        ("sensorSequence", 65536),
        ("outboxSequence", 0),
    ],
)
def test_watch_v1_contract_rejects_values_filtered_by_wtachsugar(field, invalid_value):
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    raw = _watch_v1_payload(timestamp_ms, "invalid-watch-value").model_dump(by_alias=True)
    raw[field] = invalid_value

    with pytest.raises(ValidationError):
        integrations.WatchGlucoseEntryV1Request.model_validate(raw)
