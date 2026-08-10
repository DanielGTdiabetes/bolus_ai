from app.services.active_plan_store import (
    find_active_plan,
    load_active_plans,
    select_due_active_plan,
    update_active_plan,
)


class FakeStore:
    def __init__(self, data=None):
        self.data = data or {"plans": []}

    def load_json(self, name):
        assert name == "active_plans.json"
        return self.data

    def save_json(self, name, payload):
        assert name == "active_plans.json"
        self.data = payload


def test_select_due_plan_uses_planned_later_dose_and_respects_snooze():
    base_ms = 1_700_000_000_000
    plans = [
        {
            "id": "p1",
            "created_at_ts": base_ms,
            "later_u_planned": 2.0,
            "later_after_min": 60,
            "status": "pending",
        },
        {
            "id": "p2",
            "created_at_ts": base_ms + 1_000,
            "later_u_planned": 3.0,
            "later_after_min": 30,
            "snooze_until_ts": base_ms + 10_000_000,
            "status": "pending",
        },
    ]

    due = select_due_active_plan(plans, now_ms=base_ms + 61 * 60_000)
    assert due["id"] == "p1"
    assert due["later_u_planned"] == 2.0


def test_completed_zero_or_invalid_timestamp_plan_is_not_due():
    base_ms = 1_700_000_000_000
    plans = [
        {
            "id": "done",
            "created_at_ts": base_ms,
            "later_u_planned": 2,
            "later_after_min": 1,
            "status": "completed",
        },
        {
            "id": "zero-dose",
            "created_at_ts": base_ms,
            "later_u_planned": 0,
            "later_after_min": 1,
            "status": "pending",
        },
        {
            "id": "zero-time",
            "created_at_ts": 0,
            "later_u_planned": 2,
            "later_after_min": 1,
            "status": "pending",
        },
    ]
    assert select_due_active_plan(plans, now_ms=base_ms + 9_000_000) is None


def test_find_and_update_plan_by_plan_or_treatment_id():
    store = FakeStore({
        "plans": [{
            "id": "plan-1",
            "plan_id": "plan-1",
            "treatment_id": "tx-1",
            "created_at_ts": 1_700_000_000_000,
            "later_u_planned": 1.5,
            "later_after_min": 90,
            "status": "pending",
        }]
    })

    assert find_active_plan(store, "tx-1")["id"] == "plan-1"
    updated = update_active_plan(store, "plan-1", status="cancelled")
    assert updated["status"] == "cancelled"
    assert load_active_plans(store)[0]["status"] == "cancelled"


def test_epoch_seconds_are_supported_for_legacy_plans():
    # 1_700_000_000 is seconds, not milliseconds.
    plan = {
        "id": "legacy",
        "created_at_ts": 1_700_000_000,
        "later_u_planned": 1,
        "later_after_min": 1,
        "status": "pending",
    }
    assert select_due_active_plan([plan], now_ms=1_700_000_061_000)["id"] == "legacy"
