
import pytest
import uuid
from datetime import datetime, date, timedelta
from unittest.mock import AsyncMock, MagicMock
from app.services.notification_service import get_notification_summary_service, mark_seen_service
from app.models.notifications import UserNotificationState
from app.models.suggestion import ParameterSuggestion
from app.models.evaluation import SuggestionEvaluation

@pytest.mark.asyncio
async def test_notifications_unread():
    user_id = str(uuid.uuid4())
    db = AsyncMock()
    
    # Mock States (Initially empty for user)
    # 1. State Fetch
    mr_s = MagicMock()
    mr_s.scalars.return_value.all.return_value = []
    
    # 2. Suggestions (2 pending)
    # Pending 1 very recent
    p1 = ParameterSuggestion(user_id=user_id, status='pending', created_at=datetime.utcnow() - timedelta(hours=1))
    p2 = ParameterSuggestion(user_id=user_id, status='pending', created_at=datetime.utcnow() - timedelta(hours=2))
    
    mr_p = MagicMock()
    mr_p.scalars.return_value.all.return_value = [p1, p2]
    
    # 3. Evaluations (1 ready)
    # Mock last seen for evaluation? If state is empty, no last seen.
    # So any evaluation found is unread.
    e1 = SuggestionEvaluation(created_at=datetime.utcnow())
    mr_e = MagicMock()
    mr_e.scalars.return_value.all.return_value = [e1]
    
    # 4. Basal Advice
    # This involves mocking 'get_advice_service' which is imported inside notification_service.py usually,
    # or passed. But here it's imported directly.
    # We need to mock 'app.services.notification_service.get_advice_service'.
    
    mr_meal = MagicMock()
    mr_meal.scalars.return_value.first.return_value = None

    db.execute.side_effect = [mr_s, mr_p, mr_e, mr_meal]
    
    with pytest.MonkeyPatch.context() as m:
        # Mock basal advice logic
        async def mock_advice(*args):
            return {"message": "Basal OK"}
            
        m.setattr("app.services.notification_service.get_advice_service", mock_advice)
        
        summary = await get_notification_summary_service(user_id, db)
        
    assert summary["has_unread"] is True
    # Items: Suggestion (unread=True), Evaluation (unread=True), Basal (None)
    items = summary["items"]
    assert len(items) == 2
    assert items[0]["type"] == "suggestion_pending"
    assert items[0]["unread"] is True
    
    
@pytest.mark.asyncio
async def test_mark_seen_flow():
    user_id = str(uuid.uuid4())
    db = AsyncMock()
    
    # Step 1: Mark Seen
    # Upsert logic
    mr_ex = MagicMock()
    mr_ex.scalars.return_value.first.return_value = None # No existing state
    
    db.execute.side_effect = [mr_ex, mr_ex] # Called twice for 2 types
    
    await mark_seen_service(["suggestion_pending", "evaluation_ready"], user_id, db)
    
    # Verify add called
    assert db.add.call_count == 2
    assert db.commit.called
    
    # Step 2: Get Summary (Simulated state)
    # State has recent timestamps
    now = datetime.utcnow()
    states = [
        UserNotificationState(key="suggestion_pending", seen_at=now),
        UserNotificationState(key="evaluation_ready", seen_at=now)
    ]
    mr_s2 = MagicMock()
    mr_s2.scalars.return_value.all.return_value = states
    
    # Suggestions (old pending, before now)
    p_old = ParameterSuggestion(user_id=user_id, status='pending', created_at=now - timedelta(hours=1))
    mr_p2 = MagicMock()
    mr_p2.scalars.return_value.all.return_value = [p_old]
    
    # Evaluations (old eval, before now)
    e_old = SuggestionEvaluation(created_at=now - timedelta(hours=1))
    # Query logic filters by > last_seen. 
    # last_seen = now. created_at = now - 1h. 
    # So query returns empty list ideally if DB does filtering.
    # But db.execute is mocked.
    # The service code: q_eval.where(created_at > last_seen).
    # If we return empty list from DB mock, that simulates DB logic.
    mr_e2 = MagicMock()
    mr_e2.scalars.return_value.all.return_value = [] 
    
    mr_meal2 = MagicMock()
    mr_meal2.scalars.return_value.first.return_value = None
    db.execute.side_effect = [mr_s2, mr_p2, mr_e2, mr_meal2]
    
    with pytest.MonkeyPatch.context() as m:
        async def mock_advice(*args):
            return {"message": "Basal OK"}
        m.setattr("app.services.notification_service.get_advice_service", mock_advice)
        
        summary = await get_notification_summary_service(user_id, db)
        
    # Suggestion: exists, but unread = False (because seen_at > created_at)
    # Evaluation: empty list
    # Basal: None
    
    assert summary["has_unread"] is False
    assert len(summary["items"]) == 1 # Only suggestions (read)
    assert summary["items"][0]["unread"] is False
