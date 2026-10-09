from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.bot import service
from app.bot.state import BotMode
from app.core import config
from app.services import stability_monitor
from app.services.stability_monitor import StabilityMonitor


@pytest.fixture(autouse=True)
def isolated_failover(monkeypatch):
    for key in ("RENDER", "APP_INSTANCE_ROLE", "APP_INSTANCE_LOCATION", "PUBLIC_URL", "BOT_PUBLIC_URL", "RENDER_EXTERNAL_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENABLE_TELEGRAM_BOT", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy")
    settings = SimpleNamespace(nas_public_url="https://nas.example", emergency_mode=False)
    monkeypatch.setattr(stability_monitor, "get_settings", lambda: settings)
    for attr, value in (
        ("_is_nas_down", False), ("_consecutive_failures", 0),
        ("_consecutive_successes", 0), ("_last_check_at", None), ("_urls_logged", False),
    ):
        monkeypatch.setattr(StabilityMonitor, attr, value)
    monkeypatch.setattr(stability_monitor, "notify_admin", AsyncMock())
    monkeypatch.setattr(service.health, "mode", BotMode.DISABLED)
    monkeypatch.setattr(service.health, "enabled", False)
    return settings


@pytest.mark.parametrize("env", [
    {"RENDER": "true"}, {"APP_INSTANCE_ROLE": "backup"},
    {"APP_INSTANCE_LOCATION": "render"}, {"APP_INSTANCE_ROLE": " BACKUP "},
])
def test_backup_detection_uses_deployment_markers(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert config.is_backup_instance()


@pytest.mark.parametrize("emergency", [False, True])
async def test_failover_requires_two_failures_and_yields_on_first_success(monkeypatch, isolated_failover, emergency):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("BOT_PUBLIC_URL", "https://backup.example")
    isolated_failover.emergency_mode = emergency
    assert service.decide_bot_mode()[0] == BotMode.DISABLED
    await StabilityMonitor._handle_failure("timeout")
    assert not StabilityMonitor.backup_can_notify()
    assert service.decide_bot_mode()[0] == BotMode.DISABLED
    await StabilityMonitor._handle_failure("timeout")
    assert StabilityMonitor.backup_can_notify()
    assert service.decide_bot_mode() == (BotMode.WEBHOOK, "cloud_failover_active")
    stability_monitor.notify_admin.assert_awaited_once()
    await StabilityMonitor._handle_success("https://nas.example")
    assert not StabilityMonitor.backup_can_notify()
    assert service.decide_bot_mode()[0] == BotMode.DISABLED
    assert StabilityMonitor._is_nas_down
    await StabilityMonitor._handle_failure("timeout")
    assert not StabilityMonitor.backup_can_notify()
    await StabilityMonitor._handle_failure("timeout")
    assert StabilityMonitor.backup_can_notify()


async def test_stale_or_unconfigured_monitor_cannot_authorize_backup(monkeypatch, isolated_failover):
    await StabilityMonitor._handle_failure("timeout")
    await StabilityMonitor._handle_failure("timeout")
    assert StabilityMonitor.backup_can_notify()
    monkeypatch.setattr(StabilityMonitor, "_last_check_at", stability_monitor.time.monotonic() - 121)
    assert not StabilityMonitor.backup_can_notify()
    monkeypatch.setattr(StabilityMonitor, "_last_check_at", stability_monitor.time.monotonic())
    isolated_failover.nas_public_url = None
    assert not StabilityMonitor.backup_can_notify()


async def test_failures_separated_by_stale_monitor_do_not_activate(monkeypatch):
    await StabilityMonitor._handle_failure("timeout")
    monkeypatch.setattr(StabilityMonitor, "_last_check_at", stability_monitor.time.monotonic() - 121)
    await StabilityMonitor._handle_failure("timeout")
    assert StabilityMonitor._consecutive_failures == 1
    assert not StabilityMonitor.backup_can_notify()


@pytest.mark.parametrize("status,payload", [(200, {"status": "ok"}), (503, {}), (200, {"unrelated": True}), (200, [])])
async def test_standby_checks_nas_without_emergency_mode(monkeypatch, respx_mock, status, payload):
    monkeypatch.setenv("RENDER", "true")
    reconcile = AsyncMock()
    monkeypatch.setattr(service, "reconcile_backup_bot", reconcile)
    respx_mock.get("https://nas.example/api/health/check").mock(return_value=httpx.Response(status, json=payload))
    await StabilityMonitor.check_health()
    await StabilityMonitor.check_health()
    assert StabilityMonitor.backup_can_notify() is (payload != {"status": "ok"})
    assert reconcile.await_count == 2


async def test_notification_failure_does_not_count_as_another_nas_failure(monkeypatch, respx_mock):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(stability_monitor, "notify_admin", AsyncMock(side_effect=RuntimeError("Telegram unavailable")))
    reconcile = AsyncMock()
    monkeypatch.setattr(service, "reconcile_backup_bot", reconcile)
    respx_mock.get("https://nas.example/api/health/check").mock(return_value=httpx.Response(503))
    await StabilityMonitor.check_health()
    await StabilityMonitor.check_health()
    assert StabilityMonitor._consecutive_failures == 2
    assert StabilityMonitor.backup_can_notify()
    assert reconcile.await_count == 2


async def test_bot_lifecycle_automatically_promotes_and_demotes(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    bot = SimpleNamespace(bot=SimpleNamespace(delete_webhook=AsyncMock()))
    monkeypatch.setattr(service, "_bot_app", bot)
    monkeypatch.setattr(service, "shutdown", AsyncMock())
    async def fake_initialize():
        mode, reason = service.decide_bot_mode()
        service.health.set_mode(mode, reason)
        service.health.enabled = mode != BotMode.DISABLED
    initialize = AsyncMock(side_effect=fake_initialize)
    monkeypatch.setattr(service, "initialize", initialize)
    from app.core import scheduler
    job = Mock()
    monkeypatch.setattr(scheduler, "get_scheduler", lambda: SimpleNamespace(get_job=lambda job_id: job))
    await service.reconcile_backup_bot()
    initialize.assert_not_awaited()
    await StabilityMonitor._handle_failure("timeout")
    await StabilityMonitor._handle_failure("timeout")
    await service.reconcile_backup_bot()
    assert service.health.mode == BotMode.POLLING
    assert initialize.await_count == 1
    job.modify.assert_called_once()
    await service.reconcile_backup_bot()
    assert initialize.await_count == 1
    await StabilityMonitor._handle_success("https://nas.example")
    await service.reconcile_backup_bot()
    assert service.health.mode == BotMode.DISABLED
    assert initialize.await_count == 2
    bot.bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=True)


async def test_real_bot_initialize_and_shutdown_follow_failover(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("BOT_PUBLIC_URL", "https://backup.example")
    for attr in ("_bot_app", "_polling_task", "_leader_task", "_leader_instance_id"):
        monkeypatch.setattr(service, attr, None)
    apps = []
    def make_app():
        app = SimpleNamespace(
            bot=SimpleNamespace(set_webhook=AsyncMock(), delete_webhook=AsyncMock()),
            updater=SimpleNamespace(running=False), running=False,
            initialize=AsyncMock(), start=AsyncMock(), stop=AsyncMock(),
            shutdown=AsyncMock(), add_handler=Mock(),
        )
        async def start():
            app.running = True
        app.start.side_effect = start
        apps.append(app)
        return app
    monkeypatch.setattr(service, "create_bot_app", make_app)
    async def acquire(mode, reason):
        return mode, reason, mode != BotMode.DISABLED
    monkeypatch.setattr(service, "_acquire_leader_lock", acquire)
    from app.core import scheduler
    monkeypatch.setattr(scheduler, "get_scheduler", lambda: None)

    await service.initialize()
    apps[0].start.assert_not_awaited()
    assert service.health.mode == BotMode.DISABLED
    await StabilityMonitor._handle_failure("timeout")
    await StabilityMonitor._handle_failure("timeout")
    await service.reconcile_backup_bot()
    apps[0].shutdown.assert_awaited_once()
    apps[1].start.assert_awaited_once()
    apps[1].bot.set_webhook.assert_awaited_once()
    assert service.health.mode == BotMode.WEBHOOK
    await StabilityMonitor._handle_success("https://nas.example")
    await service.reconcile_backup_bot()
    apps[1].bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=True)
    apps[1].stop.assert_awaited_once()
    apps[1].shutdown.assert_awaited_once()
    apps[2].start.assert_not_awaited()
    assert service.health.mode == BotMode.DISABLED


async def test_standby_drops_incoming_updates(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    app = SimpleNamespace(process_update=AsyncMock())
    monkeypatch.setattr(service, "_bot_app", app)
    monkeypatch.setattr(service.health, "mode", BotMode.WEBHOOK)
    await service.process_update({"update_id": 1})
    app.process_update.assert_not_awaited()


async def test_polling_guard_drops_queued_updates_after_nas_recovery(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(service.health, "mode", BotMode.POLLING)
    with pytest.raises(service.ApplicationHandlerStop):
        await service._backup_update_guard(None, None)
    await StabilityMonitor._handle_failure("timeout")
    await StabilityMonitor._handle_failure("timeout")
    await service._backup_update_guard(None, None)
    await StabilityMonitor._handle_success("https://nas.example")
    with pytest.raises(service.ApplicationHandlerStop):
        await service._backup_update_guard(None, None)


@pytest.mark.parametrize("backup,emergency", [(True, False), (True, True), (False, False), (False, True)])
def test_scheduler_keeps_primary_jobs_off_backup(monkeypatch, isolated_failover, backup, emergency):
    from app import jobs
    if backup:
        monkeypatch.setenv("APP_INSTANCE_ROLE", "backup")
    isolated_failover.emergency_mode = emergency
    monkeypatch.setattr(jobs, "get_settings", lambda: isolated_failover)
    monkeypatch.setattr(jobs, "init_scheduler", Mock())
    scheduled = {}
    monkeypatch.setattr(jobs, "schedule_task", lambda func, trigger, task_id: scheduled.update({task_id: func}))
    monkeypatch.setattr(jobs.jobs_state, "refresh_next_run", Mock())
    jobs.setup_periodic_tasks()
    if backup:
        assert set(scheduled) == {"check_nas_health", "basal_reminder"}
    elif emergency:
        assert set(scheduled) == {"check_nas_health"}
    else:
        assert {"basal_reminder", "guardian_check", "glucose_sync", "learning_eval"} <= set(scheduled)
        assert "check_nas_health" not in scheduled
