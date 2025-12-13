import json
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.storage import load_settings

client = TestClient(app)

def test_login_and_settings_access():
    # ensure default admin exists
    response = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    access = response.json()["access_token"]

    # unauthorized
    resp = client.get("/api/settings")
    assert resp.status_code == 401

    # authorized
    resp2 = client.get("/api/settings", headers={"Authorization": f"Bearer {access}"})
    assert resp2.status_code == 200
    data = resp2.json()
    assert "settings" in data
