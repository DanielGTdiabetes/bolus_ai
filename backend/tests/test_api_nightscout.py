import importlib
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core import settings as settings_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-1234567890")
    settings_module.get_settings.cache_clear()
    import app.main as main

    importlib.reload(main)
    client = TestClient(main.app)
    yield client
    settings_module.get_settings.cache_clear()


def test_nightscout_flow(client: TestClient):
    # 1. Login
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Check status (initially disabled)
    resp = client.get("/api/nightscout/status", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["url"] is None

    # 3. Configure Nightscout
    config_payload = {
        "enabled": True,
        "url": "https://test-ns.example.com",
        "token": "secret-token"
    }
    client.put("/api/nightscout/config", headers=headers, json=config_payload)

    # 4. Check status again (enabled, mocked ping)
    with patch("app.api.nightscout.NightscoutClient") as MockClient:
        instance = MockClient.return_value
        instance.get_status = AsyncMock(return_value={"status": "ok"})
        instance.aclose = AsyncMock()
        
        resp = client.get("/api/nightscout/status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["url"] == "https://test-ns.example.com"
        assert data["ok"] is True


def test_nightscout_test_endpoint(client: TestClient):
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    with patch("app.api.nightscout.NightscoutClient") as MockClient:
        instance = MockClient.return_value
        instance.get_status = AsyncMock(return_value={"status": "ok"})
        instance.aclose = AsyncMock()

        # Test with payload
        resp = client.post(
            "/api/nightscout/test", 
            headers=headers, 
            json={"enabled": True, "url": "https://ns.test", "token": "foo"}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["message"] == "Conexión exitosa a Nightscout"
