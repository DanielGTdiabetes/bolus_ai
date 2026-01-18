import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot import proactive
from app.models.settings import UserSettings, BasalScheduleItem


@pytest.mark.asyncio
async def test_basal_reminder_runs_without_type_error(monkeypatch):
    proactive.cooldowns.cooldowns.clear()
    monkeypatch.setattr(proactive.config, "get_allowed_telegram_user_id", lambda: 123)

    async def fake_user_settings():
        settings = UserSettings.default()
        settings.bot.enabled = True
        settings.bot.proactive.basal.enabled = True
        settings.bot.proactive.basal.chat_id = 123
        settings.bot.proactive.basal.schedule = [
            BasalScheduleItem(id="test", name="Basal", time="22:00", units=1.0)
        ]
        return settings

    monkeypatch.setattr(proactive.context_builder, "get_bot_user_settings_safe", fake_user_settings)

    latest = SimpleNamespace(created_at=datetime.utcnow() - timedelta(hours=19))
    get_latest_mock = AsyncMock(return_value=latest)
    monkeypatch.setattr(proactive, "get_latest_basal_dose", get_latest_mock)

    bot = AsyncMock()

    await proactive.basal_reminder(bot)
    assert get_latest_mock.await_count in (0, 1)
