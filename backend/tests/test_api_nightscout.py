import importlib
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core import settings as settings_module
from app.models.schemas import NightscoutSGV


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-1234567890")
    settings_module.get_settings.cache_clear()
    import app.main as main

    importlib.reload(main)
    from app.core.datastore import UserStore
    UserStore(tmp_path / "users.json").ensure_seed_admin()
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
        assert data["url"].rstrip("/") == "https://test-ns.example.com"
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


def _make_compression_entries():
    base = datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc)
    return [
        NightscoutSGV(sgv=110, direction="Flat", date=base),
        NightscoutSGV(sgv=60, direction="Flat", date=base + timedelta(minutes=5)),
        NightscoutSGV(sgv=85, direction="Flat", date=base + timedelta(minutes=10)),
    ]


def test_current_glucose_get_uses_filter_settings(client: TestClient):
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    client.put("/api/nightscout/secret", headers=headers, json={
        "url": "https://test-ns.example.com",
        "api_secret": "secret-token",
        "enabled": True
    })

    settings_res = client.get("/api/settings/", headers=headers).json()
    settings_payload = settings_res["settings"] or {}
    settings_payload["nightscout"] = {
        **(settings_payload.get("nightscout") or {}),
        "filter_compression": True,
        "filter_night_start": "23:00",
        "filter_night_end": "07:00",
        "treatments_lookback_minutes": 120
    }
    client.put("/api/settings/", headers=headers, json={
        "settings": settings_payload,
        "version": settings_res["version"]
    })

    entries = _make_compression_entries()
    with patch("app.api.nightscout.NightscoutClient") as MockClient:
        instance = MockClient.return_value
        instance.get_sgv_range = AsyncMock(return_value=entries)
        instance.get_latest_sgv = AsyncMock(return_value=entries[-1])
        instance.get_recent_treatments = AsyncMock(return_value=[])
        instance.get_clock_skew_ms.return_value = 0
        instance.aclose = AsyncMock()

        resp = client.get("/api/nightscout/current", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["is_compression"], bool)


def test_current_glucose_post_stateless_filter(client: TestClient):
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    entries = _make_compression_entries()
    with patch("app.api.nightscout.NightscoutClient") as MockClient:
        instance = MockClient.return_value
        instance.get_sgv_range = AsyncMock(return_value=entries)
        instance.get_latest_sgv = AsyncMock(return_value=entries[-1])
        instance.get_recent_treatments = AsyncMock(return_value=[])
        instance.get_clock_skew_ms.return_value = 0
        instance.aclose = AsyncMock()

        resp = client.post("/api/nightscout/current", headers=headers, json={
            "url": "https://test-ns.example.com",
            "token": "secret-token",
            "filter_compression": True,
            "night_start": "23:00",
            "night_end": "07:00",
            "lookback": 120
        })
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["is_compression"], bool)
