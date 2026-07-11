from datetime import datetime, timezone
import json
from types import SimpleNamespace

import httpx
import pytest

from app.api import integrations
from app.services.nightscout_client import NightscoutClient


def test_dexcom_trends_are_normalized_for_nightscout():
    assert integrations._nightscout_direction("FortyFiveUp") == "FortyFiveUp"
    assert integrations._nightscout_direction("SINGLE_DOWN") == "SingleDown"
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
