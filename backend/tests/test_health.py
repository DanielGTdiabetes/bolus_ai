from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_full_health_contains_fields(mocker):
    mock_status = {"status": "ok"}
    mocker.patch(
        "app.services.nightscout_client.NightscoutClient.get_status",
        new=AsyncMock(return_value=mock_status),
    )
    response = client.get("/api/health/full")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "uptime_seconds" in body
    assert "version" in body
    assert body["nightscout"]["reachable"] is True
