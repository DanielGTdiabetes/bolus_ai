import os

import pytest

from app.bot import service as bot_service
from app.bot.state import health, BotMode


@pytest.mark.asyncio
async def test_bot_disabled_startup(monkeypatch):
    monkeypatch.setenv("ENABLE_TELEGRAM_BOT", "false")
    await bot_service.initialize()
    assert health.mode in (BotMode.DISABLED, BotMode.ERROR)


@pytest.mark.asyncio
async def test_bot_health_endpoint(monkeypatch):
    # Minimal check without hitting Telegram API
    monkeypatch.setenv("ENABLE_TELEGRAM_BOT", "false")
    from app.bot.webhook import bot_health

    res = await bot_health()
    assert "mode" in res
    assert "enabled" in res
