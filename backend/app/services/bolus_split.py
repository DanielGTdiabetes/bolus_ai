import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.models.bolus_split import (
    BolusPlanRequest,
    BolusPlanResponse,
    RecalcComponents,
    RecalcSecondRequest,
    RecalcSecondResponse,
)
from app.models.bolus_v2 import BolusRequestV2, NightscoutConfigSimple
from app.services.bolus_calc_service import calculate_bolus_stateless_service
from app.services.store import DataStore

logger = logging.getLogger(__name__)


def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(value / step) * step


def create_plan(req: BolusPlanRequest) -> BolusPlanResponse:
    plan_id = str(uuid.uuid4())
    warnings: list[str] = []

    now_u = 0.0
    later_u = 0.0
    later_after_min = 60
    extended_duration = None

    if req.mode == "manual":
        manual = req.manual
        now_u = manual.now_u
        later_u = manual.later_u
        later_after_min = manual.later_after_min

        total = now_u + later_u
        difference = abs(total - req.total_recommended_u)
        if difference > req.round_step_u + 0.001:
            warnings.append(
                f"Sum {total} differs from total {req.total_recommended_u} "
                f"by > {req.round_step_u}"
            )
    elif req.mode == "dual":
        dual = req.dual
        now_u = round_to_step(
            req.total_recommended_u * (dual.percent_now / 100.0),
            req.round_step_u,
        )
        later_u = round_to_step(
            max(0.0, req.total_recommended_u - now_u),
            req.round_step_u,
        )
        later_after_min = dual.later_after_min
        extended_duration = dual.duration_min

    return BolusPlanResponse(
        plan_id=plan_id,
        mode=req.mode,
        total_recommended_u=req.total_recommended_u,
        now_u=now_u,
        later_u_planned=later_u,
        later_after_min=later_after_min,
        extended_duration_min=extended_duration,
        warnings=warnings,
    )


async def recalc_second(
    req: RecalcSecondRequest,
    *,
    store: DataStore,
    user: CurrentUser,
    session: AsyncSession,
) -> RecalcSecondResponse:
    """Recalculate a second tranche through the authoritative bolus service.

    This function is intentionally only an adapter. The meal, correction and
    IOB rules live in the central bolus engine used by every other interface.
    """
    nightscout = None
    if req.nightscout and req.nightscout.url:
        nightscout = NightscoutConfigSimple(
            url=req.nightscout.url,
            token=req.nightscout.token,
        )

    payload = BolusRequestV2(
        carbs_g=req.carbs_additional_g,
        meal_slot="lunch",
        target_mgdl=req.params.target_bg_mgdl,
        cr_g_per_u=req.params.cr_g_per_u,
        isf_mgdl_per_u=req.params.isf_mgdl_per_u,
        dia_hours=req.params.dia_hours,
        insulin_model=req.params.insulin_curve,
        insulin_peak_minutes=req.params.peak_minutes,
        round_step_u=req.params.round_step_u,
        max_bolus_u=req.params.max_bolus_u,
        nightscout=nightscout,
        enable_autosens=False,
    )
    result = await calculate_bolus_stateless_service(
        payload,
        store=store,
        user=user,
        session=session,
    )

    positive_correction = max(result.correction_u, 0.0)
    iob_applied_to_correction = min(positive_correction, result.iob_u)

    return RecalcSecondResponse(
        bg_now_mgdl=result.glucose.mgdl,
        bg_age_min=(
            int(result.glucose.age_minutes)
            if result.glucose.age_minutes is not None
            else None
        ),
        iob_now_u=result.iob_u,
        components=RecalcComponents(
            meal_u=result.meal_bolus_u,
            correction_u=result.correction_u,
            iob_applied_u=round(iob_applied_to_correction, 2),
        ),
        cap_u=req.params.max_bolus_u,
        u2_recommended_u=result.total_u_final,
        warnings=result.warnings,
    )
