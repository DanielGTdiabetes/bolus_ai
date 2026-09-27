from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydexcom.glucose_reading import GlucoseReading as ShareReading

from app.services.dexcom_client import DexcomClient


@pytest.mark.asyncio
@pytest.mark.parametrize("offset_minutes", [-180, -5, 120])
async def test_share_preserves_sample_time_instead_of_replacing_with_now(offset_minutes):
    measured_at = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    measured_at = measured_at.replace(microsecond=0)
    sample = ShareReading({
        "Value": 123,
        "Trend": "Flat",
        "DT": f"Date({int(measured_at.timestamp() * 1000)}+0200)",
    })
    client = DexcomClient("test", "dummy")
    client._get_client = AsyncMock(return_value=SimpleNamespace(get_current_glucose_reading=lambda: sample))

    result = await client.get_latest_sgv()

    assert result.date == measured_at
    assert result.date.tzinfo == timezone.utc
    assert result.sgv == 123


@pytest.mark.asyncio
@pytest.mark.parametrize("timestamp", [None, datetime(2026, 9, 26, 12, 50)])
async def test_share_rejects_unknown_sample_time(timestamp):
    sample = SimpleNamespace(value=123, trend_arrow="→", datetime=timestamp)
    client = DexcomClient("test", "dummy")
    client._get_client = AsyncMock(return_value=SimpleNamespace(get_current_glucose_reading=lambda: sample))

    assert await client.get_latest_sgv() is None
