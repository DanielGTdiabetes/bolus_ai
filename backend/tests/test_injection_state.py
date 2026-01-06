import asyncio
import importlib

import pytest
from fastapi.testclient import TestClient

from app.core import settings as settings_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
            "nightscout": {"timeout_seconds": 10},
            "server": {"host": "0.0.0.0", "port": 8000},
            "security": {
                "jwt_secret": "test-secret-1234567890",
                "jwt_issuer": "bolus-ai",
                "access_token_minutes": 60,
                "cors_origins": []
            },
            "data": { "data_dir": "%s" },
            "database": { "url": null }
        }
        """ % (str(tmp_path).replace("\\", "\\\\"))
    )

    monkeypatch.setenv("BOLUS_AI_ALLOW_IN_MEMORY", "true")
    monkeypatch.setenv("CONFIG_PATH", str(config_path))
    settings_module.DEFAULT_CONFIG_PATH = config_path
    settings_module.get_settings.cache_clear()
    import app.main as main
    importlib.reload(main)

    # Ensure DB is initialized before hitting auth
    from app.core.db import init_db, create_tables
    init_db()
    asyncio.get_event_loop().run_until_complete(create_tables())

    from app.services.auth_repo import init_auth_db
    asyncio.get_event_loop().run_until_complete(init_auth_db())

    client = TestClient(main.app)

    # Ensure admin user exists (sqlite seed may run after startup)
    from app.core.datastore import UserStore
    UserStore(tmp_path / "users.json").ensure_seed_admin()
    yield client
    settings_module.get_settings.cache_clear()


def _auth_headers(client: TestClient) -> dict[str, str]:
    login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_manual_and_rotate_persistence(client: TestClient):
    headers = _auth_headers(client)

    # Set manual rapid site
    manual_id = "abd_l_mid:2"
    resp_manual = client.post(
        "/api/injection/manual",
        headers=headers,
        json={"insulin_type": "rapid", "point_id": manual_id},
    )
    assert resp_manual.status_code == 200
    data_manual = resp_manual.json()
    assert data_manual["ok"] is True
    assert data_manual["point_id"] == manual_id
    assert data_manual["source"] == "manual"

    state_after_manual = client.get("/api/injection/state", headers=headers).json()
    assert state_after_manual["states"]["bolus"]["last_point_id"] == manual_id
    assert state_after_manual["states"]["bolus"]["source"] == "manual"

    # Rotate rapid (auto) should move forward and mark source auto
    rotate_resp = client.post(
        "/api/injection/rotate",
        headers=headers,
        json={"type": "rapid"},
    )
    assert rotate_resp.status_code == 200

    state_after_rotate = client.get("/api/injection/state", headers=headers).json()
    assert state_after_rotate["states"]["bolus"]["source"] == "auto"
    assert state_after_rotate["states"]["bolus"]["last_point_id"] != manual_id

    # Manual basal using numeric index should be accepted
    resp_basal_manual = client.post(
        "/api/injection/manual",
        headers=headers,
        json={"insulin_type": "basal", "point_id": "3"},
    )
    assert resp_basal_manual.status_code == 200
    basal_state = client.get("/api/injection/state", headers=headers).json()
    assert basal_state["states"]["basal"]["last_point_id"] == "glute_left:1"
    assert basal_state["states"]["basal"]["source"] == "manual"
