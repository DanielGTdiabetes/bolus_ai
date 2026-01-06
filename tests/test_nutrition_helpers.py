import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "backend"))

from app.api.integrations import normalize_nutrition_payload, should_update_fiber  # noqa: E402


def test_normalize_handles_fiber_variants():
    payload = {"nutrition": {"fiber": 12}, "carbohydrates_total_g": 0}
    norm = normalize_nutrition_payload(payload)
    assert norm["fiber"] == 12


def test_normalize_accepts_t_fiber():
    payload = {"t_fiber": 10, "fat": 0, "protein": 0}
    norm = normalize_nutrition_payload(payload)
    assert norm["fiber"] == 10


def test_should_update_fiber_detects_change():
    assert should_update_fiber(5, 9) is True
    assert should_update_fiber(5, 5.01, tolerance=0.5) is False
