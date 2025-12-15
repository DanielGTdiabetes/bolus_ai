
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta
import uuid

from app.models.suggestion import ParameterSuggestion
from app.models.evaluation import SuggestionEvaluation
from app.models.analysis import BolusPostAnalysis
from app.services.evaluation_engine import evaluate_suggestion_service

@pytest.mark.asyncio
async def test_evaluate_suggestion_improved():
    db = AsyncMock()
    user_id = str(uuid.uuid4())
    mid = datetime.now() 
    sug_id = uuid.uuid4()
    
    # 1. Mock Suggestion Query
    # First query gets Suggestion
    sug = ParameterSuggestion(
        id=sug_id,
        user_id=user_id,
        meal_slot="breakfast",
        evidence={"window": "3h", "counts": {"short": 10}},
        status="accepted",
        resolved_at=mid
    )
    
    # 2. Mock Analysis Query
    # We need to simulate rows returned by the second query
    # Before rows: Bad (Short)
    before_rows = [
        BolusPostAnalysis(bolus_at=mid - timedelta(days=1), result="short", iob_status="ok"),
        BolusPostAnalysis(bolus_at=mid - timedelta(days=2), result="short", iob_status="ok"),
        BolusPostAnalysis(bolus_at=mid - timedelta(days=3), result="short", iob_status="ok"),
        BolusPostAnalysis(bolus_at=mid - timedelta(days=4), result="short", iob_status="ok"),
        BolusPostAnalysis(bolus_at=mid - timedelta(days=5), result="ok", iob_status="ok"),
    ]
    # Score Before: 4/5 = 0.8
    
    # After rows: Good (Ok)
    after_rows = [
        BolusPostAnalysis(bolus_at=mid + timedelta(days=1), result="ok", iob_status="ok"),
        BolusPostAnalysis(bolus_at=mid + timedelta(days=2), result="ok", iob_status="ok"),
        BolusPostAnalysis(bolus_at=mid + timedelta(days=3), result="ok", iob_status="ok"),
        BolusPostAnalysis(bolus_at=mid + timedelta(days=4), result="ok", iob_status="ok"),
        BolusPostAnalysis(bolus_at=mid + timedelta(days=5), result="short", iob_status="ok"),
    ]
    # Score After: 1/5 = 0.2
    
    # Setup Mock Returns
    # db.execute is called 3 times: 
    # 1. Get Suggestion
    # 2. Get Analysis Rows
    # 3. Get Existing Evaluation (return None)
    
    mock_res_sug = MagicMock()
    mock_res_sug.scalars.return_value.first.return_value = sug
    
    mock_res_rows = MagicMock()
    mock_res_rows.scalars.return_value.all.return_value = before_rows + after_rows
    
    mock_res_eval = MagicMock()
    mock_res_eval.scalars.return_value.first.return_value = None
    
    db.execute.side_effect = [mock_res_sug, mock_res_rows, mock_res_eval]
    
    # Run
    res = await evaluate_suggestion_service(str(sug_id), user_id, 7, db)
    
    # Verify
    assert res.result == "improved"
    # Verify we added the evaluation
    assert db.add.called
    args, _ = db.add.call_args
    eval_obj = args[0]
    assert isinstance(eval_obj, SuggestionEvaluation)
    assert eval_obj.status == "evaluated"
    assert eval_obj.evidence["before"]["score"] == 0.8
    assert eval_obj.evidence["after"]["score"] == 0.2

@pytest.mark.asyncio
async def test_evaluate_insufficient():
    db = AsyncMock()
    user_id = str(uuid.uuid4())
    mid = datetime.now()
    sug_id = uuid.uuid4()
    
    sug = ParameterSuggestion(
        id=sug_id,
        user_id=user_id,
        meal_slot="lunch",
        evidence={"window": "3h"},
        status="accepted",
        resolved_at=mid
    )
    
    # Only 2 rows
    rows = [
        BolusPostAnalysis(bolus_at=mid - timedelta(days=1), result="short", iob_status="ok"),
        BolusPostAnalysis(bolus_at=mid + timedelta(days=1), result="ok", iob_status="ok"),
    ]
    
    mock_res_sug = MagicMock()
    mock_res_sug.scalars.return_value.first.return_value = sug
    
    mock_res_rows = MagicMock()
    mock_res_rows.scalars.return_value.all.return_value = rows
    
    mock_res_eval = MagicMock()
    mock_res_eval.scalars.return_value.first.return_value = None
    
    db.execute.side_effect = [mock_res_sug, mock_res_rows, mock_res_eval]
    
    res = await evaluate_suggestion_service(str(sug_id), user_id, 7, db)
    
    assert res.result == "insufficient"

