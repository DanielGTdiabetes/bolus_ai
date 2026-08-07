import asyncio
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core import settings as settings_module
from app.core.db import get_db_session
from app.core.security import TokenManager
from app.core.settings import get_settings
from app.models.settings import UserSettingsDB
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
    UserSettingsDB.__table__.create(bind=sync_engine, checkfirst=True)
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


def _auth_headers(client: TestClient, username: str = "admin") -> dict[str, str]:
    token = TokenManager(get_settings()).create_access_token(username)
    return {"Authorization": f"Bearer {token}"}


def _fetch_all_treatments(client: TestClient):
    session_factory = getattr(client, "_session_factory")
    with session_factory() as session:
        result = session.execute(select(Treatment))
        return result.scalars().all()


def _recent_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _create_treatment(client: TestClient, **kwargs) -> Treatment:
    session_factory = getattr(client, "_session_factory")
    treatment = Treatment(**kwargs)
    with session_factory() as session:
        session.add(treatment)
        session.commit()
    return treatment


def _delete_treatment(client: TestClient, treatment_id: str) -> None:
    session_factory = getattr(client, "_session_factory")
    with session_factory() as session:
        treatment = session.get(Treatment, treatment_id)
        if treatment:
            session.delete(treatment)
            session.commit()


def _health_connect_meal_payload(timestamp: str, fingerprint: str = "shared-meal") -> dict:
    return {
        "data": {
            "metrics": [
                {
                    "name": "carbohydrates",
                    "data": [
                        {
                            "qty": 30,
                            "date": timestamp,
                            "source": "MyFitnessPal",
                            "meal_fingerprint": fingerprint,
                        }
                    ],
                },
                {
                    "name": "total_fat",
                    "data": [
                        {
                            "qty": 4,
                            "date": timestamp,
                            "source": "MyFitnessPal",
                            "meal_fingerprint": fingerprint,
                        }
                    ],
                },
                {
                    "name": "protein",
                    "data": [
                        {
                            "qty": 5,
                            "date": timestamp,
                            "source": "MyFitnessPal",
                            "meal_fingerprint": fingerprint,
                        }
                    ],
                },
            ]
        }
    }


def test_mobile_bolus_settings_requires_ingest_key(client: TestClient):
    resp = client.get("/api/integrations/mobile/bolus-settings")

    assert resp.status_code == 401


def test_mobile_bolus_settings_returns_safe_calculation_profile(client: TestClient):
    session_factory = getattr(client, "_session_factory")
    with session_factory() as session:
        session.add(
            UserSettingsDB(
                user_id="admin",
                settings={
                    "targets": {"mid": 105, "lunch": 110},
                    "cr": {"breakfast": 12, "lunch": 9, "dinner": 10, "snack": 15},
                    "cf": {"breakfast": 45, "lunch": 40, "dinner": 42, "snack": 50},
                    "iob": {"dia_hours": 4.5, "curve": "walsh", "peak_minutes": 75},
                    "calculator": {"subtract_fiber": True, "fiber_factor": 0.5, "fiber_threshold_g": 5},
                    "round_step_u": 0.5,
                    "max_bolus_u": 8,
                    "max_correction_u": 3,
                    "nightscout": {"token": "must-not-leak", "url": "https://example.invalid"},
                },
                version=1,
            )
        )
        session.commit()

    resp = client.get("/api/integrations/mobile/bolus-settings", headers={"X-Ingest-Key": "test-ingest-secret"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "admin"
    assert body["cr"]["lunch"] == 9
    assert body["cf"]["lunch"] == 40
    assert body["targets"]["lunch"] == 110
    assert body["iob"]["dia_hours"] == 4.5
    assert "nightscout" not in body
    assert "must-not-leak" not in resp.text


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


def test_enrichment_updates_existing_meal(client: TestClient):
    headers = _auth_headers(client)
    ts = "2026-01-19 14:33:00 +0100"

    resp_first = client.post(
        "/api/integrations/nutrition",
        headers=headers,
        json={"carbs": 20, "date": ts},
    )
    assert resp_first.status_code == 200
    assert resp_first.json()["ingested_count"] == 1

    resp_second = client.post(
        "/api/integrations/nutrition",
        headers=headers,
        json={"carbs": 20, "fat": 8, "protein": 12, "fiber": 4, "date": ts},
    )
    assert resp_second.status_code == 200
    assert resp_second.json()["ingested_count"] == 0

    treatments = _fetch_all_treatments(client)
    assert len(treatments) == 1
    saved = treatments[0]
    assert saved.fat == pytest.approx(8.0)
    assert saved.protein == pytest.approx(12.0)
    assert saved.fiber == pytest.approx(4.0)


def test_edit_updates_existing_meal(client: TestClient):
    headers = _auth_headers(client)
    ts = "2026-01-19 19:27:00 +0100"

    resp_first = client.post(
        "/api/integrations/nutrition",
        headers=headers,
        json={"carbs": 12, "date": ts},
    )
    assert resp_first.status_code == 200
    assert resp_first.json()["ingested_count"] == 1

    resp_second = client.post(
        "/api/integrations/nutrition",
        headers=headers,
        json={"carbs": 18, "date": ts},
    )
    assert resp_second.status_code == 200
    assert resp_second.json()["ingested_count"] == 0

    treatments = _fetch_all_treatments(client)
    assert len(treatments) == 1
    assert treatments[0].carbs == pytest.approx(18.0)


def test_strict_lookup_is_scoped_to_authenticated_user(client: TestClient):
    timestamp = _recent_timestamp()
    fingerprint = "shared-fingerprint"
    import_signature = f"Imported from Health: {fingerprint} #imported"
    _create_treatment(
        client,
        id="other-user-meal",
        user_id="other-user",
        event_type="Meal Bolus",
        created_at=datetime.fromisoformat(timestamp).replace(tzinfo=None),
        insulin=0.0,
        carbs=10.0,
        fat=0.0,
        protein=0.0,
        fiber=0.0,
        notes=import_signature,
        entered_by="webhook-integration",
        is_uploaded=False,
    )
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "carbohydrates",
                    "data": [
                        {
                            "qty": 30.0,
                            "date": timestamp,
                            "source": "MyFitnessPal",
                            "meal_fingerprint": fingerprint,
                            "meal_type": "3",
                        }
                    ],
                }
            ]
        }
    }

    response = client.post(
        "/api/integrations/nutrition",
        headers=_auth_headers(client, "target-user"),
        json=payload,
    )

    assert response.status_code == 200
    assert response.json()["ingested_count"] == 1
    treatments = _fetch_all_treatments(client)
    assert len(treatments) == 2
    treatments_by_user = {treatment.user_id: treatment for treatment in treatments}
    assert treatments_by_user["other-user"].carbs == pytest.approx(10.0)
    assert treatments_by_user["other-user"].notes == import_signature
    assert treatments_by_user["target-user"].carbs == pytest.approx(30.0)
    assert treatments_by_user["target-user"].notes == import_signature


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


def test_health_connect_daily_dump_only_imports_latest_mfp_meal(client: TestClient):
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "carbohydrates",
                    "data": [
                        {
                            "qty": 8.6,
                            "date": "2026-06-23 10:00:00 +0200",
                            "source": "MyFitnessPal",
                            "meal_fingerprint": "mfp-breakfast",
                            "meal_type": "1",
                        },
                        {
                            "qty": 26.1,
                            "date": "2026-06-23 10:00:00 +0200",
                            "source": "MyFitnessPal",
                            "meal_fingerprint": "mfp-lunch",
                            "meal_type": "2",
                        },
                        {
                            "qty": 27.2,
                            "date": "2026-06-23 10:00:00 +0200",
                            "source": "MyFitnessPal",
                            "meal_fingerprint": "mfp-dinner",
                            "meal_type": "3",
                        },
                    ],
                },
                {
                    "name": "total_fat",
                    "data": [
                        {
                            "qty": 24.7,
                            "date": "2026-06-23 10:00:00 +0200",
                            "source": "MyFitnessPal",
                            "meal_fingerprint": "mfp-breakfast",
                            "meal_type": "1",
                        },
                        {
                            "qty": 27.1,
                            "date": "2026-06-23 10:00:00 +0200",
                            "source": "MyFitnessPal",
                            "meal_fingerprint": "mfp-lunch",
                            "meal_type": "2",
                        },
                        {
                            "qty": 24.7,
                            "date": "2026-06-23 10:00:00 +0200",
                            "source": "MyFitnessPal",
                            "meal_fingerprint": "mfp-dinner",
                            "meal_type": "3",
                        },
                    ],
                },
                {
                    "name": "protein",
                    "data": [
                        {
                            "qty": 30.5,
                            "date": "2026-06-23 10:00:00 +0200",
                            "source": "MyFitnessPal",
                            "meal_fingerprint": "mfp-breakfast",
                            "meal_type": "1",
                        },
                        {
                            "qty": 26.9,
                            "date": "2026-06-23 10:00:00 +0200",
                            "source": "MyFitnessPal",
                            "meal_fingerprint": "mfp-lunch",
                            "meal_type": "2",
                        },
                        {
                            "qty": 73.2,
                            "date": "2026-06-23 10:00:00 +0200",
                            "source": "MyFitnessPal",
                            "meal_fingerprint": "mfp-dinner",
                            "meal_type": "3",
                        },
                    ],
                },
            ]
        }
    }

    resp = client.post("/api/integrations/nutrition?key=test-ingest-secret", json=payload)

    assert resp.status_code == 200
    assert resp.json()["ingested_count"] == 1
    treatments = _fetch_all_treatments(client)
    assert len(treatments) == 1
    assert treatments[0].carbs == pytest.approx(27.2)
    assert treatments[0].protein == pytest.approx(73.2)


def test_health_connect_daily_dump_dedupes_against_recent_hermes_meal(client: TestClient):
    existing_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    _create_treatment(
        client,
        id="hermes-dinner",
        user_id="admin",
        event_type="Meal Bolus",
        created_at=existing_time,
        insulin=0.0,
        carbs=28.0,
        fat=25.0,
        protein=73.0,
        fiber=0.0,
        notes="Imported from Health: hermes-mfp:2026-06-23:dinner:test #imported",
        entered_by="webhook-integration",
        is_uploaded=False,
    )
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "carbohydrates",
                    "data": [
                        {"qty": 8.6, "date": "2026-06-23 10:00:00 +0200", "source": "MyFitnessPal", "meal_fingerprint": "mfp-breakfast", "meal_type": "1"},
                        {"qty": 68.8, "date": "2026-06-23 10:00:00 +0200", "source": "MyFitnessPal", "meal_fingerprint": "mfp-lunch", "meal_type": "2"},
                        {"qty": 27.2, "date": "2026-06-23 10:00:00 +0200", "source": "MyFitnessPal", "meal_fingerprint": "mfp-dinner", "meal_type": "3"},
                    ],
                },
                {
                    "name": "total_fat",
                    "data": [
                        {"qty": 24.7, "date": "2026-06-23 10:00:00 +0200", "source": "MyFitnessPal", "meal_fingerprint": "mfp-breakfast", "meal_type": "1"},
                        {"qty": 46.6, "date": "2026-06-23 10:00:00 +0200", "source": "MyFitnessPal", "meal_fingerprint": "mfp-lunch", "meal_type": "2"},
                        {"qty": 24.7, "date": "2026-06-23 10:00:00 +0200", "source": "MyFitnessPal", "meal_fingerprint": "mfp-dinner", "meal_type": "3"},
                    ],
                },
                {
                    "name": "protein",
                    "data": [
                        {"qty": 30.5, "date": "2026-06-23 10:00:00 +0200", "source": "MyFitnessPal", "meal_fingerprint": "mfp-breakfast", "meal_type": "1"},
                        {"qty": 63.7, "date": "2026-06-23 10:00:00 +0200", "source": "MyFitnessPal", "meal_fingerprint": "mfp-lunch", "meal_type": "2"},
                        {"qty": 73.2, "date": "2026-06-23 10:00:00 +0200", "source": "MyFitnessPal", "meal_fingerprint": "mfp-dinner", "meal_type": "3"},
                    ],
                },
            ]
        }
    }

    resp = client.post("/api/integrations/nutrition?key=test-ingest-secret", json=payload)

    assert resp.status_code == 200
    assert resp.json()["ingested_count"] == 0
    treatments = _fetch_all_treatments(client)
    assert len(treatments) == 1
    assert treatments[0].id == "hermes-dinner"


def test_nutrition_shadow_mode_off_does_not_run_or_log_matcher(
    client: TestClient, monkeypatch, caplog
):
    monkeypatch.setenv("NUTRITION_DEDUPE_MODE", "off")
    timestamp = _recent_timestamp()
    fingerprint = "shadow-off-meal"
    _create_treatment(
        client,
        id="shadow-off-candidate",
        user_id="admin",
        event_type="Meal Bolus",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2),
        insulin=0.0,
        carbs=30.0,
        fat=10.0,
        protein=10.0,
        fiber=0.0,
        notes="Hermes Imported from Health: different-existing-meal #imported",
        entered_by="webhook-integration",
        is_uploaded=False,
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("shadow matcher must not run while mode is off")

    monkeypatch.setattr("app.api.integrations.classify_nutrition_candidate", fail_if_called)
    caplog.set_level("INFO", logger="app.api.integrations")

    response = client.post(
        "/api/integrations/nutrition?key=test-ingest-secret",
        json=_health_connect_meal_payload(timestamp, fingerprint),
    )

    assert response.status_code == 200
    assert response.json()["ingested_count"] == 1
    assert "nutrition_dedup_shadow" not in caplog.text
    assert len(_fetch_all_treatments(client)) == 2


def test_nutrition_shadow_mode_logs_but_does_not_suppress_meal(
    client: TestClient, monkeypatch, caplog
):
    monkeypatch.setenv("NUTRITION_DEDUPE_MODE", "shadow")
    timestamp = _recent_timestamp()
    fingerprint = "shadow-probable-meal"
    _create_treatment(
        client,
        id="shadow-probable-candidate",
        user_id="admin",
        event_type="Meal Bolus",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2),
        insulin=0.0,
        carbs=30.0,
        fat=10.0,
        protein=10.0,
        fiber=0.0,
        notes="Hermes Imported from Health: different-existing-meal #imported",
        entered_by="webhook-integration",
        is_uploaded=False,
    )
    caplog.set_level("INFO", logger="app.api.integrations")

    response = client.post(
        "/api/integrations/nutrition?key=test-ingest-secret",
        json=_health_connect_meal_payload(timestamp, fingerprint),
    )

    assert response.status_code == 200
    assert response.json()["ingested_count"] == 1
    assert "nutrition_dedup_shadow" in caplog.text
    assert "classification=ambiguous" in caplog.text
    assert len(_fetch_all_treatments(client)) == 2


def test_rejects_missing_or_wrong_secret(client: TestClient):
    ts = "2025-03-02T09:15:00Z"
    resp_missing = client.post(
        "/api/integrations/nutrition",
        json={"carbs": 5, "date": ts},
    )
    assert resp_missing.status_code == 401


def test_recent_imports_sorted_and_limited(client: TestClient):
    headers = _auth_headers(client)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    _create_treatment(
        client,
        id="import-1",
        user_id="admin",
        event_type="Meal Bolus",
        created_at=now - timedelta(minutes=30),
        insulin=0.0,
        carbs=25.0,
        fat=5.0,
        protein=6.0,
        fiber=3.0,
        notes="Imported from Health: test #imported",
        entered_by="webhook-integration",
        is_uploaded=False,
    )
    _create_treatment(
        client,
        id="import-2",
        user_id="admin",
        event_type="Meal Bolus",
        created_at=now - timedelta(minutes=10),
        insulin=0.0,
        carbs=40.0,
        fat=8.0,
        protein=9.0,
        fiber=4.0,
        notes="Imported from Health: test #imported",
        entered_by="webhook-integration",
        is_uploaded=False,
    )
    _create_treatment(
        client,
        id="import-3",
        user_id="admin",
        event_type="Meal Bolus",
        created_at=now - timedelta(minutes=5),
        insulin=0.0,
        carbs=10.0,
        fat=2.0,
        protein=3.0,
        fiber=1.0,
        notes="Imported from Health: test #imported",
        entered_by="webhook-integration",
        is_uploaded=False,
    )

    resp = client.get("/api/integrations/nutrition/recent?limit=2", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 2
    assert payload[0]["id"] == "import-3"
    assert payload[1]["id"] == "import-2"
    assert payload[0]["timestamp"] > payload[1]["timestamp"]
    assert payload[1]["timestamp"] > (now - timedelta(minutes=30)).isoformat()


def test_recent_imports_excludes_consumed_entries(client: TestClient):
    headers = _auth_headers(client)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    _create_treatment(
        client,
        id="import-pending",
        user_id="admin",
        event_type="Meal Bolus",
        created_at=now - timedelta(minutes=15),
        insulin=0.0,
        carbs=30.0,
        fat=4.0,
        protein=5.0,
        fiber=2.0,
        notes="Imported from Health: pending #imported",
        entered_by="webhook-integration",
        is_uploaded=False,
    )
    _create_treatment(
        client,
        id="import-consumed",
        user_id="admin",
        event_type="Meal Bolus",
        created_at=now - timedelta(minutes=5),
        insulin=2.0,
        carbs=30.0,
        fat=4.0,
        protein=5.0,
        fiber=2.0,
        notes="Imported from Health: consumed #imported",
        entered_by="webhook-integration",
        is_uploaded=False,
    )

    resp = client.get("/api/integrations/nutrition/recent", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    ids = {item["id"] for item in payload}
    assert "import-pending" in ids
    assert "import-consumed" not in ids


def test_recent_imports_drop_after_delete(client: TestClient):
    headers = _auth_headers(client)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    _create_treatment(
        client,
        id="import-delete-me",
        user_id="admin",
        event_type="Meal Bolus",
        created_at=now - timedelta(minutes=2),
        insulin=0.0,
        carbs=22.0,
        fat=4.0,
        protein=6.0,
        fiber=2.0,
        notes="Imported from Health: delete test #imported",
        entered_by="webhook-integration",
        is_uploaded=False,
    )

    resp = client.get("/api/integrations/nutrition/recent", headers=headers)
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()}
    assert "import-delete-me" in ids

    _delete_treatment(client, "import-delete-me")

    resp_after = client.get("/api/integrations/nutrition/recent", headers=headers)
    assert resp_after.status_code == 200
    ids_after = {item["id"] for item in resp_after.json()}
    assert "import-delete-me" not in ids_after


def test_nutrition_draft_endpoint_removed(client: TestClient):
    resp = client.get("/api/integrations/nutrition/draft")
    assert resp.status_code == 200
    assert '<div id="app"></div>' in resp.text
