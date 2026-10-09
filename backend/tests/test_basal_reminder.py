from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

# Import the service first, matching startup's import order.
from app.bot import service, proactive
from app.bot.state import BotMode
from app.models.settings import UserSettings, BasalScheduleItem
from app.services.stability_monitor import StabilityMonitor
from app.utils.timezone import get_user_timezone


@pytest.fixture
def reminder(monkeypatch, tmp_path):
    settings = UserSettings.default()
    settings.bot.enabled = True
    settings.bot.proactive.basal.enabled = True
    settings.bot.proactive.basal.chat_id = 123
    settings.bot.proactive.basal.schedule = [
        BasalScheduleItem(
            id="test", name="Basal",
            time=datetime.now(get_user_timezone()).strftime("%H:%M"), units=1.0,
        )
    ]
    load_settings = AsyncMock(return_value=(settings, "admin"))
    monkeypatch.setattr(proactive.context_builder, "get_bot_user_settings_with_user", load_settings)
    monkeypatch.setattr(proactive, "get_settings", lambda: SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path)))
    monkeypatch.setattr(proactive.config, "is_backup_instance", lambda: False)
    monkeypatch.setattr(proactive.health, "mode", BotMode.POLLING)
    monkeypatch.setattr(proactive, "get_recent_treatments_db", AsyncMock(return_value=[]))
    monkeypatch.setattr(proactive, "get_latest_basal_dose", AsyncMock(return_value=None))
    store = Mock()
    store.load_events.return_value = []
    monkeypatch.setattr(proactive, "DataStore", Mock(return_value=store))
    from app.bot.llm import router
    monkeypatch.setattr(router, "handle_event", AsyncMock(return_value=SimpleNamespace(text="Basal", buttons=[])))
    send = AsyncMock(return_value=SimpleNamespace(message_id=1))
    monkeypatch.setattr(service, "bot_send", send)
    return SimpleNamespace(load_settings=load_settings, send=send, store=store, router=router)


async def test_basal_reminder_sends_on_primary(reminder):
    await proactive.basal_reminder()
    reminder.send.assert_awaited_once()
    reminder.store.save_events.assert_called_once()
    assert proactive.get_proactive_status()["basal"]["sent"] is True


@pytest.mark.parametrize("force", [False, True])
async def test_backup_standby_cannot_send_even_when_forced(monkeypatch, reminder, force):
    monkeypatch.setattr(proactive.config, "is_backup_instance", lambda: True)
    monkeypatch.setattr(StabilityMonitor, "backup_can_notify", lambda: False)
    await proactive.basal_reminder(force=force)
    reminder.load_settings.assert_not_awaited()
    reminder.send.assert_not_awaited()
    reminder.store.save_events.assert_not_called()
    assert proactive.get_proactive_status()["basal"]["reason"] == "backup_standby"


async def test_backup_sends_after_confirmed_outage(monkeypatch, reminder):
    monkeypatch.setattr(proactive.config, "is_backup_instance", lambda: True)
    monkeypatch.setattr(StabilityMonitor, "backup_can_notify", lambda: True)
    await proactive.basal_reminder()
    reminder.send.assert_awaited_once()


async def test_nas_recovery_during_reminder_preparation_prevents_send(monkeypatch, reminder):
    monkeypatch.setattr(proactive.config, "is_backup_instance", lambda: True)
    allowed = iter([True, False])
    monkeypatch.setattr(StabilityMonitor, "backup_can_notify", lambda: next(allowed))
    await proactive.basal_reminder()
    reminder.router.handle_event.assert_awaited_once()
    reminder.send.assert_not_awaited()
    reminder.store.save_events.assert_not_called()


@pytest.mark.parametrize("mode", [BotMode.DISABLED, BotMode.ERROR])
async def test_inactive_bot_cannot_send(monkeypatch, reminder, mode):
    monkeypatch.setattr(proactive.health, "mode", mode)
    await proactive.basal_reminder(force=True)
    reminder.send.assert_not_awaited()
    assert proactive.get_proactive_status()["basal"]["reason"] == "bot_inactive"


async def test_failed_delivery_does_not_mark_basal_asked(reminder):
    reminder.send.return_value = None
    await proactive.basal_reminder()
    reminder.store.save_events.assert_not_called()
    assert proactive.get_proactive_status()["basal"]["reason"] == "send_failed"
