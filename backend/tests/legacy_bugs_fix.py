import os
import pytest
from unittest.mock import MagicMock, patch

import respx
from httpx import Response

from app.models.settings import UserSettings
from app.services.bolus import BolusRequestData, recommend_bolus

# Setup Env before importing app
@pytest.fixture(autouse=True)
def setup_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-bugs")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("VISION_PROVIDER", "openai")

# --- TEST 1: Migration ---
def test_cr_migration_logic():
    # Case A: 1.0 -> 10.0
    raw_a = {"cr": {"breakfast": 1.0, "lunch": 1.0, "dinner": 1.0}}
    settings_a = UserSettings.migrate(raw_a)
    assert settings_a.cr.breakfast == 10.0
    
    # Case B: Inverted (0.1 U/g) -> Should flip to 10.0
    raw_b = {"cr": {"breakfast": 0.1, "lunch": 0.05, "dinner": 20}}
    settings_b = UserSettings.migrate(raw_b)
    assert settings_b.cr.breakfast == 10.0 
    assert settings_b.cr.lunch == 20.0 
    assert settings_b.cr.dinner == 20.0

    # Case C: Correct (15.0) -> No change
    raw_c = {"cr": {"breakfast": 15.0}}
    settings_c = UserSettings.migrate(raw_c)
    assert settings_c.cr.breakfast == 15.0

# --- TEST 2: Boolean Math ---
def test_bolus_math_cr_definition():
    settings = UserSettings()
    settings.cr.lunch = 10.0
    settings.targets.mid = 100
    settings.cf.lunch = 50.0

    # 10g carbs / 10g/U = 1.0 U
    req = BolusRequestData(carbs_g=10.0, bg_mgdl=100.0, meal_slot="lunch")
    res = recommend_bolus(req, settings, iob_u=0.0)
    assert res.upfront_u == 1.0
    
    found = any("Carbs: 10.0 g / CR 10.0" in x for x in res.explain)
    assert found

# --- TEST 3: Nightscout Fallback ---
@pytest.mark.asyncio
async def test_api_recommend_uses_nightscout_when_no_bg():
    # Helper to load app after env setup
    from app.main import app
    from fastapi.testclient import TestClient
    
    client = TestClient(app)
    
    mock_settings = UserSettings()
    mock_settings.nightscout.enabled = True
    mock_settings.nightscout.url = "https://ns.test"
    mock_settings.nightscout.token = "token"
    mock_settings.cr.lunch = 10.0
    
    with patch("app.services.store.DataStore.load_settings", return_value=mock_settings):
        with patch("app.services.iob.compute_iob_from_sources", return_value=(0.0, [])):
             with respx.mock(base_url="https://ns.test", assert_all_called=False) as respx_mock:
                 respx_mock.get("/api/v1/entries/sgv.json").mock(
                     return_value=Response(200, json=[{"sgv": 150, "direction": "Flat", "date": 1234567890}])
                 )
                 
                 payload = {"carbs_g": 0, "meal_slot": "lunch"}
                 resp = client.post("/api/bolus/recommend", json=payload)
                 
                 assert resp.status_code == 200, resp.text
                 data = resp.json()
                 
                 assert data["glucose"]["source"] == "nightscout"
                 assert data["glucose"]["mgdl"] == 150.0

@pytest.mark.asyncio
async def test_api_recommend_fallback_when_ns_fails():
    from app.main import app
    from fastapi.testclient import TestClient
    
    client = TestClient(app)
    
    mock_settings = UserSettings()
    mock_settings.nightscout.enabled = True
    mock_settings.nightscout.url = "https://ns.fail"
    mock_settings.cr.lunch = 10.0
    
    with patch("app.services.store.DataStore.load_settings", return_value=mock_settings):
        with patch("app.services.iob.compute_iob_from_sources", return_value=(0.0, [])):
             with respx.mock(base_url="https://ns.fail", assert_all_called=False) as respx_mock:
                 respx_mock.get("/api/v1/entries/sgv.json").mock(return_value=Response(500))
                 
                 payload = {"carbs_g": 10, "meal_slot": "lunch"}
                 resp = client.post("/api/bolus/recommend", json=payload)
                 
                 assert resp.status_code == 200
                 data = resp.json()
                 
                 assert data["glucose"]["source"] == "none"
                 assert data["upfront_u"] == 1.0
