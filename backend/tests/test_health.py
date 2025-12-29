from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


from unittest.mock import MagicMock
from app.core.settings import get_settings

def test_full_health_contains_fields(mocker):
    # Override settings to ensure Nightscout is enabled (system-level)
    def mock_settings():
        s = MagicMock()
        s.nightscout.base_url = "https://mock-ns.example.com"
        s.nightscout.token = "foo"
        s.nightscout.api_secret = None
        s.nightscout.timeout_seconds = 10
        s.server.host = "localhost"
        s.server.port = 8000
        return s
    
    app.dependency_overrides[get_settings] = mock_settings

    mock_status = {"status": "ok"}
    # Mocking the client method on the class so instances use it
    mocker.patch(
        "app.services.nightscout_client.NightscoutClient.get_status",
        new=AsyncMock(return_value=mock_status),
    )
    # Also need to mock aclose since we call it
    mocker.patch(
        "app.services.nightscout_client.NightscoutClient.aclose",
        new=AsyncMock(),
    )

    try:
        response = client.get("/api/health/full")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert "uptime_seconds" in body
        assert "version" in body
        assert body["nightscout"]["reachable"] is True
    finally:
        app.dependency_overrides = {}


def test_jobs_health_contains_basal():
    response = client.get("/api/health/jobs")
    assert response.status_code == 200
    body = response.json()
    assert "basal" in body
    basal_state = body["basal"]
    assert "last_run_at" in basal_state
    assert basal_state["last_run_at"] is None or isinstance(basal_state["last_run_at"], str)
