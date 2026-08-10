from app.api.bolus import ActivePlan


def test_legacy_active_plan_remains_valid():
    plan = ActivePlan(
        id="legacy-plan",
        created_at_ts=1000,
        upfront_u=4,
        later_u_planned=2,
        later_after_min=90,
    )

    assert plan.id == "legacy-plan"
    assert plan.treatment_id is None
    assert plan.total_recommended_u is None
    assert plan.status == "pending"


def test_enriched_active_plan_preserves_treatment_and_meal_context():
    plan = ActivePlan(
        id="plan-123",
        plan_id="plan-123",
        treatment_id="tx-123",
        created_at_ts=1000,
        upfront_u=3.5,
        later_u_planned=2,
        later_after_min=90,
        extended_duration_min=120,
        mode="dual",
        source="app-manual-split",
        meal_slot="dinner",
        total_recommended_u=6,
    )

    assert plan.plan_id == "plan-123"
    assert plan.treatment_id == "tx-123"
    assert plan.meal_slot == "dinner"
    assert plan.total_recommended_u == 6
