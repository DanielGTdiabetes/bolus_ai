
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.core.security import get_current_user, auth_required, CurrentUser
from app.core.db import get_db_session

client = TestClient(app)

def mock_get_current_user():
    return CurrentUser(username="test_user", role="user")

def mock_auth_required():
    return "test_user"

async def mock_get_db_session():
    # Create a mock session that returns an empty list for execute().scalars().all()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result
    yield mock_session

app.dependency_overrides[get_current_user] = mock_get_current_user
app.dependency_overrides[auth_required] = mock_auth_required
app.dependency_overrides[get_db_session] = mock_get_db_session

def test_suggestions_list_fix():
    """Test that suggestions endpoint handles CurrentUser object correctly"""
    response = client.get("/api/suggestions?status=pending")
    # If auth works and db mock works, it should be 200 []
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_basal_timeline():
    """Test basal timeline (uses basal_repo and checkin_date logic)"""
    # Requires basal_repo to use in-memory mode if DB not present.
    # But ensure_basal_schema ran? It needs engine. 
    # If engine is None, ensure_basal_schema returns early.
    response = client.get("/api/basal/timeline?days=14")
    assert response.status_code == 200

def test_basal_entry_manual():
    """Test creating a basal entry manually"""
    response = client.post("/api/basal/entry", json={"dose_u": 10.5})
    assert response.status_code == 200
    data = response.json()
    assert data["dose_u"] == 10.5

def test_basal_checkin_manual():
    """Test creating a manual checkin (no nightscout)"""
    response = client.post("/api/basal/checkin", json={
        "manual_bg": 120,
        "manual_trend": "Flat"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["bg_now_mgdl"] == 120
    assert data["trend"] == "Flat"
