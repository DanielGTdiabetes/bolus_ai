
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone

from app.services.pattern_analysis import run_analysis_service, get_summary_service
from app.models.analysis import BolusPostAnalysis
from app.models.settings import UserSettings

@pytest.mark.asyncio
async def test_bolus_patterns_empty():
    # Mock dependencies
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    
    mock_ns = AsyncMock()
    mock_ns.get_recent_treatments.return_value = []
    
    settings = UserSettings() # default
    
    result = await run_analysis_service("test_user", 30, settings, mock_ns, mock_db)
    
    assert result["boluses"] == 0
    assert result["windows_written"] == 0

@pytest.mark.asyncio
async def test_bolus_patterns_synthetic():
    # 5 breakfasts, result short (BG > target+30)
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)
    
    # Mock treatments
    now = datetime.utcnow()
    # Create 5 boluses at 8:00 AM (Breakfast)
    treatments = []
    for i in range(5):
        t = MagicMock()
        t.insulin = 5.0
        t.carbs = 50
        # date: 1 day ago, 2 days ago... at 8 AM
        d = now - timedelta(days=i+1)
        d = d.replace(hour=8, minute=0)
        t.created_at = d
        treatments.append(t)
        
    mock_ns = AsyncMock()
    mock_ns.get_recent_treatments.return_value = treatments
    
    # Mock SGVs to always be High (150 > 100+30)
    async def side_effect_sgv(start, end, count=20):
        sgv = MagicMock()
        sgv.sgv = 150 
        # Make sure date is inside
        mid = start + (end - start) / 2
        sgv.date = int(mid.timestamp() * 1000)
        return [sgv]

    mock_ns.get_sgv_range.side_effect = side_effect_sgv
    
    settings = UserSettings()
    
    # Run analysis (writes to db, but db is mock)
    res = await run_analysis_service("test_user", 30, settings, mock_ns, mock_db)
    assert res["boluses"] == 5
    
    # Verify DB inserts happened
    # mock_db.execute called for cleanup + reads + inserts
    assert mock_db.execute.call_count >= 15
    
    # NOW Test Summary Logic
    # We need to mock the SELECT retrieval
    
    # Construct rows that simulated what we just wrote
    # 5 boluses * 1 window (testing 3h specifically for insight)
    # Actually get_summary aggregates all windows.
    
    mock_rows = []
    for i in range(5):
        # 3h window -> short
        mock_rows.append(BolusPostAnalysis(
            user_id="test_user",
            meal_slot="breakfast",
            window_h=3,
            result="short",
            iob_status="ok",
            bolus_at=now
        ))
        
    # Mock db.execute returning scalars
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_rows
    
    mock_db_read = AsyncMock()
    mock_db_read.execute.return_value = mock_result
    
    summary = await get_summary_service("test_user", 30, mock_db_read)
    
    # Check insight
    # We expect "En desayunos, a las 3h sueles estar ALTO."
    insights = summary.get("insights", [])
    print(insights)
    
    has_insight = False
    for i in insights:
        if "desayunos" in i and "3h" in i and "ALTO" in i:
            has_insight = True
            
    assert has_insight, "Insight 'desayunos 3h alto' not found"
