import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from telegram import CallbackQuery, Update, User
from telegram.ext import Application, ExtBot

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
    for attr in ("_bot_app", "_polling_task", "_leader_task", "_leader_instance_id"):
        monkeypatch.setattr(service, attr, None)
    monkeypatch.setattr(service, "_webhook_registered", False)
    monkeypatch.setattr(service, "_backup_update_tasks", set())
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
    bot = SimpleNamespace(bot=SimpleNamespace(delete_webhook=AsyncMock()), running=False,
                          updater=SimpleNamespace(running=False))
    monkeypatch.setattr(service, "_bot_app", bot)
    monkeypatch.setattr(service, "shutdown", AsyncMock())
    async def fake_initialize():
        mode, reason = service.decide_bot_mode()
        service.health.set_mode(mode, reason)
        service.health.enabled = mode != BotMode.DISABLED
        bot.running = bot.updater.running = mode == BotMode.POLLING
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


@pytest.mark.parametrize("public_url", [None, "https://backup.example"])
async def test_retries_reception_after_all_telegram_start_attempts_fail(monkeypatch, public_url):
    monkeypatch.setenv("RENDER", "true")
    if public_url:
        monkeypatch.setenv("BOT_PUBLIC_URL", public_url)
    apps = []
    def make_app():
        failing = len(apps) == 1
        app = SimpleNamespace(
            bot=SimpleNamespace(
                set_webhook=AsyncMock(side_effect=RuntimeError("Telegram unavailable") if failing else None),
                delete_webhook=AsyncMock(), get_webhook_info=AsyncMock(return_value=SimpleNamespace(url="")),
            ),
            updater=SimpleNamespace(running=False, start_polling=AsyncMock(), stop=AsyncMock()),
            running=False, initialize=AsyncMock(), start=AsyncMock(), stop=AsyncMock(),
            shutdown=AsyncMock(), add_handler=Mock(),
        )
        async def start():
            app.running = True
        async def poll(**kwargs):
            if failing:
                raise RuntimeError("Telegram unavailable")
            app.updater.running = True
        app.start.side_effect = start
        app.updater.start_polling.side_effect = poll
        apps.append(app)
        return app
    monkeypatch.setattr(service, "create_bot_app", make_app)
    async def acquire(mode, reason):
        return mode, reason, mode != BotMode.DISABLED
    monkeypatch.setattr(service, "_acquire_leader_lock", acquire)
    original_sleep = asyncio.sleep
    async def fast_sleep(delay):
        await original_sleep(0)
    monkeypatch.setattr(service.asyncio, "sleep", fast_sleep)
    from app.core import scheduler
    monkeypatch.setattr(scheduler, "get_scheduler", lambda: None)
    try:
        await service.initialize()
        await StabilityMonitor._handle_failure("timeout")
        await StabilityMonitor._handle_failure("timeout")
        await service.reconcile_backup_bot()
        await service._polling_task
        assert service.health.mode == BotMode.ERROR
        assert not service.health.enabled
        assert not service._backup_reception_ready()
        assert apps[1].updater.start_polling.await_count == 7

        await service.reconcile_backup_bot()
        if service._polling_task:
            await service._polling_task
        assert len(apps) == 3
        assert service._backup_reception_ready()
        assert service.health.enabled
        await service.reconcile_backup_bot()
        assert len(apps) == 3
    finally:
        await service.shutdown()


async def test_does_not_restart_polling_while_start_attempt_is_pending(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    await StabilityMonitor._handle_failure("timeout")
    await StabilityMonitor._handle_failure("timeout")
    monkeypatch.setattr(service, "_bot_app", SimpleNamespace(running=True))
    pending = asyncio.create_task(asyncio.Event().wait())
    monkeypatch.setattr(service, "_polling_task", pending)
    initialize = AsyncMock()
    monkeypatch.setattr(service, "initialize", initialize)
    try:
        await service.reconcile_backup_bot()
        initialize.assert_not_awaited()
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("mode", [BotMode.POLLING, BotMode.WEBHOOK])
async def test_active_mode_label_alone_does_not_prevent_reception_retry(monkeypatch, mode):
    monkeypatch.setenv("RENDER", "true")
    await StabilityMonitor._handle_failure("timeout")
    await StabilityMonitor._handle_failure("timeout")
    service.health.set_mode(mode, "previous_start_attempt")
    monkeypatch.setattr(service, "_bot_app", SimpleNamespace(running=True, updater=SimpleNamespace(running=False)))
    shutdown = AsyncMock()
    initialize = AsyncMock()
    monkeypatch.setattr(service, "shutdown", shutdown)
    monkeypatch.setattr(service, "initialize", initialize)
    await service.reconcile_backup_bot()
    shutdown.assert_awaited_once()
    initialize.assert_awaited_once()


@pytest.mark.parametrize("transport", ["webhook", "polling"])
@pytest.mark.parametrize("stage", ["answer", "settings"])
async def test_recovery_cancels_dispatched_basal_callback_before_write(monkeypatch, transport, stage):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test")
    await StabilityMonitor._handle_failure("timeout")
    await StabilityMonitor._handle_failure("timeout")
    service.health.set_mode(BotMode.WEBHOOK if transport == "webhook" else BotMode.POLLING, "test")
    app = service.create_bot_app()
    app._initialized = True
    monkeypatch.setattr(service, "_bot_app", app)
    monkeypatch.setattr(service, "_check_auth", AsyncMock(return_value=True))
    entered = asyncio.Event()
    blocker = asyncio.Event()
    async def answer(*args, **kwargs):
        if stage == "answer":
            entered.set()
            await blocker.wait()
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    async def read_settings():
        if stage == "settings":
            entered.set()
            await blocker.wait()
        return SimpleNamespace(), "admin"
    monkeypatch.setattr(service, "get_bot_user_settings_with_user_id", read_settings)
    write = AsyncMock()
    reply = AsyncMock()
    monkeypatch.setattr(service, "upsert_basal_dose", write)
    monkeypatch.setattr(service, "edit_message_text_safe", reply)
    monkeypatch.setattr(service, "shutdown", AsyncMock())
    async def initialize():
        service.health.set_mode(BotMode.DISABLED, "emergency_mode_send_only")
    monkeypatch.setattr(service, "initialize", initialize)
    async def delete_webhook(*args, **kwargs):
        # Operations must finish cancellation before waiting on Telegram cleanup.
        assert not service._backup_update_tasks
        write.assert_not_awaited()
        reply.assert_not_awaited()
    monkeypatch.setattr(type(app.bot), "delete_webhook", delete_webhook)
    payload = {"update_id": 1, "callback_query": {
        "id": "query", "from": {"id": 1, "is_bot": False, "first_name": "Test"},
        "chat_instance": "chat", "data": "basal_confirm|18", "message": {
            "message_id": 2, "date": 0, "chat": {"id": 1, "type": "private"}, "text": "Basal",
        },
    }}
    coroutine = service.process_update(payload) if transport == "webhook" else app.process_update(Update.de_json(payload, app.bot))
    request = asyncio.create_task(coroutine)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await StabilityMonitor._handle_success("https://nas.example")
        await service.reconcile_backup_bot()
        await asyncio.wait_for(request, timeout=2)
        blocker.set()
        write.assert_not_awaited()
        reply.assert_not_awaited()
        assert not request.cancelled()
        assert not service._backup_update_tasks
    finally:
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)


async def test_demotion_cancels_detached_callback_work(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    entered = asyncio.Event()
    write = AsyncMock()
    async def refresh():
        entered.set()
        await asyncio.Event().wait()
        await write()
    task = service._create_update_task(refresh(), name="mfp-refresh-test")
    await entered.wait()
    await service.shutdown()
    assert task.cancelled()
    assert not service._backup_update_tasks
    write.assert_not_awaited()


async def test_external_update_cancellation_still_propagates(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test")
    entered = asyncio.Event()
    async def dispatch(self, update):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(Application, "process_update", dispatch)
    app = service.create_bot_app()
    request = asyncio.create_task(app.process_update(None))
    await entered.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert not service._backup_update_tasks


async def test_primary_updates_are_not_cancelled_by_backup_cleanup(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test")
    entered = asyncio.Event()
    resume = asyncio.Event()
    completed = Mock()
    async def dispatch(self, update):
        entered.set()
        await resume.wait()
        completed()
    monkeypatch.setattr(Application, "process_update", dispatch)
    app = service.create_bot_app()
    request = asyncio.create_task(app.process_update(None))
    await entered.wait()
    await service._cancel_backup_updates()
    assert not request.done()
    resume.set()
    await request
    completed.assert_called_once()


async def test_basal_tool_preserves_cancellation_during_user_resolution(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(service.tools, "SessionLocal", lambda: session)
    entered = asyncio.Event()
    async def resolve_user(session):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(service.tools, "_resolve_user_id", resolve_user)
    write = AsyncMock()
    monkeypatch.setattr(service.tools.basal_repo, "upsert_basal_dose", write)
    task = service._create_update_task(service.tools.register_basal({"dose_u": 18}), name="backup-basal-tool")
    await entered.wait()
    await service.shutdown()
    assert task.cancelled()
    write.assert_not_awaited()


@pytest.mark.parametrize("failure_stage", ["initialize", "start"])
async def test_failed_startup_closes_both_http_pools_before_retry(monkeypatch, failure_stage):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test")
    await StabilityMonitor._handle_failure("timeout")
    await StabilityMonitor._handle_failure("timeout")
    apps = []
    factory = service.create_bot_app
    def make_app():
        app = factory()
        apps.append(app)
        return app
    monkeypatch.setattr(service, "create_bot_app", make_app)
    async def acquire(mode, reason):
        return mode, reason, True
    monkeypatch.setattr(service, "_acquire_leader_lock", acquire)
    monkeypatch.setattr(ExtBot, "get_me", AsyncMock(
        side_effect=RuntimeError("Telegram unavailable") if failure_stage == "initialize" else None,
        return_value=User(id=1, first_name="Test", is_bot=True),
    ))
    start = AsyncMock(side_effect=RuntimeError("Application start failed"))
    monkeypatch.setattr(Application, "start", start)
    monkeypatch.setattr(service.asyncio, "sleep", AsyncMock())

    for attempt in range(2):
        await service.reconcile_backup_bot()
        assert len(apps) == attempt + 1
        assert all(request._client.is_closed for request in apps[-1]._http_requests)
        assert service._bot_app is None
        assert service.health.mode == BotMode.ERROR
        assert not service.health.enabled
    assert start.await_count == (6 if failure_stage == "start" else 0)


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
