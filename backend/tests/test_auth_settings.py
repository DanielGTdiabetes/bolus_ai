import importlib
import os

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


def test_login_successful(client: TestClient):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "admin"
    assert body["user"]["needs_password_change"] is True
    assert "access_token" in body


def test_settings_requires_auth(client: TestClient):
    resp = client.get("/api/settings")
    assert resp.status_code == 401


def test_settings_with_token(client: TestClient):
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login_resp.json()["access_token"]

    resp = client.get("/api/settings", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["units"] == "mg/dL"


def test_change_password_flow(client: TestClient):
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login_resp.json()["access_token"]

    change_resp = client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "admin123", "new_password": "newpass890"},
    )
    assert change_resp.status_code == 200
    assert change_resp.json()["ok"] is True

    # login again with new password
    relogin = client.post("/api/auth/login", json={"username": "admin", "password": "newpass890"})
    assert relogin.status_code == 200
    assert relogin.json()["user"]["needs_password_change"] is False
