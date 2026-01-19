from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2, GlucoseUsed
from app.models.iob import SourceStatus
from app.models.settings import UserSettings
from app.services.autosens_service import AutosensService
from app.services.bolus_engine import calculate_bolus_v2
from app.services.iob import compute_cob_from_sources, compute_iob_from_sources
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config
from app.services.smart_filter import CompressionDetector, FilterConfig
from app.services.store import DataStore

logger = logging.getLogger(__name__)


async def calculate_bolus_stateless_service(
    payload: BolusRequestV2,
    *,
    store: DataStore,
    user: CurrentUser,
    session: Optional[AsyncSession],
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
            peak_minutes=payload.settings.insulin_peak_minutes,
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
            curve="walsh",
            peak_minutes=75,
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

    compression_config = FilterConfig(
        enabled=user_settings.nightscout.filter_compression,
        night_start_hour=user_settings.nightscout.filter_night_start_hour,
        night_end_hour=user_settings.nightscout.filter_night_end_hour,
        treatments_lookback_minutes=user_settings.nightscout.treatments_lookback_minutes,
    )

    # 3. Resolve Glucose (Manual vs Nightscout)
    resolved_bg: Optional[float] = payload.bg_mgdl
    bg_source: Literal["manual", "nightscout", "none"] = (
        "manual" if resolved_bg is not None else "none"
    )
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

    if resolved_bg is None and ns_config.enabled and ns_config.url:
        logger.info(f"Attempting to fetch BG from Nightscout: {ns_config.url}")
        try:
            ns_client = NightscoutClient(
                base_url=ns_config.url,
                token=ns_config.token,
                timeout_seconds=5,
            )
            entries = []
            if compression_config.enabled:
                end_dt = datetime.now(timezone.utc)
                start_dt = end_dt - timedelta(minutes=60)
                entries = await ns_client.get_sgv_range(start_dt, end_dt, count=12)

            if entries:
                entries.sort(key=lambda x: x.date)
                sgv = entries[-1]
            else:
                sgv = await ns_client.get_latest_sgv()

            resolved_bg = float(sgv.sgv)
            bg_source = "nightscout"
            bg_trend = sgv.direction
            glucose_status.source = "nightscout"

            if compression_config.enabled and len(entries) > 1:
                lookback_hours = max(
                    1, math.ceil(compression_config.treatments_lookback_minutes / 60)
                )
                treatments = await ns_client.get_recent_treatments(
                    hours=lookback_hours, limit=10
                )
                detector = CompressionDetector(config=compression_config)
                processed = detector.detect(
                    [e.model_dump() for e in entries],
                    [t.model_dump() for t in treatments],
                )
                if processed:
                    last_proc = processed[-1]
                    if last_proc.get("date") == sgv.date:
                        compression_flag = last_proc.get("is_compression", False)
                        compression_reason = last_proc.get("compression_reason")
                        if compression_flag:
                            glucose_status.reason = "compression_suspected"

            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            diff_ms = now_ms - sgv.date
            diff_min = diff_ms / 60000.0

            bg_age_minutes = diff_min
            if diff_min > 10:
                bg_is_stale = True
                glucose_status.status = "stale"
            else:
                glucose_status.status = "ok"

            logger.info(
                "Nightscout fetch success: %s mg/dL, age=%.1fm", resolved_bg, diff_min
            )

        except Exception as e:
            logger.error(f"Nightscout fetch failed in calc: {e}")
            bg_source = "none"

    db_events = []
    if session:
        try:
            from app.models.treatment import Treatment as DBTreatment
            from sqlalchemy import select

            stmt = (
                select(DBTreatment)
                .where(DBTreatment.user_id == user.username)
                .order_by(DBTreatment.created_at.desc())
                .limit(50)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            for row in rows:
                if row.insulin and row.insulin > 0:
                    created_iso = row.created_at.isoformat()
                    if not created_iso.endswith("Z") and "+" not in created_iso:
                        created_iso += "Z"
                    db_events.append({"ts": created_iso, "units": float(row.insulin)})
        except Exception as db_err:
            logger.error(f"Failed to fetch DB events for IOB: {db_err}")

    if db_events:
        try:
            latest = db_events[0]
            lat_ts = datetime.fromisoformat(latest["ts"])
            if lat_ts.tzinfo is None:
                lat_ts = lat_ts.replace(tzinfo=timezone.utc)

            now_ts = datetime.now(timezone.utc)
            diff_min = int((now_ts - lat_ts).total_seconds() / 60)

            if diff_min >= 0:
                payload.last_bolus_minutes = diff_min
                logger.info(
                    "Safety: Detected last bolus %s min ago (%s U)",
                    diff_min,
                    latest["units"],
                )
        except Exception as e:
            logger.warning(f"Failed to calc last bolus time: {e}")

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
            from app.services.dynamic_isf_service import DynamicISFService

            tdd_ratio = await DynamicISFService.calculate_dynamic_ratio(
                username=user.username,
                session=session,
                settings=user_settings,
            )

            local_ratio = 1.0
            local_reason = ""
            try:
                res = await AutosensService.calculate_autosens(
                    username=user.username,
                    session=session,
                    settings=user_settings,
                    record_run=True,
                    compression_config=compression_config,
                )
                local_ratio = res.ratio
                if local_ratio != 1.0:
                    local_reason = f" + Local {res.reason}"
            except Exception:
                pass

            autosens_ratio = tdd_ratio * local_ratio

            autosens_ratio = max(
                user_settings.autosens.min_ratio,
                min(user_settings.autosens.max_ratio, autosens_ratio),
            )

            autosens_reason = (
                f"Híbrido: TDD {tdd_ratio:.2f}x * Local {local_ratio:.2f}x"
            )

            logger.info("Hybrid Autosens: %s (%s)", autosens_ratio, autosens_reason)
        except Exception as e:
            logger.error(f"Hybrid Autosens failed: {e}")
            autosens_reason = "Error (usando 1.0)"

    try:
        now = datetime.now(timezone.utc)
        iob_u, breakdown, iob_info, iob_warning = await compute_iob_from_sources(
            now, user_settings, ns_client, store, extra_boluses=db_events
        )
        cob_total, cob_info, cob_source_status = await compute_cob_from_sources(
            now, ns_client, store, extra_entries=None
        )
        iob_info.glucose_source_status = glucose_status
        assumptions: list[str] = []

        if iob_info.status == "unavailable" and not payload.confirm_iob_unknown:
            raise HTTPException(
                status_code=424,
                detail={
                    "error_code": "IOB_UNAVAILABLE_CONFIRM_REQUIRED",
                    "message": "IOB/COB no disponible (treatments). Confirma para calcular sin IOB.",
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
                    "message": "IOB/COB desactualizado. Confirma para calcular asumiendo IOB=0.",
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

        iob_for_calc = iob_u if iob_u is not None else 0.0
        if iob_info.status in ["unavailable", "stale"]:
            flag = (
                "IOB_ASSUMED_ZERO_DUE_TO_UNAVAILABLE"
                if iob_info.status == "unavailable"
                else "IOB_ASSUMED_ZERO_DUE_TO_STALE"
            )
            assumptions.append(flag)
            iob_info.assumptions.append(flag)
            iob_for_calc = 0.0
            iob_warning = (
                iob_warning or "IOB no disponible; se asumió 0 U tras confirmación explícita."
            )

        glucose_info = GlucoseUsed(
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
