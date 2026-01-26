import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "backend"))

from app.core.settings import NightPatternConfig  # noqa: E402
from app.services.night_pattern import NightPatternContext  # noqa: E402


def test_forecast_night_pattern_context_contract():
    cfg = NightPatternConfig(enabled=True)

    context = NightPatternContext(
        draft_active=False,
        meal_recent=False,
        bolus_recent=False,
        iob_u=0.1,
        cob_g=0.0,
        trend_slope=0.1,
        sustained_rise=False,
        slow_digestion_signal=False,
        last_meal_high_fat_protein=False,
    )

    assert cfg.enabled is True
    assert context.draft_active is False
