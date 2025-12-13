from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core import settings as settings_module
from app.models.vision import VisionEstimateResponse, FoodItemEstimate

# We define a fixture for client similar to concurrency, but need re-import to apply settings
# Assuming we can reuse the client fixture structure or just create a new one here or rely on conftest if robust.
# Let's just create a quick fixture here to ensure clean state.

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-vision")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-test-key")
    # Reload main to pick up new routers if needed
    import app.main as main
    from importlib import reload
    reload(main)
    return TestClient(main.app)

def test_vision_unauthorized(client):
    resp = client.post("/api/vision/estimate")
    assert resp.status_code == 401

def test_vision_missing_file(client):
    # Authenticate
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = client.post("/api/vision/estimate", headers=headers)
    # FastAPI usually returns 422 for missing required files/fields
    assert resp.status_code == 422 

def test_vision_success_flow(client):
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Mock OpenAI
    mock_vision_response = VisionEstimateResponse(
        carbs_estimate_g=50,
        carbs_range_g=(45, 55),
        confidence="high",
        items=[FoodItemEstimate(name="Pizza", carbs_g=50)],
        fat_score=0.9,
        slow_absorption_score=0.8,
        assumptions=["Just an assumption"],
        needs_user_input=[],
        glucose_used={"mgdl": 120, "source": "manual"},
        bolus=None # calculated in endpoint
    )

    with patch("app.api.vision.estimate_meal_from_image") as mock_estimate:
        mock_estimate.return_value = mock_vision_response
        
        # Test file upload
        files = {"image": ("pizza.jpg", b"fake-image-bytes", "image/jpeg")}
        data = {
            "bg_mgdl": 120, 
            "meal_slot": "lunch",
            "prefer_extended": True
        }
        
        resp = client.post("/api/vision/estimate", headers=headers, files=files, data=data)
        
        assert resp.status_code == 200, resp.text
        json_resp = resp.json()
        assert json_resp["carbs_estimate_g"] == 50
        assert json_resp["bolus"] is not None
        assert json_resp["bolus"]["kind"] == "extended" # High fat score -> extended
        assert json_resp["bolus"]["delay_min"] >= 30

def test_vision_split_logic():
    # Unit test the split logic function directly
    from app.services.vision import calculate_extended_split
    
    # Normal case
    u, l, d = calculate_extended_split(10.0, 0.1, 0.1, ["rice", "chicken"])
    # Should default to 65% / 35% if prefer_extended was true logic, but here we just test the func. 
    # Actually the function has defaults. 
    # If fat score low, defaults apply: 65/35, 120 min.
    assert u == 6.5
    assert l == 3.5
    assert d == 120
    
    # Pizza (detected by keyword)
    u, l, d = calculate_extended_split(10.0, 0.9, 0.9, ["Pizza Pepperoni"])
    # Pizza logic: 60/40, 150 min
    assert u == 6.0
    assert l == 4.0
    assert d == 150
    
    # Creamy pasta
    u, l, d = calculate_extended_split(10.0, 0.5, 0.5, ["Pasta Carbonara (con nata)"])
    # Creamy logic: 70/30, 105 min
    assert u == 7.0
    assert l == 3.0
    assert d == 105

