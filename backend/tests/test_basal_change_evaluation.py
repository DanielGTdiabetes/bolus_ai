
import pytest
import uuid
from datetime import datetime, date, timedelta
from unittest.mock import AsyncMock, MagicMock
from app.services.basal_engine import evaluate_change_service
from app.models.basal import BasalEntry, BasalCheckin, BasalNightSummary

@pytest.mark.asyncio
async def test_evaluate_change_improved():
    user_id = str(uuid.uuid4())
    db = AsyncMock()
    
    # Mock Entries (Change from 10 to 12 u)
    change_dt = datetime.utcnow() - timedelta(days=8)
    e_new = BasalEntry(units=12.0, created_at=change_dt)
    e_old = BasalEntry(units=10.0, created_at=change_dt - timedelta(days=30))
    
    # Mock Data
    # Before: Bad (High and instable)
    # After: Good (Stable)
    
    # DB calls:
    # 1. Entries (limit 2)
    # 2. Before Stats (Checkins)
    # 3. Before Stats (Nights)
    # 4. After Stats (Checkins)
    # 5. After Stats (Nights)
    # 6. Add Eval
    
    mr_e = MagicMock()
    mr_e.scalars.return_value.all.return_value = [e_new, e_old]
    
    # Before Checkins (High)
    c_before = [BasalCheckin(bg_mgdl=180) for _ in range(5)]
    mr_cb = MagicMock()
    mr_cb.scalars.return_value.all.return_value = c_before
    
    # Before Nights (1 hypo)
    n_before = [BasalNightSummary(had_hypo=True)]
    mr_nb = MagicMock()
    mr_nb.scalars.return_value.all.return_value = n_before
    
    # After Checkins (Perfect)
    c_after = [BasalCheckin(bg_mgdl=110) for _ in range(5)]
    mr_ca = MagicMock()
    mr_ca.scalars.return_value.all.return_value = c_after
    
    # After Nights (0 hypos)
    n_after = []
    mr_na = MagicMock()
    mr_na.scalars.return_value.all.return_value = n_after
    
    db.execute.side_effect = [mr_e, mr_cb, mr_nb, mr_ca, mr_na]
    
    res = await evaluate_change_service(user_id, 7, db)
    
    # Before Score: %over=1.0, %under=0. Hypos=1 (<2, flag=0). Score=1.0
    # After Score: %over=0, %under=0. Hypos=0. Score=0.0
    # Diff = 1.0 (Improved)
    
    assert res["result"] == "improved"
    assert "Mejoró" in res["summary"]

@pytest.mark.asyncio
async def test_evaluate_change_worse_hypos():
    user_id = str(uuid.uuid4())
    db = AsyncMock()
    
    change_dt = datetime.utcnow() - timedelta(days=8)
    e_new = BasalEntry(units=15.0, created_at=change_dt) # Increased dose too much
    e_old = BasalEntry(units=12.0, created_at=change_dt - timedelta(days=30))
    
    mr_e = MagicMock()
    mr_e.scalars.return_value.all.return_value = [e_new, e_old]
    
    # Before: 110 avg, no hypos
    c_before = [BasalCheckin(bg_mgdl=110) for _ in range(5)]
    mr_cb = MagicMock()
    mr_cb.scalars.return_value.all.return_value = c_before
    n_before = []
    mr_nb = MagicMock()
    mr_nb.scalars.return_value.all.return_value = n_before
    
    # After: 90 avg, BUT 3 nights hypos
    c_after = [BasalCheckin(bg_mgdl=90) for _ in range(5)]
    mr_ca = MagicMock()
    mr_ca.scalars.return_value.all.return_value = c_after
    n_after = [BasalNightSummary(had_hypo=True) for _ in range(3)]
    mr_na = MagicMock()
    mr_na.scalars.return_value.all.return_value = n_after
    
    db.execute.side_effect = [mr_e, mr_cb, mr_nb, mr_ca, mr_na]
    
    res = await evaluate_change_service(user_id, 7, db)
    
    # Before Score: 0 (Good)
    # After Score: %under (maybe 90 is under? <100). 5/5 = 1.0. Hypos=3 (flag=1). Score=2.0.
    # Worse.
    
    assert res["result"] == "worse"
    assert "Empeoró" in res["summary"]
