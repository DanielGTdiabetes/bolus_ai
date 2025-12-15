
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from datetime import date, datetime, timedelta

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
async def test_latest_endpoint_empty(override_auth):
    """Test GET /api/basal/latest returns {'dose_u': null} when empty"""
    with patch("app.api.basal.basal_repo.get_latest_basal_dose", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        
        response = client.get("/api/basal/latest")
        assert response.status_code == 200
        data = response.json()
        assert data["dose_u"] is None

@pytest.mark.asyncio
async def test_latest_endpoint_with_data(override_auth):
    """Test GET /api/basal/latest returns data"""
    with patch("app.api.basal.basal_repo.get_latest_basal_dose", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "dose_u": 18.0,
            "effective_from": date.today(),
            "created_at": datetime.utcnow()
        }
        
        response = client.get("/api/basal/latest")
        assert response.status_code == 200
        data = response.json()
        assert data["dose_u"] == 18.0
        assert "effective_from" in data
        assert "created_at" in data

@pytest.mark.asyncio
async def test_history_endpoint(override_auth):
    """Test GET /api/basal/history returns items"""
    with patch("app.api.basal.basal_repo.get_dose_history", new_callable=AsyncMock) as mock_hist:
        mock_hist.return_value = [
            {"dose_u": 16.0, "effective_from": date(2025, 12, 1), "created_at": datetime(2025, 12, 1, 10, 0)},
            {"dose_u": 18.0, "effective_from": date(2025, 12, 15), "created_at": datetime(2025, 12, 15, 10, 0)}
        ]
        
        response = client.get("/api/basal/history?days=30")
        assert response.status_code == 200
        data = response.json()
        assert data["days"] == 30
        assert len(data["items"]) == 2
        assert data["items"][0]["dose_u"] == 16.0
        assert data["items"][1]["dose_u"] == 18.0

@pytest.mark.asyncio
async def test_create_dose_with_alias(override_auth):
    """Test POST /api/basal/dose accepts dose_units alias"""
    with patch("app.api.basal.basal_repo.upsert_basal_dose", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = {
            "dose_u": 20.0,
            "effective_from": date.today(),
            "created_at": datetime.utcnow()
        }
        
        # Payload with dose_units instead of dose_u
        payload = {"dose_units": 20.0, "effective_from": str(date.today())}
        
        response = client.post("/api/basal/dose", json=payload)
        
        assert response.status_code == 200
        # Backend should have mapped it and returned the saved dose
        assert response.json()["dose_u"] == 20.0
        
        # Verify repo was called with mapped value
        call_args = mock_upsert.call_args
        assert call_args[0][1] == 20.0
