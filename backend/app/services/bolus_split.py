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
from app.models.bolus_v2 import BolusRequestV2
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
    """Recalculate additional carbs/current correction via the central engine.

    The request may contain legacy ``params``/``nightscout`` fields from older
    clients, but they are deliberately non-authoritative. Current ICR, ISF,
    target, DIA, insulin model, limits, data sources and Autosens state are
    resolved by ``calculate_bolus_stateless_service`` from backend user settings.

    ``later_u_planned`` is retained as plan metadata for compatibility. This
    adapter does not silently add it to the newly calculated dose; planned-dose
    semantics are handled separately from new-carbohydrate/correction math.
    """
    payload = BolusRequestV2(
        carbs_g=req.carbs_additional_g,
        meal_slot=req.meal_slot,
        # Important: no client dosing overrides and no enable_autosens override.
        # Omission means the authenticated user's saved backend configuration
        # remains authoritative, including Autosens when enabled.
    )
    result = await calculate_bolus_stateless_service(
        payload,
        store=store,
        user=user,
        session=session,
    )

    warnings = list(result.warnings or [])
    if req.later_u_planned > 0:
        warnings.append(
            "La dosis planificada para más tarde se mantiene separada del "
            "recálculo de hidratos adicionales/corrección actual."
        )

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
            iob_applied_u=round(result.iob_applied_to_correction_u, 2),
        ),
        cap_u=result.used_params.max_bolus_final,
        u2_recommended_u=result.total_u_final,
        warnings=warnings,
    )
