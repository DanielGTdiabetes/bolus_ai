from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.models.bolus_v2 import BolusResponseV2, GlucoseUsed, UsedParams

client = TestClient(app)


def _headers(token: str = "agent-test-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_agent_status_without_token_is_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-test-token")
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)

    response = client.get("/api/agent/status")

    assert response.status_code == 401


def test_agent_status_with_valid_token_ok(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-test-token")
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)
    monkeypatch.delenv("APP_INSTANCE_ROLE", raising=False)
    monkeypatch.delenv("APP_INSTANCE_LOCATION", raising=False)

    response = client.get("/api/agent/status", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["safe_mode"] == "read_only_estimate_only"
    assert body["agent_api_enabled"] is True
    assert body["instance_role"] == "unknown"
    assert body["instance_location"] == "unknown"
    assert body["emergency_mode"] is False
    assert "nightscout" in body
    assert "dexcom" in body


def test_agent_status_reports_backup_render_emergency_mode(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-test-token")
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)
    monkeypatch.setenv("APP_INSTANCE_ROLE", "backup")
    monkeypatch.setenv("APP_INSTANCE_LOCATION", "render")

    response = client.get("/api/agent/status", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["instance_role"] == "backup"
    assert body["instance_location"] == "render"
    assert body["emergency_mode"] is True


def test_agent_api_disabled_without_configured_token(monkeypatch):
    monkeypatch.delenv("AGENT_API_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)

    response = client.get("/api/agent/status", headers=_headers())

    assert response.status_code == 503


def test_agent_status_does_not_require_external_services(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-test-token")
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)

    response = client.get("/api/agent/status", headers=_headers())

    assert response.status_code == 200
    assert response.json()["nightscout"]["reachable"] is None


def _make_user_settings(insulin_name: str = "Novorapid", iob_curve: str = "novorapid"):
    """Build a UserSettings instance with the given insulin name and IOB curve."""
    from app.models.settings import UserSettings

    return UserSettings.model_validate(
        {
            "insulin": {"name": insulin_name},
            "iob": {"curve": iob_curve, "dia_hours": 4.0, "peak_minutes": 75},
        }
    )


def test_agent_profile_returns_real_settings(monkeypatch, mocker):
    """Profile endpoint must read user settings, not return hardcoded defaults."""
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-test-token")
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)

    mocker.patch(
        "app.api.agent._load_user_settings",
        new=AsyncMock(return_value=_make_user_settings("Novorapid", "novorapid")),
    )

    response = client.get("/api/agent/profile", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["insulin_onset_min"] == 15
    assert body["insulin_peak_min"] == 75
    assert body["dia_hours"] == 4.0


def test_agent_profile_fiasp_returns_ultrafast_timing(monkeypatch, mocker):
    """Fiasp insulin must yield onset=5, peak=55."""
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-test-token")
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)

    mocker.patch(
        "app.api.agent._load_user_settings",
        new=AsyncMock(return_value=_make_user_settings("Fiasp", "fiasp")),
    )

    response = client.get("/api/agent/profile", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["insulin_onset_min"] == 5
    assert body["insulin_peak_min"] == 55


def test_agent_profile_novorapid_returns_rapid_timing(monkeypatch, mocker):
    """NovoRapid insulin must yield onset=15, peak=75."""
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-test-token")
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)

    mocker.patch(
        "app.api.agent._load_user_settings",
        new=AsyncMock(return_value=_make_user_settings("NovoRapid", "novorapid")),
    )

    response = client.get("/api/agent/profile", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["insulin_onset_min"] == 15
    assert body["insulin_peak_min"] == 75


def test_agent_profile_unknown_insulin_uses_default_timing(monkeypatch, mocker):
    """Unknown insulin names must fall back to rapid-analogue defaults (15/75)."""
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-test-token")
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)

    mocker.patch(
        "app.api.agent._load_user_settings",
        new=AsyncMock(return_value=_make_user_settings("MyCustomInsulin", "walsh")),
    )

    response = client.get("/api/agent/profile", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["insulin_onset_min"] == 15
    assert body["insulin_peak_min"] == 75


def test_agent_profile_without_bearer_token_is_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-test-token")
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)

    response = client.get("/api/agent/profile")

    assert response.status_code == 401


def test_agent_profile_disabled_without_configured_token(monkeypatch):
    monkeypatch.delenv("AGENT_API_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)

    response = client.get("/api/agent/profile", headers=_headers())

    assert response.status_code == 503


def test_agent_bolus_estimate_does_not_persist_or_upload(monkeypatch, mocker):
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-test-token")
    monkeypatch.delenv("AGENT_ALLOWED_IPS", raising=False)
    mocked_calc = mocker.patch(
        "app.api.agent.calculate_bolus_stateless_service",
        new=AsyncMock(return_value=_bolus_response()),
    )
    mocked_log = mocker.patch(
        "app.services.treatment_logger.log_treatment", new=AsyncMock()
    )
    mocked_upload = mocker.patch(
        "app.services.nightscout_client.NightscoutClient.upload_treatments",
        new=AsyncMock(),
    )

    response = client.post(
        "/api/agent/bolus/estimate",
        headers=_headers(),
        json={
            "carbs_g": 10,
            "bg_mgdl": 120,
            "meal_slot": "lunch",
            "cr_g_per_u": 10,
            "isf_mgdl_per_u": 50,
            "confirm_iob_unknown": True,
            "manual_iob_u": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is False
    assert body["nightscout_uploaded"] is False
    mocked_calc.assert_awaited_once()
    assert mocked_calc.await_args.kwargs["persist_autosens_run"] is False
    assert mocked_calc.await_args.kwargs["persist_iob_cache"] is False
    mocked_log.assert_not_awaited()
    mocked_upload.assert_not_awaited()


def _bolus_response() -> BolusResponseV2:
    return BolusResponseV2(
        ok=True,
        total_u=1.0,
        meal_bolus_u=1.0,
        correction_u=0.0,
        iob_u=0.0,
        total_u_raw=1.0,
        total_u_final=1.0,
        kind="normal",
        upfront_u=1.0,
        later_u=0.0,
        duration_min=0,
        glucose=GlucoseUsed(mgdl=120, source="manual"),
        used_params=UsedParams(
            cr_g_per_u=10,
            isf_mgdl_per_u=50,
            target_mgdl=100,
            dia_hours=4,
            max_bolus_final=10,
        ),
        explain=["Estimación de prueba"],
        warnings=[],
    )
