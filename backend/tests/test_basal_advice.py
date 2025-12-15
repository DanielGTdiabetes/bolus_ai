
import pytest
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock
from app.services.basal_engine import get_advice_service, evaluate_change_service
from app.models.basal import BasalEntry, BasalCheckin, BasalNightSummary

@pytest.mark.asyncio
async def test_basal_advice_night_hypos():
    user_id = str(uuid.uuid4())
    db = AsyncMock()
    
    # Mock Timeline Service returns
    # We mock DB calls inside get_timeline_service
    # But get_advice_service calls get_timeline_service...
    # It's better to integration-test logic or mock db results for get_timeline logic if I test get_advice_service directly.
    # get_advice_service calls get_timeline_service.
    # get_timeline_service calls db.execute(select(BasalCheckin)...) and db.execute(select(BasalNightSummary)...)
    
    # Let's mock the DB calls in get_timeline_service via get_advice_service.
    
    today = date.today()
    
    # Mock Checkins (Empty or irrelevant)
    mock_checkins = []
    
    # Mock Nights (Hypos)
    mock_nights = [
        BasalNightSummary(user_id=user_id, night_date=today, had_hypo=True),
        BasalNightSummary(user_id=user_id, night_date=today-timedelta(1), had_hypo=True)
    ]
    
    # Setup DB Mocks
    # 1. Checkins Query
    mr_c = MagicMock()
    mr_c.scalars.return_value.all.return_value = mock_checkins
    
    # 2. Nights Query
    mr_n = MagicMock()
    mr_n.scalars.return_value.all.return_value = mock_nights
    
    db.execute.side_effect = [mr_c, mr_n]
    
    res = await get_advice_service(user_id, 3, db)
    
    assert "hipoglucemias nocturnas" in res["message"]
    # Confidence: 0 checks, 2 nights -> Checks < 1 -> Low?
    # Logic: if nabs check >= 3 and night >= 2: high. elif >=1 >=1: med. else: low.
    # Checks=0. Night=2. => Low.
    
    # But wait, logic: valid_checks = [i for i in items if i["wake_bg"] is not None]
    # Items generated from range(days).
    # If checkin is missing for day, item["wake_bg"] is None.
    # So confidence is low.
    
    assert res["confidence"] == "low"

@pytest.mark.asyncio
async def test_basal_advice_wake_high():
    user_id = str(uuid.uuid4())
    db = AsyncMock()
    
    today = date.today()
    
    # 3 Days high waking
    mock_checkins = [
        BasalCheckin(user_id=user_id, checkin_date=today, bg_mgdl=150, trend="Flat"),
        BasalCheckin(user_id=user_id, checkin_date=today-timedelta(1), bg_mgdl=140, trend="Flat"),
        BasalCheckin(user_id=user_id, checkin_date=today-timedelta(2), bg_mgdl=160, trend="Flat")
    ]
    
    mock_nights = [
        BasalNightSummary(user_id=user_id, night_date=today, had_hypo=False),
        BasalNightSummary(user_id=user_id, night_date=today-timedelta(1), had_hypo=False)
    ]
    
    mr_c = MagicMock()
    mr_c.scalars.return_value.all.return_value = mock_checkins
    
    mr_n = MagicMock()
    mr_n.scalars.return_value.all.return_value = mock_nights
    
    db.execute.side_effect = [mr_c, mr_n]
    
    res = await get_advice_service(user_id, 3, db)
    
    assert "tendencia al alza" in res["message"]
    # 3 checks, 2 nights -> High confidence
    assert res["confidence"] == "high"
