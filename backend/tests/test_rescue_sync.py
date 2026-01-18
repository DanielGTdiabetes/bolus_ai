import httpx
import pytest
import respx
from sqlalchemy import delete
from unittest.mock import AsyncMock

from app.core.db import SessionLocal
from app.models.nightscout_secrets import NightscoutSecrets
from app.services.nightscout_secrets_service import upsert_ns_config
from app.services.rescue_sync import run_rescue_sync


@pytest.mark.asyncio
async def test_rescue_sync_skips_without_secret(monkeypatch):
    async with SessionLocal() as session:
        await session.execute(delete(NightscoutSecrets))
        await session.commit()

    http_get = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, "get", http_get)

    await run_rescue_sync(hours=1)

    http_get.assert_not_called()


@pytest.mark.asyncio
@respx.mock
async def test_rescue_sync_uses_db_nightscout_url():
    async with SessionLocal() as session:
        await session.execute(delete(NightscoutSecrets))
        await session.commit()
        await upsert_ns_config(
            session,
            user_id="admin",
            url="https://nightscout.example.com",
            api_secret="secret-token",
            enabled=True,
        )

    route = respx.get("https://nightscout.example.com/api/v1/treatments").mock(
        return_value=httpx.Response(200, json=[]),
    )

    await run_rescue_sync(hours=1)

    assert route.called
