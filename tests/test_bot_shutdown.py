import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "backend"))

from app.bot import service  # noqa: E402


class FakeUpdater:
    def __init__(self) -> None:
        self.stopped = False
        self.running = False

    async def stop(self) -> None:
        self.stopped = True


class FakeBotApp:
    def __init__(self) -> None:
        self.running = False
        self.updater = FakeUpdater()
        self.stop_called = False
        self.shutdown_called = False

    async def stop(self) -> None:
        self.stop_called = True
        raise RuntimeError("This Application is not running!")

    async def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.mark.asyncio
async def test_shutdown_ignores_not_running_bot(monkeypatch):
    fake_app = FakeBotApp()
    fake_app.updater.running = True
    monkeypatch.setattr(service, "_bot_app", fake_app)
    monkeypatch.setattr(service, "_polling_task", None)
    monkeypatch.setattr(service, "_leader_task", None)
    monkeypatch.setattr(service, "_leader_instance_id", None)

    await service.shutdown()

    assert fake_app.updater.stopped is True
    assert fake_app.stop_called is False
    assert fake_app.shutdown_called is True
    assert service.get_bot_application() is None


class FakeBotAppNoUpdater:
    def __init__(self) -> None:
        self.running = False
        self.stop_called = False
        self.shutdown_called = False

    async def stop(self) -> None:
        self.stop_called = True
        raise RuntimeError("This Application is not running!")

    async def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.mark.asyncio
async def test_shutdown_handles_missing_updater_and_is_idempotent(monkeypatch):
    fake_app = FakeBotAppNoUpdater()
    monkeypatch.setattr(service, "_bot_app", fake_app)
    monkeypatch.setattr(service, "_polling_task", None)
    monkeypatch.setattr(service, "_leader_task", None)
    monkeypatch.setattr(service, "_leader_instance_id", None)

    await service.shutdown()
    await service.shutdown()

    assert fake_app.stop_called is False
    assert fake_app.shutdown_called is True
    assert service.get_bot_application() is None
