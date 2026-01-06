import importlib
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from app.core import settings as settings_module


class DummyWebhookInfo:
    def __init__(self, url: Optional[str]):
        self.url = url
        self.has_custom_certificate = False
        self.pending_update_count = 0
        self.last_error_date = None
        self.last_error_message = None
        self.max_connections = 40
        self.ip_address = "1.1.1.1"


class DummyBot:
    def __init__(self):
        self.set_webhook_called = False
        self.get_webhook_info_called = False

    async def set_webhook(self, **kwargs):
        self.set_webhook_called = True

    async def get_webhook_info(self):
        self.get_webhook_info_called = True
        return DummyWebhookInfo("https://example.com/api/webhook/telegram")


class DummyApp:
    def __init__(self):
        self.bot = DummyBot()


def test_webhook_diag_missing_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-1234567890")
    monkeypatch.setenv("ENABLE_TELEGRAM_BOT", "false")
    settings_module.get_settings.cache_clear()

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    resp = client.get("/api/bot/telegram/webhook")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] == "missing_token"
    assert body["telegram_webhook_info"] is None


def test_webhook_refresh_requires_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-1234567890")
    monkeypatch.setenv("ADMIN_SHARED_SECRET", "super-secret")
    settings_module.get_settings.cache_clear()
    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    resp = client.post("/api/bot/telegram/webhook/refresh")
    assert resp.status_code == 403


def test_webhook_refresh_ok(monkeypatch, tmp_path):
    # Fresh client to avoid startup side effects
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-1234567890")
    monkeypatch.setenv("ADMIN_SHARED_SECRET", "super-secret")
    monkeypatch.setenv("BOT_PUBLIC_URL", "https://example.com")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    settings_module.get_settings.cache_clear()
    import app.main as main
    importlib.reload(main)

    # Inject dummy bot app
    from app.bot import service as bot_service

    bot_service._bot_app = DummyApp()

    client = TestClient(main.app)

    resp = client.post("/api/bot/telegram/webhook/refresh", headers={"X-Admin-Secret": "super-secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["expected_webhook_url"] == "https://example.com/api/webhook/telegram"
    assert body["telegram_webhook_info"]["url"] == "https://example.com/api/webhook/telegram"

    assert bot_service._bot_app.bot.set_webhook_called is True
    assert bot_service._bot_app.bot.get_webhook_info_called is True


def test_webhook_endpoint_available(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-1234567890")
    monkeypatch.setenv("ENABLE_TELEGRAM_BOT", "false")
    settings_module.get_settings.cache_clear()

    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)

    resp = client.post("/api/webhook/telegram", json={"update_id": 1})
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"
