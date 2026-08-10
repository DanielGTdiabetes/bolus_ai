import math

import pytest
from pydantic import ValidationError

from app.models.bolus_v2 import BolusRequestV2


def valid_payload(**overrides):
    payload = {
        "carbs_g": 20,
        "bg_mgdl": 110,
        "target_mgdl": 110,
        "cr_g_per_u": 10,
        "isf_mgdl_per_u": 30,
        "manual_iob_u": 0,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("bg", [0, 39.9, 400.1, 999])
def test_manual_bg_outside_dosing_range_is_rejected(bg):
    with pytest.raises(ValidationError):
        BolusRequestV2.model_validate(valid_payload(bg_mgdl=bg))


@pytest.mark.parametrize(
    "field,value",
    [
        ("carbs_g", math.inf),
        ("bg_mgdl", math.inf),
        ("target_mgdl", math.inf),
        ("cr_g_per_u", math.inf),
        ("isf_mgdl_per_u", math.inf),
        ("manual_iob_u", math.inf),
    ],
)
def test_non_finite_dosing_inputs_are_rejected(field, value):
    with pytest.raises(ValidationError):
        BolusRequestV2.model_validate(valid_payload(**{field: value}))


@pytest.mark.parametrize("bg", [40, 70, 110, 400])
def test_valid_manual_bg_boundaries_are_accepted(bg):
    request = BolusRequestV2.model_validate(valid_payload(bg_mgdl=bg))
    assert request.bg_mgdl == bg


def test_new_carbs_contract_accepts_zero_and_reasonable_values():
    assert BolusRequestV2.model_validate(valid_payload(carbs_g=0)).carbs_g == 0
    assert BolusRequestV2.model_validate(valid_payload(carbs_g=60)).carbs_g == 60


def test_unreasonably_large_carbs_are_rejected():
    with pytest.raises(ValidationError):
        BolusRequestV2.model_validate(valid_payload(carbs_g=501))
