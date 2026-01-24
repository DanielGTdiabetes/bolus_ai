from pathlib import Path

from app.models.settings import UserSettings
from app.services.forecast_diagnostics import SweepConfig, run_forecast_sweep


def test_forecast_sweep_smoke(tmp_path: Path):
    settings = UserSettings.default()
    config = SweepConfig(
        slots=("breakfast",),
        carbs_grid=(0, 30),
        bolus_grid=(0, 6),
        horizon_minutes=180,
    )

    result = run_forecast_sweep(
        user_settings=settings,
        user_id="test-user",
        basal_entry=None,
        output_dir=tmp_path,
        config=config,
        print_summary=False,
    )

    csv_path = Path(result["csv_path"])
    json_path = Path(result["json_path"])

    assert csv_path.exists()
    assert json_path.exists()
    assert csv_path.read_text(encoding="utf-8").count("\n") >= 2
