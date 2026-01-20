import os
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-123456789")

from app.main import app


client = TestClient(app)


def test_capabilities_lists_core_items():
    from app.core.security import get_current_user, CurrentUser
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(username="test", role="admin")
    try:
        response = client.get("/api/bot/capabilities")
    finally:
        app.dependency_overrides = {}
    assert response.status_code == 200
    payload = response.json()

    tools = {item["name"] for item in payload.get("tools", [])}
    assert {"get_status_context", "calculate_bolus", "calculate_correction"}.issubset(tools)

    jobs = {item["id"] for item in payload.get("jobs", [])}
    assert "glucose_monitor" in jobs
