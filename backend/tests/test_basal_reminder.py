import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot import proactive


@pytest.mark.asyncio
async def test_basal_reminder_runs_without_type_error(monkeypatch):
    proactive.cooldowns.cooldowns.clear()
    monkeypatch.setattr(proactive.config, "get_allowed_telegram_user_id", lambda: 123)
    monkeypatch.setattr(proactive, "get_engine", lambda: None)

    latest = SimpleNamespace(created_at=datetime.utcnow() - timedelta(hours=19))
    get_latest_mock = AsyncMock(return_value=latest)
    monkeypatch.setattr(proactive, "get_latest_basal_dose", get_latest_mock)

    bot = AsyncMock()

    await proactive.basal_reminder(bot)

    get_latest_mock.assert_awaited_once_with(user_id="admin")
    bot.send_message.assert_awaited_once()
