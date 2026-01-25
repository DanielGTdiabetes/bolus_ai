import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-restaurant")

    from app.core.settings import get_settings
    get_settings.cache_clear()

    from app.main import app
    from app.core.security import get_current_user, CurrentUser

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(username="test", role="admin")

    from app.core.datastore import UserStore
    UserStore(tmp_path / "users.json").ensure_seed_admin()

    yield TestClient(app)

    app.dependency_overrides = {}
    get_settings.cache_clear()


def test_restaurant_compare_guardrails_success(client):
    resp = client.post(
        "/api/restaurant/compare_plate",
        data={"expectedCarbs": 60, "actualCarbs": 80, "confidence": 0.6},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["expectedCarbs"] == 60
    assert payload["actualCarbs"] == 80
    assert "deltaCarbs" in payload


def test_restaurant_compare_requires_image_or_actual(client):
    resp = client.post("/api/restaurant/compare_plate", data={"expectedCarbs": 60})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "image_or_actual_required"
