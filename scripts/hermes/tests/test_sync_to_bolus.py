from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "sync_to_bolus.py"


def load_sync(monkeypatch, adapter):
    monkeypatch.setitem(sys.modules, "mfp_adapter", adapter)
    spec = importlib.util.spec_from_file_location("sync_to_bolus_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    return module


def meal(name: str, carbs: float):
    return {
        "meal": name,
        "carbs_g": carbs,
        "fat_g": 3,
        "protein_g": 8,
        "fiber_g": 2,
        "foods": [{"name": f"{name} food", "quantity": "1", "unit": "unidad", "carbs_g": carbs}],
    }


def day(*meals):
    return {"date": "2026-08-22", "meals": list(meals)}


def test_stabilization_rejects_62_and_accepts_27_after_two_matching_reads(monkeypatch):
    readings = iter([day(meal("lunch", 62)), day(meal("lunch", 27)), day(meal("lunch", 27))])
    module = load_sync(monkeypatch, SimpleNamespace(get_day=lambda _date: next(readings)))

    stable, read_count = module.stable_candidates("2026-08-22")

    assert read_count == 3
    assert list(stable) == ["hermes-mfp:2026-08-22:lunch"]
    assert stable["hermes-mfp:2026-08-22:lunch"]["meal"]["carbs_g"] == 27


def test_payload_separates_stable_identity_from_content_revision(monkeypatch):
    module = load_sync(monkeypatch, SimpleNamespace(get_day=lambda _date: None))
    item = {"day": "2026-08-22", "meal": meal("lunch", 27), "revision": "abc123"}

    payload = module.build_payload(item, 2)

    assert payload["meal_id"] == "hermes-mfp:2026-08-22:lunch"
    assert payload["meal_revision"] == "abc123"
    assert payload["stability_confirmed"] is True
    assert payload["foods"][0]["carbs_g"] == 27


def test_fetch_failure_is_fail_closed_and_never_posts_old_payload(monkeypatch, tmp_path):
    def fail(_date):
        raise TimeoutError("MFP timeout")

    module = load_sync(monkeypatch, SimpleNamespace(get_day=fail))
    module.STATE_PATH = tmp_path / "state.json"
    module.LOG_PATH = tmp_path / "sync.log"
    calls = []
    monkeypatch.setattr(module, "post_to_bolus", lambda payload, dry_run: calls.append(payload))

    result = module.sync_once(argparse.Namespace(date="2026-08-22", force=False, dry_run=False))

    assert result == 1
    assert calls == []
    assert json.loads(module.STATE_PATH.read_text())["last_result"]["failures"] == 1


def test_invalid_cookie_is_fail_closed(monkeypatch, tmp_path):
    def invalid_cookie(_date):
        raise RuntimeError("Cookies are missing, expired, or not accepted")

    module = load_sync(monkeypatch, SimpleNamespace(get_day=invalid_cookie))
    module.STATE_PATH = tmp_path / "state.json"
    posted = []
    monkeypatch.setattr(module, "post_to_bolus", lambda payload, dry_run: posted.append(payload))

    result = module.sync_once(argparse.Namespace(date="2026-08-22", force=False, dry_run=False))

    assert result == 1
    assert posted == []


def test_known_lunch_is_skipped_when_new_dinner_appears(monkeypatch, tmp_path):
    diary = day(meal("lunch", 27), meal("dinner", 31))
    module = load_sync(monkeypatch, SimpleNamespace(get_day=lambda _date: diary))
    module.STATE_PATH = tmp_path / "state.json"
    lunch_revision = module.meal_revision("2026-08-22", diary["meals"][0])
    module.STATE_PATH.write_text(json.dumps({
        "sent": {"hermes-mfp:2026-08-22:lunch": {"revision": lunch_revision}}
    }))
    posted = []
    monkeypatch.setattr(module, "post_to_bolus", lambda payload, dry_run: posted.append(payload) or {"success": 1, "notification_status": "queued"})

    result = module.sync_once(argparse.Namespace(date="2026-08-22", force=False, dry_run=False))

    assert result == 0
    assert [item["meal_id"] for item in posted] == ["hermes-mfp:2026-08-22:dinner"]


def test_legacy_fingerprint_state_is_migrated_without_replay(monkeypatch, tmp_path):
    diary = day(meal("lunch", 27))
    module = load_sync(monkeypatch, SimpleNamespace(get_day=lambda _date: diary))
    module.STATE_PATH = tmp_path / "state.json"
    legacy_id = module.legacy_fingerprint("2026-08-22", diary["meals"][0])
    module.STATE_PATH.write_text(json.dumps({"sent": {legacy_id: {"sent_at": "2026-08-22T14:01:00"}}}))
    posted = []
    monkeypatch.setattr(module, "post_to_bolus", lambda payload, dry_run: posted.append(payload))

    result = module.sync_once(argparse.Namespace(date="2026-08-22", force=False, dry_run=False))

    state = json.loads(module.STATE_PATH.read_text())
    assert result == 0
    assert posted == []
    assert state["sent"]["hermes-mfp:2026-08-22:lunch"]["migrated_from"] == legacy_id
