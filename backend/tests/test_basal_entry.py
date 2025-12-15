
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
async def test_create_entry_alias(override_auth):
    """Test POST /entry works as alias for /dose"""
    with patch("app.api.basal.basal_repo.upsert_basal_dose", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = {
            "dose_u": 18.0,
            "effective_from": date.today(),
            "created_at": datetime.utcnow()
        }
        
        payload = {"dose_u": 18.0}
        response = client.post("/api/basal/entry", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["dose_u"] == 18.0
        mock_upsert.assert_called_once()
        
        # Verify passed args
        call_args = mock_upsert.call_args
        assert call_args[0][0] == "testuser"
        assert call_args[0][1] == 18.0

@pytest.mark.asyncio
async def test_create_entry_validation_error(override_auth):
    """Test POST /entry validation fails like /dose"""
    payload = {"dose_u": -5} # Invalid
    response = client.post("/api/basal/entry", json=payload)
    assert response.status_code == 422
