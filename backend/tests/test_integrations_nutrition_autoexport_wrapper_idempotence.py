import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from .test_integrations_nutrition import _auth_headers, _fetch_all_treatments, client

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "autoexport_wrapper_real.json"


def _load_wrapper_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _expected_timestamps(payload: dict) -> dict[str, datetime]:
    metrics = payload["payload"]["data"]["metrics"]
    timestamps = {
        entry["date"]
        for metric in metrics
        for entry in metric.get("data", [])
        if entry.get("date")
    }
    return {
        date_str: datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
        for date_str in timestamps
    }


def _assert_imported_treatments(client: TestClient, expected_dates: dict[str, datetime]) -> None:
    treatments = _fetch_all_treatments(client)
    imported = [t for t in treatments if t.notes and "#imported" in t.notes]
    assert len(imported) == len(expected_dates)
    for date_str, expected_ts in expected_dates.items():
        matches = [t for t in imported if date_str in (t.notes or "")]
        assert len(matches) == 1
        assert matches[0].created_at == expected_ts


def test_autoexport_wrapper_idempotence(client: TestClient):
    headers = _auth_headers(client)
    payload = _load_wrapper_payload()
    expected_dates = _expected_timestamps(payload)

    resp_first = client.post("/api/integrations/nutrition", headers=headers, json=payload)
    assert resp_first.status_code == 200
    data_first = resp_first.json()
    assert data_first["success"] == 1
    assert data_first["ingested_count"] == 4
    assert len(data_first["ids"]) == len(set(data_first["ids"]))

    _assert_imported_treatments(client, expected_dates)

    resp_second = client.post("/api/integrations/nutrition", headers=headers, json=payload)
    assert resp_second.status_code == 200
    data_second = resp_second.json()
    assert data_second["success"] == 1
    assert data_second.get("ingested_count", 0) == 0
    assert len(data_second.get("ids", [])) == len(set(data_second.get("ids", [])))

    _assert_imported_treatments(client, expected_dates)


def test_autoexport_direct_payload_idempotence(client: TestClient):
    headers = _auth_headers(client)
    payload = _load_wrapper_payload()
    direct_payload = payload["payload"]
    expected_dates = _expected_timestamps(payload)

    resp_first = client.post("/api/integrations/nutrition", headers=headers, json=direct_payload)
    assert resp_first.status_code == 200
    data_first = resp_first.json()
    assert data_first["success"] == 1
    assert data_first["ingested_count"] == 4
    assert len(data_first["ids"]) == len(set(data_first["ids"]))

    _assert_imported_treatments(client, expected_dates)

    resp_second = client.post("/api/integrations/nutrition", headers=headers, json=direct_payload)
    assert resp_second.status_code == 200
    data_second = resp_second.json()
    assert data_second["success"] == 1
    assert data_second.get("ingested_count", 0) == 0
    assert len(data_second.get("ids", [])) == len(set(data_second.get("ids", [])))

    _assert_imported_treatments(client, expected_dates)
