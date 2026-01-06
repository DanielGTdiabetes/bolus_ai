import os
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

from app.models.draft import NutritionDraft
from app.services.nutrition_draft_service import NutritionDraftService, _save_drafts, _load_drafts

@pytest.fixture
def mock_store(tmp_path):
    d_file = tmp_path / "drafts.json"
    with patch("app.services.nutrition_draft_service._get_store_path", return_value=d_file):
        yield d_file

def test_draft_lifecycle(mock_store):
    user = "test_user"
    
    # 1. Create
    draft, action = NutritionDraftService.update_draft(user, 10.0, 5.0, 2.0, 1.0)
    assert action == "created"
    assert draft.carbs == 10.0
    assert draft.fiber == 1.0
    
    # 2. Add Small (Dessert) -> 5g Carbs
    draft, action = NutritionDraftService.update_draft(user, 5.0, 0, 0, 0)
    assert action == "updated_add"
    assert draft.carbs == 15.0 # 10+5
    
    # 3. Cumulative Update (Correction of Total) -> 16g
    # 16 is close to 15 (epsilon 2.0). 
    draft, action = NutritionDraftService.update_draft(user, 16.0, 5.0, 2.0, 1.0)
    assert action == "updated_replace"
    assert draft.carbs == 16.0
    
    # 4. Big Update (New Meal part?) -> 40g
    # 40 > 20 (small threshold) -> Replace
    draft, action = NutritionDraftService.update_draft(user, 40.0, 10.0, 10.0, 5.0)
    assert action == "updated_replace"
    assert draft.carbs == 40.0
    assert draft.fiber == 5.0

    # 5. Close
    t = NutritionDraftService.close_draft_to_treatment(user)
    assert t is not None
    assert t.carbs == 40.0
    assert t.fiber == 5.0
    assert t.notes == "Draft confirmed #draft"
    
    # 6. Ensure cleared
    assert NutritionDraftService.get_draft(user) is None

def test_draft_expiry(mock_store):
    user = "u2"
    with patch.dict(os.environ, {"NUTRITION_DRAFT_WINDOW_MIN": "1"}):
        draft, _ = NutritionDraftService.update_draft(user, 10, 0, 0, 0)
        assert draft is not None
        
        # Manually age it
        draft.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        data = {user: draft.model_dump()}
        _save_drafts(data)
        
        # Fetch should return None
        d2 = NutritionDraftService.get_draft(user)
        assert d2 is None

def test_discard(mock_store):
    user = "u3"
    NutritionDraftService.update_draft(user, 10, 0, 0, 0)
    assert NutritionDraftService.get_draft(user) is not None
    
    NutritionDraftService.discard_draft(user)
    assert NutritionDraftService.get_draft(user) is None
