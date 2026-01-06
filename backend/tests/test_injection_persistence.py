import pytest
from fastapi.testclient import TestClient

from .test_injection_state import _auth_headers, client as base_client


@pytest.fixture()
def client(base_client: TestClient):
    return base_client


def test_manual_injection_returns_json_and_persists_for_rapid(client: TestClient):
    headers = _auth_headers(client)
    point_id = "abd_r_top:1"

    resp = client.post(
        "/api/injection/manual",
        headers=headers,
        json={"insulin_type": "rapid", "point_id": point_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["insulin_type"] == "rapid"
    assert isinstance(body["point_id"], str)
    assert body["point_id"] == point_id
    assert body["source"] == "manual"

    state = client.get("/api/injection/state", headers=headers).json()
    assert state["states"]["bolus"]["last_point_id"] == point_id
    assert state["bolus"] == point_id


def test_manual_injection_returns_json_and_persists_for_basal(client: TestClient):
    headers = _auth_headers(client)
    point_id = "glute_right:1"

    resp = client.post(
        "/api/injection/manual",
        headers=headers,
        json={"insulin_type": "basal", "point_id": point_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["insulin_type"] == "basal"
    assert isinstance(body["point_id"], str)
    assert body["point_id"] == point_id
    assert body["source"] == "manual"

    state = client.get("/api/injection/state", headers=headers).json()
    assert state["states"]["basal"]["last_point_id"] == point_id
    assert state["basal"] == point_id
