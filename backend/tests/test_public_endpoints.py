import pytest
from httpx import AsyncClient
from app.main import app
from app.core.security import create_access_token

@pytest.mark.asyncio
async def test_public_endpoints_no_auth():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # 1. PLAN (Public)
        plan_load = {
          "mode": "dual",
          "total_recommended_u": 8.0,
          "round_step_u": 0.5,
          "dual": {"percent_now": 60, "duration_min": 120, "later_after_min": 60}
        }
        res = await ac.post("/api/bolus/plan", json=plan_load)
        assert res.status_code == 200, f"Got {res.status_code}: {res.text}"
        data = res.json()
        assert data["mode"] == "dual"
        
        # 2. RECALC (Public) - Needs mocking external services ideally, 
        # but here we just check we hit logic, not 401. 
        # Logic might fail 500 if we don't mock NS/IOB but we want to confirm NO 401.
        recalc_load = {
          "later_u_planned": 3.0,
          "carbs_additional_g": 15,
          "params": {
            "cr_g_per_u": 10,
            "isf_mgdl_per_u": 40,
            "target_bg_mgdl": 110,
            "round_step_u": 0.5,
            "max_bolus_u": 12,
            "stale_bg_minutes": 15
          },
          "nightscout": {
            "url": "http://mock-ns.com",
            "token": "skip",
            "units": "mgdl"
          }
        }
        # We expect 200 (handled error/warnings inside) OR 500 (logic error), but NOT 401.
        # Actually our recalc_second logic catches exceptions?
        # In api_recalc_second calling recalc_second...
        # recalc_second catches BG fetch and IOB errors internally and returns warnings.
        # So it should be 200.
        res = await ac.post("/api/bolus/recalc-second", json=recalc_load)
        if res.status_code == 401:
            pytest.fail("Recalc endpoint rejected public access (401)")
            
        assert res.status_code == 200
        # Warnings might be present because http://mock-ns.com fails
        j = res.json()
        assert "warnings" in j

@pytest.mark.asyncio
async def test_protected_endpoints_require_auth():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Try /api/bolus/treatments without token
        res = await ac.post("/api/bolus/treatments", json={})
        # Should be 401 Unauthorized
        assert res.status_code == 401

@pytest.mark.asyncio
async def test_protected_endpoints_with_auth():
    # Generate token
    token = create_access_token({"sub": "admin"})
    headers = {"Authorization": f"Bearer {token}"}
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Check hitting a protected endpoint gives something other than 401
        # It might give 422 validation error for empty body, which proves auth passed.
        res = await ac.post("/api/bolus/treatments", json={}, headers=headers)
        assert res.status_code != 401
        assert res.status_code == 422 # Body required
