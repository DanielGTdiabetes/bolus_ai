import asyncio
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core import settings as settings_module
from app.core.db import get_db_session
from app.core.security import TokenManager
from app.core.settings import get_settings
from app.models.treatment import Treatment


@pytest.fixture()
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    db_path = tmp_path / "test.db"
    config = {
        "nightscout": {"timeout_seconds": 10},
        "server": {"host": "0.0.0.0", "port": 8000},
        "security": {
            "jwt_secret": "test-secret-1234567890",
            "jwt_issuer": "bolus-ai",
            "access_token_minutes": 60,
            "cors_origins": [],
        },
        "data": {"data_dir": str(tmp_path)},
        "database": {"url": None},
    }
    config_path.write_text(json.dumps(config))

    monkeypatch.setenv("BOLUS_AI_ALLOW_IN_MEMORY", "true")
    monkeypatch.setenv("CONFIG_PATH", str(config_path))
    monkeypatch.setenv("NUTRITION_INGEST_SECRET", "test-ingest-secret")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_ID", "12345")
    settings_module.DEFAULT_CONFIG_PATH = config_path
    settings_module.get_settings.cache_clear()

    import app.main as main

    importlib.reload(main)

    from app.core.db import init_db, create_tables
    from app.services.auth_repo import init_auth_db
    from app.core.datastore import UserStore

    init_db()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_tables())
    loop.run_until_complete(init_auth_db())

    sync_engine = create_engine(f"sqlite:///{db_path}")
    Treatment.__table__.create(bind=sync_engine, checkfirst=True)
    SessionLocal = sessionmaker(bind=sync_engine)

    class SyncSessionWrapper:
        def __init__(self, sync_session):
            self._sync = sync_session

        def add(self, obj):
            self._sync.add(obj)

        async def commit(self):
            await asyncio.to_thread(self._sync.commit)

        async def execute(self, stmt):
            return await asyncio.to_thread(self._sync.execute, stmt)

        async def get(self, model, pk):
            return await asyncio.to_thread(self._sync.get, model, pk)

        async def close(self):
            await asyncio.to_thread(self._sync.close)

    async def override_db_session():
        session = SessionLocal()
        wrapper = SyncSessionWrapper(session)
        try:
            yield wrapper
        finally:
            await wrapper.close()

    main.app.dependency_overrides[get_db_session] = override_db_session
    client = TestClient(main.app)
    client._session_factory = SessionLocal
    UserStore(Path(tmp_path) / "users.json").ensure_seed_admin()
    yield client

    main.app.dependency_overrides.clear()
    settings_module.get_settings.cache_clear()


def _auth_headers(client: TestClient) -> dict[str, str]:
    token = TokenManager(get_settings()).create_access_token("admin")
    return {"Authorization": f"Bearer {token}"}


def _fetch_all_treatments(client: TestClient):
    session_factory = getattr(client, "_session_factory")
    with session_factory() as session:
        result = session.execute(select(Treatment))
        return result.scalars().all()


def _recent_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def test_updates_fiber_on_same_timestamp(client: TestClient):
    headers = _auth_headers(client)
    ts = _recent_timestamp()
    base_payload = {"carbs": 30, "fat": 10, "protein": 7, "fiber": 12, "date": ts}

    resp_first = client.post("/api/integrations/nutrition", headers=headers, json=base_payload)
    assert resp_first.status_code == 200

    resp_second = client.post(
        "/api/integrations/nutrition",
        headers=headers,
        json={**base_payload, "fiber": 18},
    )
    assert resp_second.status_code == 200

    treatments = _fetch_all_treatments(client)
    assert len(treatments) == 1
    assert treatments[0].fiber == pytest.approx(18.0)


def test_accepts_fiber_only_meal(client: TestClient):
    headers = _auth_headers(client)
    ts = _recent_timestamp()

    resp = client.post(
        "/api/integrations/nutrition",
        headers=headers,
        json={"fiber": 10, "date": ts},
    )
    assert resp.status_code == 200

    treatments = _fetch_all_treatments(client)
    assert len(treatments) == 1
    saved = treatments[0]
    assert saved.carbs == pytest.approx(0.0)
    assert saved.fat == pytest.approx(0.0)
    assert saved.protein == pytest.approx(0.0)
    assert saved.fiber == pytest.approx(10.0)


def test_triggers_notification_for_valid_meal(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    headers = _auth_headers(client)
    ts = _recent_timestamp()
    called = {}

    async def fake_on_new_meal_received(carbs, fat, protein, fiber, source, origin_id=None):
        called["args"] = {
            "carbs": carbs,
            "fat": fat,
            "protein": protein,
            "fiber": fiber,
            "source": source,
            "origin_id": origin_id,
        }

    monkeypatch.setattr("app.bot.service.on_new_meal_received", fake_on_new_meal_received)

    resp = client.post(
        "/api/integrations/nutrition",
        headers=headers,
        json={"fat": 12, "protein": 4, "date": ts},
    )
    assert resp.status_code == 200

    treatments = _fetch_all_treatments(client)
    assert len(treatments) == 1
    assert called["args"]["origin_id"] == treatments[0].id
    assert called["args"]["fat"] == pytest.approx(12.0)


def test_allows_secret_without_jwt(client: TestClient):
    ts = "2025-03-01T09:15:00Z"
    resp = client.post(
        "/api/integrations/nutrition?key=test-ingest-secret",
        json={"carbs": 12, "fat": 4, "protein": 5, "fiber": 2, "date": ts},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] == 1


def test_rejects_missing_or_wrong_secret(client: TestClient):
    ts = "2025-03-02T09:15:00Z"
    resp_missing = client.post(
        "/api/integrations/nutrition",
        json={"carbs": 5, "date": ts},
    )
    assert resp_missing.status_code == 401

    resp_wrong = client.post(
        "/api/integrations/nutrition?key=wrong-secret",
        json={"carbs": 5, "date": ts},
    )
    assert resp_wrong.status_code == 401


def test_nutrition_draft_endpoint_removed(client: TestClient):
    resp = client.get("/api/integrations/nutrition/draft")
    assert resp.status_code == 200
    assert '<div id="app"></div>' in resp.text
