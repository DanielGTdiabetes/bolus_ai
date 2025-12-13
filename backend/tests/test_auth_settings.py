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


def test_settings_requires_auth(client: TestClient):
    resp = client.get("/api/settings")
    assert resp.status_code == 401


def test_login_and_access_settings(client: TestClient):
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    resp = client.get("/api/settings", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["units"] == "mg/dL"
