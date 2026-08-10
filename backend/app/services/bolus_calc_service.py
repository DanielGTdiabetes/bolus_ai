from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2, GlucoseUsed
from app.models.iob import SourceStatus
from app.models.settings import UserSettings
from app.services.autosens_service import AutosensService
from app.services.bolus_engine import calculate_bolus_v2
from app.services import iob as iob_service
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config
from app.services.glucose_source_service import resolve_current_glucose
from app.services.store import DataStore

logger = logging.getLogger(__name__)


async def compute_iob_from_sources(*args, **kwargs):
    return await iob_service.compute_iob_from_sources(*args, **kwargs)


async def compute_cob_from_sources(*args, **kwargs):
    return await iob_service.compute_cob_from_sources(*args, **kwargs)


async def calculate_bolus_stateless_service(
    payload: BolusRequestV2,
    *,
    store: DataStore,
    user: CurrentUser,
    session: Optional[AsyncSession],
    persist_autosens_run: bool = True,
    persist_iob_cache: bool = True,
) -> BolusResponseV2:
    # 1. Resolve Settings
    if payload.settings:
        from app.models.settings import (
            AutosensConfig,
            CorrectionFactors,
            IOBConfig,
            MealFactors,
            NightscoutConfig,
            TargetRange,
        )

        cr_settings = MealFactors(
            breakfast=payload.settings.breakfast.icr,
            lunch=payload.settings.lunch.icr,
            dinner=payload.settings.dinner.icr,
            snack=payload.settings.snack.icr if payload.settings.snack else 10.0,
        )
        isf_settings = CorrectionFactors(
            breakfast=payload.settings.breakfast.isf,
            lunch=payload.settings.lunch.isf,
            dinner=payload.settings.dinner.isf,
            snack=payload.settings.snack.isf if payload.settings.snack else 30.0,
        )

        target_settings = TargetRange(low=70, mid=100, high=180)

        c_model = getattr(payload.settings, "insulin_model", "walsh")
        if c_model not in ["walsh", "bilinear", "fiasp", "novorapid", "linear"]:
            c_model = "walsh"

        iob_settings = IOBConfig(
            dia_hours=payload.settings.dia_hours,
            curve=c_model,
            peak_minutes=payload.settings.insulin_peak_minutes or 75,
        )

        ns_settings = NightscoutConfig(
            enabled=bool(payload.nightscout and payload.nightscout.url),
            url=payload.nightscout.url if payload.nightscout else "",
            token=payload.nightscout.token if payload.nightscout else "",
        )

        user_settings = UserSettings(
            cr=cr_settings,
            cf=isf_settings,
            targets=target_settings,
            iob=iob_settings,
            nightscout=ns_settings,
            autosens=AutosensConfig(enabled=payload.enable_autosens)
            if payload.enable_autosens is not None
            else AutosensConfig(),
            max_bolus_u=payload.settings.max_bolus_u,
            max_correction_u=payload.settings.max_correction_u,
            round_step_u=payload.settings.round_step_u,
        )

        if payload.target_mgdl is None:
            slot_profile = getattr(payload.settings, payload.meal_slot)
            payload.target_mgdl = slot_profile.target

    elif payload.cr_g_per_u:
        from app.models.settings import (
            AutosensConfig,
            CalculatorConfig,
            CorrectionFactors,
            IOBConfig,
            MealFactors,
            NightscoutConfig,
            TargetRange,
            WarsawConfig,
        )

        cr_val = payload.cr_g_per_u
        isf_val = payload.isf_mgdl_per_u or 30.0

        cr_settings = MealFactors(breakfast=cr_val, lunch=cr_val, dinner=cr_val)
        isf_settings = CorrectionFactors(breakfast=isf_val, lunch=isf_val, dinner=isf_val)

        target_settings = TargetRange(low=70, mid=payload.target_mgdl or 100, high=180)

        iob_settings = IOBConfig(
            dia_hours=payload.dia_hours or 4.0,
            curve=payload.insulin_model or "walsh",
            peak_minutes=payload.insulin_peak_minutes or 75,
        )

        ns_settings = NightscoutConfig(
            enabled=bool(payload.nightscout and payload.nightscout.url),
            url=payload.nightscout.url if payload.nightscout else "",
            token=payload.nightscout.token if payload.nightscout else "",
        )

        warsaw_settings = WarsawConfig()
        if payload.warsaw_safety_factor is not None:
            warsaw_settings.safety_factor = payload.warsaw_safety_factor
        if payload.warsaw_safety_factor_dual is not None:
            warsaw_settings.safety_factor_dual = payload.warsaw_safety_factor_dual
        if payload.warsaw_trigger_threshold_kcal is not None:
            warsaw_settings.trigger_threshold_kcal = payload.warsaw_trigger_threshold_kcal

        calc_config = CalculatorConfig()
        if payload.use_fiber_deduction is not None:
            calc_config.subtract_fiber = payload.use_fiber_deduction
        if payload.fiber_factor is not None:
            calc_config.fiber_factor = payload.fiber_factor
        if payload.fiber_threshold is not None:
            calc_config.fiber_threshold_g = payload.fiber_threshold

        user_settings = UserSettings(
            cr=cr_settings,
            cf=isf_settings,
            targets=target_settings,
            iob=iob_settings,
            nightscout=ns_settings,
            warsaw=warsaw_settings,
            calculator=calc_config,
            autosens=AutosensConfig(enabled=payload.enable_autosens)
            if payload.enable_autosens is not None
            else AutosensConfig(),
            max_bolus_u=payload.max_bolus_u or 10.0,
            max_correction_u=payload.max_correction_u or 5.0,
            round_step_u=payload.round_step_u or 0.05,
        )

    else:
        from app.services.settings_service import get_user_settings_service

        user_settings = None
        if session:
            try:
                data = await get_user_settings_service(user.username, session)
                if data and data.get("settings"):
                    user_settings = UserSettings.migrate(data["settings"])
            except Exception as e:
                logger.warning(f"Failed to load settings from DB for bolus: {e}")

        if user_settings:
            invalid_limits = (
                user_settings.max_bolus_u <= 0
                or user_settings.max_correction_u < 0
                or user_settings.round_step_u < 0
            )
            invalid_ratios = any(
                getattr(user_settings.cr, slot, 0) <= 0
                for slot in ("breakfast", "lunch", "dinner", "snack")
            )
            if invalid_limits or invalid_ratios:
                logger.warning("Invalid settings from DB for bolus; using stored defaults.")
                user_settings = None

        if not user_settings:
            user_settings = store.load_settings()

    # 2. Resolve Nightscout Client
    ns_client: Optional[NightscoutClient] = None
    ns_config = user_settings.nightscout

    if payload.nightscout:
        ns_config.enabled = True
        ns_config.url = payload.nightscout.url
        ns_config.token = payload.nightscout.token
    elif session:
        try:
            db_ns_config = await get_ns_config(session, user.username)
            if db_ns_config and db_ns_config.enabled and db_ns_config.url:
                ns_config.enabled = True
                ns_config.url = db_ns_config.url
                ns_config.token = db_ns_config.api_secret
                logger.debug("Injected Nightscout config from DB for calculation.")
        except Exception as e:
            logger.warning(f"Failed to fetch NS config from DB: {e}")

    # 3. Resolve Glucose (manual override vs unified source resolver)
    resolved_bg: Optional[float] = payload.bg_mgdl
    reported_bg: Optional[float] = resolved_bg
    bg_source = "manual" if resolved_bg is not None else "none"
    bg_trend: Optional[str] = None
    bg_age_minutes: Optional[float] = None
    bg_is_stale: bool = False
    compression_flag = False
    compression_reason = None
    glucose_status = SourceStatus(
        source=bg_source,
        status="ok" if resolved_bg is not None else "unavailable",
        fetched_at=datetime.now(timezone.utc),
    )

    if resolved_bg is None and session:
        try:
            selected = await resolve_current_glucose(
                session,
                user.username,
                user_settings=user_settings,
                refresh_remote=True,
            )
            bg_source = selected.source
            bg_trend = selected.trend
            bg_age_minutes = selected.age_minutes
            bg_is_stale = selected.status == "stale"
            compression_flag = selected.is_compression
            compression_reason = selected.compression_reason
            glucose_status.source = selected.source
            glucose_status.status = selected.status
            if selected.is_compression:
                glucose_status.reason = "compression_suspected"
            elif selected.status == "conflict":
                glucose_status.reason = "source_conflict"
            elif not selected.usable_for_dosing and selected.bg_mgdl is not None:
                glucose_status.reason = "reading_not_usable_for_dosing"

            # Never feed stale, historical, uncertain or conflicting automatic
            # glucose into the correction component.
            reported_bg = selected.bg_mgdl
            resolved_bg = selected.bg_mgdl if selected.usable_for_dosing else None
        except Exception as e:
            logger.error("Unified glucose resolution failed in calc: %s", e)
            resolved_bg = None
            bg_source = "none"
            bg_trend = None
            bg_age_minutes = None
            bg_is_stale = False
            glucose_status.source = "none"
            glucose_status.status = "unavailable"
    if resolved_bg is None and bg_source == "none" and ns_config.enabled and ns_config.url:
        # Compatibility for request-scoped Nightscout credentials that are not
        # stored in the encrypted user table. Apply the same freshness gate.
        try:
            ns_client = NightscoutClient(
                base_url=ns_config.url,
                token=ns_config.token,
                timeout_seconds=5,
            )
            sgv = await ns_client.get_latest_sgv()
            reported_bg = float(sgv.sgv)
            measured_at = datetime.fromtimestamp(sgv.date / 1000, tz=timezone.utc)
            bg_age_minutes = max(
                0.0,
                (datetime.now(timezone.utc) - measured_at).total_seconds() / 60.0,
            )
            bg_source = "nightscout"
            bg_trend = sgv.direction
            bg_is_stale = bg_age_minutes > user_settings.glucose_sources.max_age_minutes
            glucose_status.source = bg_source
            glucose_status.status = "stale" if bg_is_stale else "ok"
            resolved_bg = None if bg_is_stale else float(sgv.sgv)
        except Exception as exc:
            logger.error("Stateless Nightscout glucose fallback failed: %s", exc)
            glucose_status.status = "unavailable"

    if ns_client is None and ns_config.enabled and ns_config.url:
        ns_client = NightscoutClient(
            base_url=ns_config.url,
            token=ns_config.token,
            timeout_seconds=5,
        )

    autosens_ratio = 1.0
    autosens_reason = None

    should_run_autosens = user_settings.autosens.enabled

    if should_run_autosens and session:
        try:
            from app.services.dynamic_isf_service import DynamicISFService, TDDDebugInfo

            # Get TDD ratio with debug info
            tdd_result = await DynamicISFService.calculate_dynamic_ratio(
                username=user.username,
                session=session,
                settings=user_settings,
                return_debug=True,
            )

            # Handle both return types (with or without debug)
            if isinstance(tdd_result, tuple):
                tdd_ratio, tdd_debug = tdd_result
            else:
                tdd_ratio = tdd_result
                tdd_debug = None

            local_ratio = 1.0
            local_reason = ""
            try:
                res = await AutosensService.calculate_autosens(
                    username=user.username,
                    session=session,
                    settings=user_settings,
                    record_run=persist_autosens_run,
                    compression_config=compression_config,
                )
                local_ratio = res.ratio
                if local_ratio != 1.0:
                    local_reason = f" + Local {res.reason}"
            except Exception:
                pass

            # Calculate hybrid ratio
            raw_hybrid = tdd_ratio * local_ratio
            autosens_ratio = max(
                user_settings.autosens.min_ratio,
                min(user_settings.autosens.max_ratio, raw_hybrid),
            )

            # Build detailed reason string
            autosens_reason = (
                f"Híbrido: TDD {tdd_ratio:.2f}x * Local {local_ratio:.2f}x"
            )

            # Add debug info if available
            if tdd_debug:
                autosens_reason += (
                    f" [TDD: Recent={tdd_debug.recent_tdd:.1f}U, "
                    f"Base={tdd_debug.baseline_tdd:.1f}U, "
                    f"Basal src={tdd_debug.basal_source}]"
                )

            logger.info(
                "Hybrid Autosens: ratio=%.2f (raw=%.3f), TDD=%.2f, Local=%.2f",
                autosens_ratio, raw_hybrid, tdd_ratio, local_ratio
            )
        except Exception as e:
            logger.error(f"Hybrid Autosens failed: {e}")
            autosens_reason = "Error (usando 1.0)"

    try:
        now = datetime.now(timezone.utc)
        iob_u, breakdown, iob_info, iob_warning = await compute_iob_from_sources(
            now,
            user_settings,
            ns_client,
            store,
            user_id=user.username,
            persist_cache=persist_iob_cache,
        )
        cob_total, cob_info, cob_source_status = await compute_cob_from_sources(
            now,
            ns_client,
            store,
            extra_entries=None,
            user_id=user.username,
        )
        iob_info.glucose_source_status = glucose_status
        assumptions: list[str] = []

        if iob_info.status == "unavailable" and not payload.confirm_iob_unknown:
            raise HTTPException(
                status_code=424,
                detail={
                    "error_code": "IOB_UNAVAILABLE_CONFIRM_REQUIRED",
                    "message": "IOB no disponible. Confirma el estado y aporta un IOB manual para continuar.",
                    "requires_confirmation": True,
                    "required_flag": "confirm_iob_unknown",
                    "iob": iob_info.model_dump(),
                    "cob": cob_info.model_dump(),
                    "treatments_source": iob_info.treatments_source_status.source
                    if iob_info.treatments_source_status
                    else "unknown",
                    "glucose_source": bg_source or "unknown",
                    "safe_alternatives": ["manual_mode"],
                },
            )

        if iob_info.status == "stale" and not payload.confirm_iob_stale:
            age_minutes = None
            if iob_info.last_updated_at:
                age_minutes = (now - iob_info.last_updated_at).total_seconds() / 60.0
            raise HTTPException(
                status_code=424,
                detail={
                    "error_code": "IOB_STALE_CONFIRM_REQUIRED",
                    "message": "IOB desactualizado. Confirma el estado y aporta un IOB manual; no se asumirá 0.",
                    "requires_confirmation": True,
                    "required_flag": "confirm_iob_stale",
                    "iob": iob_info.model_dump(),
                    "cob": cob_info.model_dump(),
                    "data_age_minutes": age_minutes,
                    "treatments_source": iob_info.treatments_source_status.source
                    if iob_info.treatments_source_status
                    else "unknown",
                    "glucose_source": bg_source or "unknown",
                    "safe_alternatives": ["manual_mode"],
                },
            )

        # IOB incierto: no asumir 0.0 (peligro de sobredosis)
        if iob_info.status in ["unavailable", "stale"]:
            if payload.manual_iob_u is not None:
                iob_for_calc = payload.manual_iob_u
                flag = "IOB_MANUAL_OVERRIDE"
                assumptions.append(flag)
                iob_info.assumptions.append(flag)
                iob_warning = f"IOB manual del usuario: {iob_for_calc:.2f} U"
                logger.info(f"Manual IOB override: {iob_for_calc} U (status={iob_info.status})")
            else:
                raise HTTPException(
                    status_code=424,
                    detail={
                        "error_code": "IOB_UNCERTAIN",
                        "message": "IOB no disponible. Introduce tu IOB estimado manualmente o espera a que el sistema se recupere.",
                        "requires_confirmation": True,
                        "required_flag": "manual_iob_u",
                        "iob": iob_info.model_dump(),
                        "cob": cob_info.model_dump(),
                        "treatments_source": iob_info.treatments_source_status.source
                        if iob_info.treatments_source_status
                        else "unknown",
                        "glucose_source": bg_source or "unknown",
                        "safe_alternatives": ["manual_mode", "wait_for_recovery"],
                    },
                )
        else:
            if iob_u is None:
                raise HTTPException(
                    status_code=424,
                    detail={
                        "error_code": "IOB_UNCERTAIN",
                        "message": "IOB no disponible. Introduce tu IOB estimado manualmente o espera a que el sistema se recupere.",
                        "required_flag": "manual_iob_u",
                        "iob": iob_info.model_dump(),
                        "cob": cob_info.model_dump(),
                        "safe_alternatives": ["manual_mode", "wait_for_recovery"],
                    },
                )
            iob_for_calc = iob_u

        if breakdown:
            try:
                latest = max(breakdown, key=lambda item: datetime.fromisoformat(item["ts"]))
                latest_ts = datetime.fromisoformat(latest["ts"])
                if latest_ts.tzinfo is None:
                    latest_ts = latest_ts.replace(tzinfo=timezone.utc)
                diff_min = int((now - latest_ts).total_seconds() / 60)
                if diff_min >= 0:
                    payload.last_bolus_minutes = diff_min
            except Exception as exc:
                logger.warning("Failed to derive last bolus time from IOB data: %s", exc)

        glucose_info = GlucoseUsed(
            # Only a value that passed freshness, conflict and source validation
            # is allowed into the dosing engine.
            mgdl=resolved_bg,
            source=bg_source,
            trend=bg_trend,
            age_minutes=bg_age_minutes,
            is_stale=bg_is_stale,
        )

        response = calculate_bolus_v2(
            request=payload,
            settings=user_settings,
            iob_u=iob_for_calc,
            glucose_info=glucose_info,
            autosens_ratio=autosens_ratio,
            autosens_reason=autosens_reason,
        )

        response.iob = iob_info
        response.cob = cob_info
        response.assumptions.extend(
            assumptions + (cob_info.assumptions if cob_info else [])
        )
        response.iob_u = round(iob_for_calc, 2)

        if iob_warning:
            response.warnings.append(iob_warning)
        if cob_info and cob_info.status in ["unavailable", "stale"]:
            response.warnings.append(
                "COB no disponible o desactualizado; revisa tratamientos recientes."
            )

        if resolved_bg is None:
            response.warnings.append(
                "⚠️ NO SE DETECTÓ GLUCOSA. El cálculo NO incluye corrección."
            )
        if compression_flag:
            warning = (
                "⚠️ Posible compresión detectada en CGM; verifica con medición capilar."
            )
            if compression_reason:
                warning = f"{warning} ({compression_reason})"
            response.warnings.append(warning)

        if breakdown:
            response.explain.append(f"   (IOB basado en {len(breakdown)} tratamientos):")
            now_ts = datetime.now(timezone.utc)
            for b in breakdown:
                try:
                    ts_dt = datetime.fromisoformat(b["ts"])
                    if ts_dt.tzinfo is None:
                        ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                    diff_min = int((now_ts - ts_dt).total_seconds() / 60)
                    time_label = (
                        f"Hace {diff_min} min"
                        if diff_min < 120
                        else f"Hace {diff_min // 60}h {diff_min % 60}m"
                    )
                except Exception:
                    time_label = b["ts"][11:16]

                response.explain.append(
                    f"    - {time_label}: {b['units']} U -> quedan {b['iob']:.2f} U"
                )

        return response

    finally:
        if ns_client:
            await ns_client.aclose()
