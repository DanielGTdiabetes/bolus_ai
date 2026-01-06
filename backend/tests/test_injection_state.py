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
        json={"insulin_type": "rapid"},
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


def test_manual_persists_for_full_state(client: TestClient):
    headers = _auth_headers(client)

    manual_id = "abd_r_top:1"
    resp_manual = client.post(
        "/api/injection/manual",
        headers=headers,
        json={"insulin_type": "rapid", "point_id": manual_id},
    )
    assert resp_manual.status_code == 200

    state_resp = client.get("/api/injection/state", headers=headers).json()
    full_resp = client.get("/api/injection/full", headers=headers).json()

    assert state_resp["states"]["bolus"]["last_point_id"] == manual_id
    assert full_resp["states"]["bolus"]["last_point_id"] == manual_id


def test_manual_round_trip_persists_state(client: TestClient):
    headers = _auth_headers(client)

    manual_id = "abd_r_top:1"
    resp_manual = client.post(
        "/api/injection/manual",
        headers=headers,
        json={"insulin_type": "rapid", "point_id": manual_id},
    )
    assert resp_manual.status_code == 200
    payload = resp_manual.json()
    assert payload["point_id"] == manual_id
    assert payload["source"] == "manual"

    state = client.get("/api/injection/state", headers=headers).json()
    assert state["bolus"] == manual_id
    assert state["states"]["bolus"]["last_point_id"] == manual_id
    assert state["states"]["bolus"]["source"] == "manual"


def test_basal_and_rapid_states_are_independent(client: TestClient):
    headers = _auth_headers(client)

    basal_id = "glute_left:1"
    rapid_id = "abd_l_top:2"

    assert (
        client.post(
            "/api/injection/manual",
            headers=headers,
            json={"insulin_type": "basal", "point_id": basal_id},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/injection/manual",
            headers=headers,
            json={"insulin_type": "rapid", "point_id": rapid_id},
        ).status_code
        == 200
    )

    state = client.get("/api/injection/state", headers=headers).json()
    assert state["states"]["basal"]["last_point_id"] == basal_id
    assert state["states"]["bolus"]["last_point_id"] == rapid_id


def test_bolus_alias_maps_to_rapid(client: TestClient):
    headers = _auth_headers(client)

    rapid_id = "abd_r_mid:3"
    resp_manual = client.post(
        "/api/injection/manual",
        headers=headers,
        json={"insulin_type": "bolus", "point_id": rapid_id},
    )
    assert resp_manual.status_code == 200
    data = resp_manual.json()
    assert data["point_id"] == rapid_id
    assert data["insulin_type"] == "rapid"

    state = client.get("/api/injection/state", headers=headers).json()
    assert state["states"]["bolus"]["last_point_id"] == rapid_id


@pytest.mark.asyncio
async def test_set_current_site_executes_textual_sql(monkeypatch):
    pytest.importorskip("aiosqlite")

    from sqlalchemy.ext.asyncio import create_async_engine  # noqa: WPS433
    from sqlalchemy.pool import StaticPool  # noqa: WPS433

    import app.core.db as core_db
    from app.services import async_injection_manager as mgr_module
    from app.services.async_injection_manager import AsyncInjectionManager

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    try:
        async with engine.begin() as conn:
            await conn.run_sync(core_db.Base.metadata.create_all)

        monkeypatch.setattr(mgr_module, "get_engine", lambda: engine)

        manager = AsyncInjectionManager("admin")

        await manager.set_current_site("rapid", "abd_l_mid:1", source="manual")
        state = await manager.get_state()
        assert state["rapid"]["last_used_id"] == "abd_l_mid:1"
        assert state["rapid"]["source"] == "manual"

        await manager.set_current_site("rapid", "abd_l_mid:2", source="manual")
        state = await manager.get_state()
        assert state["rapid"]["last_used_id"] == "abd_l_mid:2"

        await manager.set_current_site("basal", "glute_left:1", source="manual")
        state = await manager.get_state()
        assert state["basal"]["last_used_id"] == "glute_left:1"
    finally:
        await engine.dispose()
