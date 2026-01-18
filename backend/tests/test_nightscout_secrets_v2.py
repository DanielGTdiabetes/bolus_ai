
import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

# Import app to create TestClient
from app.main import app
from app.core.security import get_current_user
from app.core.db import get_db_session
from app.models.nightscout_secrets import NightscoutSecrets
from app.services.nightscout_secrets_service import upsert_ns_config

# Mock User
async def mock_get_current_user():
    return MagicMock(username="test_user", role="user")

# Mock Session
async def mock_get_db_session():
    # Return a dummy object, we will mock the service logic mostly or rely on in-memory DB if configured
    # For unit testing endpoints that rely on service, we can mock the service functions.
    yield MagicMock(spec=AsyncSession)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _override_dependencies():
    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = mock_get_current_user
    try:
        yield
    finally:
        app.dependency_overrides = original_overrides

@pytest.fixture
def mock_ns_service():
    with patch("app.api.nightscout_secrets.get_ns_config") as mock_get, \
         patch("app.api.nightscout_secrets.upsert_ns_config") as mock_upsert, \
         patch("app.api.nightscout_secrets.delete_ns_config") as mock_delete:
        yield mock_get, mock_upsert, mock_delete

def test_get_secret_status_none(mock_ns_service):
    mock_get, _, _ = mock_ns_service
    mock_get.return_value = None # No config
    
    response = client.get("/api/nightscout/secret")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["has_secret"] is False
    assert data["url"] is None

def test_get_secret_status_exists(mock_ns_service):
    mock_get, _, _ = mock_ns_service
    # Mock return object
    config = MagicMock()
    config.enabled = True
    config.url = "https://my-ns.com/"
    config.api_secret = "hidden"
    mock_get.return_value = config
    
    response = client.get("/api/nightscout/secret")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["has_secret"] is True
    assert data["url"] == "https://my-ns.com/"
    # MUST NOT return secret
    assert "api_secret" not in data

def test_put_secret(mock_ns_service):
    _, mock_upsert, _ = mock_ns_service
    
    payload = {
        "url": "https://new.com",
        "api_secret": "my-secret",
        "enabled": True
    }
    
    response = client.put("/api/nightscout/secret", json=payload)
    assert response.status_code == 200
    assert response.json() == {"success": True}
    
    # Verify upsert called
    mock_upsert.assert_awaited_once()
    args = mock_upsert.call_args
    # args[0] is session, args[1] user_id ("test_user"), args[2] url, args[3] secret, args[4] enabled
    assert args[0][1] == "test_user"
    assert args[0][2] == "https://new.com"
    assert args[0][3] == "my-secret"

def test_put_secret_validation_error(mock_ns_service):
    # Missing secret
    payload = {
        "url": "https://new.com",
        "enabled": True
    }
    response = client.put("/api/nightscout/secret", json=payload)
    assert response.status_code == 422 # Pydantic validation error or manual check?
    # Logic manual check returns 400 if fields missing (if model allows optional but logic forbids)
    # The Pydantic model 'SecretPayload' requires api_secret. 
    # So Pydantic returns 422.

# Test integration with nightscout.py status endpoint
@pytest.fixture
def mock_ns_status_deps():
    with patch("app.api.nightscout.get_ns_config") as mock_get_conf:
        yield mock_get_conf

def test_ns_status_endpoint_no_config(mock_ns_status_deps):
    mock_ns_status_deps.return_value = None
    
    response = client.get("/api/nightscout/status")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["ok"] is False

def test_ns_status_endpoint_with_config(mock_ns_status_deps):
    config = MagicMock()
    config.enabled = True
    config.url = "https://mock-ns.com/"
    config.api_secret = "shh"
    mock_ns_status_deps.return_value = config
    
    # We also need to mock NightscoutClient to avoid real network call
    with patch("app.api.nightscout.NightscoutClient") as MockClient:
        instance = MockClient.return_value
        instance.get_status = AsyncMock(return_value={"version": "14.2"})
        instance.aclose = AsyncMock()
        
        response = client.get("/api/nightscout/status")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["ok"] is True
        assert data["url"] == "https://mock-ns.com/"
        
        # Verify secret usage
        MockClient.assert_called_with(base_url="https://mock-ns.com/", token="shh", timeout_seconds=5)


# Test Treatments endpoint
def test_ns_treatments_endpoint_not_configured(mock_ns_status_deps):
    mock_ns_status_deps.return_value = None
    response = client.get("/api/nightscout/treatments")
    assert response.status_code == 200
    assert response.json() == []

def test_ns_treatments_endpoint_configured(mock_ns_status_deps):
    config = MagicMock()
    config.enabled = True
    config.url = "https://mock-ns.com/"
    config.api_secret = "shh"
    mock_ns_status_deps.return_value = config
    
    with patch("app.api.nightscout.NightscoutClient") as MockClient:
        response = client.get("/api/nightscout/treatments?count=5")
        assert response.status_code == 200
        assert response.json() == []  # Empty list mocked
        MockClient.assert_not_called()
