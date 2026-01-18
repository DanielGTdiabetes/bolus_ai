import pytest
from app.models.bolus_split import BolusPlanRequest, ManualSplit, DualSplit, BolusParams, NightscoutConn, RecalcSecondRequest
from app.services.bolus_split import create_plan, recalc_second

# --- PLAN TESTS ---

def test_plan_manual_exact():
    req = BolusPlanRequest(
        mode="manual",
        total_recommended_u=10.0,
        manual=ManualSplit(now_u=6.0, later_u=4.0, later_after_min=60)
    )
    res = create_plan(req)
    assert res.now_u == 6.0
    assert res.later_u_planned == 4.0
    assert len(res.warnings) == 0

def test_plan_manual_tolerance():
    # 8.0 split into 4.0 and 3.5 (sum 7.5, diff 0.5 <= step 0.5)
    req = BolusPlanRequest(
        mode="manual",
        total_recommended_u=8.0,
        round_step_u=0.5,
        manual=ManualSplit(now_u=4.0, later_u=3.5, later_after_min=60)
    )
    res = create_plan(req)
    assert len(res.warnings) == 0

def test_plan_manual_tolerance_fail():
    # 8.0 split into 4.0 and 3.0 (sum 7.0, diff 1.0 > step 0.5)
    req = BolusPlanRequest(
        mode="manual",
        total_recommended_u=8.0,
        round_step_u=0.5,
        manual=ManualSplit(now_u=4.0, later_u=3.0, later_after_min=60)
    )
    res = create_plan(req)
    assert len(res.warnings) > 0
    assert "differs" in res.warnings[0]

def test_plan_dual_calc():
    # 10U, 60% now => 6U now, 4U later
    req = BolusPlanRequest(
        mode="dual",
        total_recommended_u=10.0,
        round_step_u=0.1,
        dual=DualSplit(percent_now=60, duration_min=120)
    )
    res = create_plan(req)
    assert res.now_u == 6.0
    assert res.later_u_planned == 4.0
    assert res.extended_duration_min == 120

def test_plan_dual_rounding():
    # 10U, 33% now => 3.333U. Step 0.5 => 3.5U
    # later = 10 - 3.5 = 6.5U. rounded to 0.5 => 6.5U.
    req = BolusPlanRequest(
        mode="dual",
        total_recommended_u=10.0,
        round_step_u=0.5,
        dual=DualSplit(percent_now=33, duration_min=120)
    )
    res = create_plan(req)
    assert res.now_u == 3.5
    assert res.later_u_planned == 6.5

# --- RECALC TESTS ---

@pytest.mark.asyncio
async def test_recalc_second_mock(mocker):
    # Mock Instance
    mock_instance = mocker.AsyncMock()
    # attributes need to be set on return_value of methods if they are async methods?
    # get_latest_sgv is async.
    
    # Setup SGV
    mock_sgv = mocker.Mock()
    from datetime import datetime, timezone
    mock_sgv.sgv = 150
    mock_sgv.date = int(datetime.now(timezone.utc).timestamp() * 1000)
    mock_instance.get_latest_sgv.return_value = mock_sgv
    
    # Setup Treatments
    mock_instance.get_recent_treatments.return_value = []
    
    # Patch the Class to return this instance
    mock_cls = mocker.patch("app.services.bolus_split.NightscoutClient")
    mock_cls.return_value = mock_instance
    
    # Params
    params = BolusParams(
        cr_g_per_u=10, 
        isf_mgdl_per_u=50, 
        target_bg_mgdl=100
    )
    
    # 50mg/dl over target => 1U correction
    # 10g carbs => 1U meal
    # Total raw = 2U
    # IOB = 0
    # Net = 2U
    # Cap = 3U
    
    req = RecalcSecondRequest(
        later_u_planned=3.0,
        carbs_additional_g=10,
        params=params,
        nightscout=NightscoutConn(url="http://mock")
    )
    
    res = await recalc_second(req)
    
    assert res.bg_now_mgdl == 150
    assert res.iob_now_u == 0
    assert res.components.meal_u == 1.0
    assert res.components.correction_u == 1.0
    assert res.u2_recommended_u == 2.0
    assert len(res.warnings) == 0

@pytest.mark.asyncio
async def test_recalc_second_cap(mocker):
    mock_instance = mocker.AsyncMock()
    mock_sgv = mocker.Mock()
    mock_sgv.sgv = 200
    # Date needed for stale check or it defaults to warnings?
    # Logic: if fails, warnings. But we want succes.
    # We should ensure date is fresh.
    # But wait, date is int timestamp.
    from datetime import datetime, timezone
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    mock_sgv.date = now_ms
    
    mock_instance.get_latest_sgv.return_value = mock_sgv
    mock_instance.get_recent_treatments.return_value = []
    
    mock_cls = mocker.patch("app.services.bolus_split.NightscoutClient")
    mock_cls.return_value = mock_instance
    
    # Params
    params = BolusParams(
        cr_g_per_u=10, 
        isf_mgdl_per_u=50, # 100 over => 2U
        target_bg_mgdl=100
    )
    # Meal 20g => 2U
    # Total 4U
    # Cap 3U
    
    req = RecalcSecondRequest(
        later_u_planned=3.0,
        carbs_additional_g=20,
        params=params,
        nightscout=NightscoutConn(url="http://mock")
    )
    
    res = await recalc_second(req)
    assert res.u2_recommended_u == 4.0

@pytest.mark.asyncio
async def test_recalc_second_iob_subtraction(mocker):
    mock_instance = mocker.AsyncMock()
    
    mock_sgv = mocker.Mock()
    from datetime import datetime, timezone, timedelta
    mock_sgv.sgv = 100 # No correction
    mock_sgv.date = int(datetime.now(timezone.utc).timestamp() * 1000)
    mock_instance.get_latest_sgv.return_value = mock_sgv
    
    # Fake treatment 30 min ago, 5U. 
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(minutes=30)).isoformat()
    
    from app.models.schemas import Treatment
    # Ensure we use valid fields
    t = Treatment(
        _id="1", eventType="Correction Bolus", created_at=ts, insulin=5.0, carbs=0, enteredBy="test"
    )
    mock_instance.get_recent_treatments.return_value = [t]
    
    mock_cls = mocker.patch("app.services.bolus_split.NightscoutClient")
    mock_cls.return_value = mock_instance
    
    params = BolusParams(cr_g_per_u=10, isf_mgdl_per_u=50, target_bg_mgdl=100)
    # Meal 20g => 2U needed
    # IOB should cover it.
    
    req = RecalcSecondRequest(
        later_u_planned=3.0,
        carbs_additional_g=20,
        params=params,
        nightscout=NightscoutConn(url="http://mock")
    )
    
    res = await recalc_second(req)
    
    assert res.iob_now_u > 2.0 
    assert res.components.iob_applied_u > 2.0 
    assert res.u2_recommended_u == 0.0 # Covered by IOB
