
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from datetime import date, datetime

from app.main import app
from app.core.security import auth_required

client = TestClient(app)

# Helper to bypass auth
def mock_auth_required():
    return "testuser"

@pytest.fixture
def override_auth():
    app.dependency_overrides[auth_required] = mock_auth_required
    yield
    app.dependency_overrides = {}

@pytest.mark.asyncio
async def test_log_dose_with_dose_to_u(override_auth):
    """Test POST /dose with standard dose_u param"""
    with patch("app.api.basal.basal_repo.upsert_basal_dose", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = {
            "dose_u": 18.0,
            "effective_from": date.today(),
            "created_at": datetime.utcnow()
        }
        
        payload = {"dose_u": 18.0}
        response = client.post("/api/basal/dose", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["dose_u"] == 18.0
        mock_upsert.assert_called_once()
        # Verify passed args
        call_args = mock_upsert.call_args
        assert call_args[0][0] == "testuser"
        assert call_args[0][1] == 18.0

@pytest.mark.asyncio
async def test_log_dose_with_dose_units_alias(override_auth):
    """Test POST /dose with dose_units alias"""
    with patch("app.api.basal.basal_repo.upsert_basal_dose", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = {
            "dose_u": 15.5,
            "effective_from": date.today(),
            "created_at": datetime.utcnow()
        }
        
        # Payload using alias
        payload = {"dose_units": 15.5}
        response = client.post("/api/basal/dose", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["dose_u"] == 15.5
        
        # Verify repo called with aliased value
        call_args = mock_upsert.call_args
        assert call_args[0][1] == 15.5

@pytest.mark.asyncio
async def test_get_latest_dose(override_auth):
    """Test GET /latest"""
    with patch("app.api.basal.basal_repo.get_latest_basal_dose", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "dose_u": 20.0,
            "effective_from": date(2025, 12, 1),
            "created_at": datetime(2025, 12, 1, 10, 0, 0)
        }
        
        response = client.get("/api/basal/latest")
        assert response.status_code == 200
        data = response.json()
        # Use float comparison approx if needed, but exact matches fine for simple floats
        assert data["dose_u"] == 20.0
        assert data["effective_from"] == "2025-12-01"

@pytest.mark.asyncio
async def test_get_latest_dose_empty(override_auth):
    """Test GET /latest when no data exists"""
    with patch("app.api.basal.basal_repo.get_latest_basal_dose", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        
        response = client.get("/api/basal/latest")
        assert response.status_code == 200
        assert response.json() == {
            "dose_u": None,
            "effective_from": None,
            "created_at": None,
        }

@pytest.mark.asyncio
async def test_get_history(override_auth):
    """Test GET /history"""
    with patch("app.api.basal.basal_repo.get_dose_history", new_callable=AsyncMock) as mock_hist:
        mock_hist.return_value = [
            {"dose_u": 10.0, "effective_from": date(2025, 11, 1), "created_at": datetime.utcnow()},
            {"dose_u": 12.0, "effective_from": date(2025, 12, 1), "created_at": datetime.utcnow()}
        ]
        
        response = client.get("/api/basal/history?days=60")
        assert response.status_code == 200
        data = response.json()
        assert data["days"] == 60
        assert len(data["items"]) == 2
        assert data["items"][0]["dose_u"] == 10.0
        assert data["items"][1]["dose_u"] == 12.0
