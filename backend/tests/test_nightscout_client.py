from datetime import datetime, timedelta

import httpx
import pytest
import respx

from app.services.nightscout_client import NightscoutClient, NightscoutError


@pytest.mark.asyncio
@respx.mock
async def test_status_success():
    route = respx.get("https://example.com/api/v1/status").mock(
        return_value=httpx.Response(200, json={"status": "ok", "version": "14.2.3"})
    )
    client = NightscoutClient(
        base_url="https://example.com",
        client=httpx.AsyncClient(base_url="https://example.com"),
    )
    status = await client.get_status()
    assert route.called
    assert status.status == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_latest_sgv_parses():
    respx.get("https://example.com/api/v1/entries/sgv").mock(
        return_value=httpx.Response(
            200,
            json=[{"sgv": 123, "direction": "Flat", "date": 1690000000000, "delta": 1.1}],
        )
    )
    client = NightscoutClient(
        base_url="https://example.com",
        client=httpx.AsyncClient(base_url="https://example.com"),
    )
    sgv = await client.get_latest_sgv()
    assert sgv.sgv == 123
    assert sgv.direction == "Flat"


@pytest.mark.asyncio
@respx.mock
async def test_recent_treatments_query():
    since = datetime.utcnow() - timedelta(minutes=30)
    route = respx.get("https://example.com/api/v1/treatments").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "eventType": "Bolus",
                    "created_at": since.isoformat(),
                    "insulin": 1.2,
                    "carbs": 15,
                }
            ],
        )
    )
    client = NightscoutClient(
        base_url="https://example.com",
        client=httpx.AsyncClient(base_url="https://example.com"),
    )
    treatments = await client.get_recent_treatments(hours=2)
    assert route.called
    assert treatments[0].eventType == "Bolus"


@pytest.mark.asyncio
@respx.mock
async def test_status_failure_raises():
    respx.get("https://example.com/api/v1/status").mock(return_value=httpx.Response(500, json={}))
    client = NightscoutClient(
        base_url="https://example.com",
        client=httpx.AsyncClient(base_url="https://example.com"),
    )
    with pytest.raises(NightscoutError):
        await client.get_status()
