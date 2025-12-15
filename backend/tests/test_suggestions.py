
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
import uuid

from app.models.suggestion import ParameterSuggestion
from app.services.suggestion_engine import generate_suggestions_service, get_suggestions_service, resolve_suggestion_service

# Patching get_summary_service would be ideal, or just mocking the result if we can't easily patch.
# Since pattern_analysis is imported in suggestion_engine, we should patch where it's used.
# But for simplicity, we know generate_suggestions_service calls it.
# We can mock the DB and rely on get_summary_service being mocked? 
# No, get_summary_service is imported directly. We need to patch it.

from unittest.mock import patch

@pytest.mark.asyncio
async def test_generate_suggestions():
    user_id = "test_user"
    mock_db = AsyncMock()
    
    # 1. Mock Summary
    # We simulate: Breakfast 3h Short > 60% (valid quality)
    summary_data = {
        "by_meal": {
            "breakfast": {
                "3h": {"short": 6, "ok": 2, "over": 0, "missing": 0, "unavailable_iob": 0}
            }
        },
        "days": 30
    }
    
    with patch("app.services.suggestion_engine.get_summary_service", new=AsyncMock(return_value=summary_data)):
        
        # 2. Mock 'existing' check in DB (return None -> not exists)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute.return_value = mock_result
        
        # Run
        res = await generate_suggestions_service(user_id, 30, mock_db)
        
        # Verify
        assert res["created"] == 1
        assert mock_db.add.called
        
        # Inspect what was added
        args, _ = mock_db.add.call_args
        sug = args[0]
        assert isinstance(sug, ParameterSuggestion)
        assert sug.meal_slot == "breakfast"
        assert sug.parameter == "icr"
        assert sug.status == "pending"
        assert "tiendes a quedarte corto" in sug.reason

@pytest.mark.asyncio
async def test_generate_skipped_duplicate():
    user_id = "test_user"
    mock_db = AsyncMock()
    
    summary_data = {
        "by_meal": {
            "breakfast": {
                "3h": {"short": 6, "ok": 2, "over": 0, "missing": 0, "unavailable_iob": 0}
            }
        }
    }
    
    with patch("app.services.suggestion_engine.get_summary_service", new=AsyncMock(return_value=summary_data)):
        # Simulate existing pending
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = ParameterSuggestion(id=uuid.uuid4())
        mock_db.execute.return_value = mock_result
        
        res = await generate_suggestions_service(user_id, 30, mock_db)
        
        assert res["created"] == 0
        assert res["skipped"] == 1
        assert not mock_db.add.called

@pytest.mark.asyncio
async def test_resolve_suggestion():
    mock_db = AsyncMock()
    sug_id = uuid.uuid4()
    user_id = "test_user"
    
    # Mock finding the suggestion
    sug = ParameterSuggestion(id=sug_id, user_id=user_id, status="pending")
    
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = sug
    mock_db.execute.return_value = mock_result
    
    # Accept
    updated = await resolve_suggestion_service(sug_id, user_id, "accept", "Ok", mock_db)
    
    assert updated.status == "accepted"
    assert "Ok" in updated.resolution_note
    assert mock_db.commit.called
