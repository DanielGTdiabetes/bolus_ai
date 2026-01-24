from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

from app.models.basal import BasalEntry
from app.models.forecast import (
    ForecastBasalInjection,
    ForecastEventBolus,
    ForecastEventCarbs,
    ForecastEvents,
    ForecastSimulateRequest,
    SimulationParams,
)
from app.models.settings import UserSettings
from app.services.forecast_engine import ForecastEngine

DEFAULT_SLOTS: tuple[str, ...] = ("breakfast", "lunch", "dinner")
DEFAULT_CARBS_GRID: tuple[int, ...] = (0, 15, 30, 60)
DEFAULT_BOLUS_GRID: tuple[int, ...] = (0, 2, 4, 6, 8, 12)

CLAMP_MIN = 20.0
CLAMP_MAX = 600.0


@dataclass(frozen=True)
class SweepConfig:
    slots: Sequence[str] = DEFAULT_SLOTS
    carbs_grid: Sequence[int] = DEFAULT_CARBS_GRID
    bolus_grid: Sequence[int] = DEFAULT_BOLUS_GRID
    start_bg: float = 120.0
    horizon_minutes: int = 240
    step_minutes: int = 5
    clamp_min: float = CLAMP_MIN
    clamp_max: float = CLAMP_MAX
    carbs_ignored_threshold: float = 10.0
    basal_drift_threshold: float = 30.0
    bolus_sensitivity_threshold: float = 5.0


def determine_onset_minutes(insulin_name: Optional[str]) -> int:
    if not insulin_name:
        return 10
    name = insulin_name.lower()
    if "fiasp" in name or "lyumjev" in name:
        return 5
    if any(x in name for x in ["novorapid", "humalog", "apidra", "rapid", "aspart", "lispro"]):
        return 15
    return 10


def _baseline_basal_units(settings: UserSettings) -> float:
    schedule = []
    if settings.bot and settings.bot.proactive and settings.bot.proactive.basal:
        schedule = settings.bot.proactive.basal.schedule or []
    if schedule:
        return float(sum(item.units for item in schedule if item.units))
    if settings.tdd_u:
        return float(settings.tdd_u * 0.5)
    return 0.0


def _build_basal_injection(entry: Optional[BasalEntry]) -> Optional[ForecastBasalInjection]:
    if not entry:
        return None
    duration_minutes = None
    if entry.effective_hours:
        duration_minutes = int(entry.effective_hours * 60)
    return ForecastBasalInjection(
        time_offset_min=0,
        units=float(entry.dose_u),
        type=entry.basal_type or "glargine",
        duration_minutes=duration_minutes,
    )


def _nearest_bg(series: Iterable, target_min: int) -> Optional[float]:
    series_list = list(series)
    if not series_list:
        return None
    nearest = min(series_list, key=lambda point: abs(point.t_min - target_min))
    return float(nearest.bg)


def _metrics_from_series(series: Iterable, start_bg: float, clamp_min: float, clamp_max: float) -> dict:
    series_list = list(series)
    bgs = [float(point.bg) for point in series_list]
    tmins = [int(point.t_min) for point in series_list]
    min_bg = min(bgs) if bgs else start_bg
    max_bg = max(bgs) if bgs else start_bg
    min_idx = bgs.index(min_bg) if bgs else 0
    t_min = tmins[min_idx] if tmins else 0
    bg_t30 = _nearest_bg(series_list, 30)
    bg_t60 = _nearest_bg(series_list, 60)
    bg_t120 = _nearest_bg(series_list, 120)
    bg_t180 = _nearest_bg(series_list, 180)
    bg_t15 = _nearest_bg(series_list, 15)
    slope_0_15 = None
    if bg_t15 is not None:
        slope_0_15 = (bg_t15 - start_bg) / 15.0
    clamp_hits = sum(1 for bg in bgs if bg <= clamp_min or bg >= clamp_max)
    return {
        "bg_min": min_bg,
        "bg_max": max_bg,
        "t_min": t_min,
        "bg_t30": bg_t30,
        "bg_t60": bg_t60,
        "bg_t120": bg_t120,
        "bg_t180": bg_t180,
        "slope_0_15": slope_0_15,
        "clamp_hits": clamp_hits,
        "delta_0_60": (bg_t60 - start_bg) if bg_t60 is not None else None,
    }


def _slot_value(settings_section, slot: str) -> float:
    return float(getattr(settings_section, slot))


def _summarize_flags(
    runs: list[dict],
    config: SweepConfig,
    carbs_focus: int = 30,
    bolus_low: int = 6,
    bolus_high: int = 12,
) -> dict:
    clamp_runs = [r for r in runs if (r["clamp_hits"] or 0) > 0]
    clamp_ratio = (len(clamp_runs) / len(runs)) if runs else 0.0
    clamp_domination = clamp_ratio > 0.2

    dose_low = next(
        (r for r in runs if r["carbs_g"] == carbs_focus and r["bolus_u"] == bolus_low),
        None,
    )
    dose_high = next(
        (r for r in runs if r["carbs_g"] == carbs_focus and r["bolus_u"] == bolus_high),
        None,
    )
    dose_sensitivity_score = None
    insensitive_to_bolus = False
    if dose_low and dose_high:
        dose_sensitivity_score = abs(dose_high["bg_min"] - dose_low["bg_min"])
        insensitive_to_bolus = dose_sensitivity_score < config.bolus_sensitivity_threshold

    no_carb_no_bolus = next(
        (r for r in runs if r["carbs_g"] == 0 and r["bolus_u"] == 0),
        None,
    )
    basal_drift_issue = False
    if no_carb_no_bolus and no_carb_no_bolus["delta_0_60"] is not None:
        basal_drift_issue = abs(no_carb_no_bolus["delta_0_60"]) >= config.basal_drift_threshold

    carbs_ignored = False
    carb_only = next(
        (r for r in runs if r["carbs_g"] == 60 and r["bolus_u"] == 0),
        None,
    )
    if carb_only and carb_only["delta_0_60"] is not None:
        carbs_ignored = carb_only["delta_0_60"] < config.carbs_ignored_threshold

    issue_detected = clamp_domination or insensitive_to_bolus or basal_drift_issue or carbs_ignored

    return {
        "issue_detected": issue_detected,
        "clamp_domination": clamp_domination,
        "clamp_ratio": clamp_ratio,
        "insensitive_to_bolus": insensitive_to_bolus,
        "dose_sensitivity_score": dose_sensitivity_score,
        "basal_drift_issue": basal_drift_issue,
        "carbs_ignored": carbs_ignored,
    }


def run_forecast_sweep(
    user_settings: UserSettings,
    user_id: str,
    output_dir: Path,
    basal_entry: Optional[BasalEntry] = None,
    config: SweepConfig = SweepConfig(),
    print_summary: bool = True,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = output_dir / f"forecast_sweep_{user_id}_{timestamp}.csv"
    json_path = output_dir / f"forecast_sweep_{user_id}_{timestamp}.json"

    baseline_basal_units = _baseline_basal_units(user_settings)
    basal_injection = _build_basal_injection(basal_entry)

    basal_cases = [
        {
            "name": "A_no_basal_injection",
            "basal_injections": [],
            "basal_daily_units": baseline_basal_units,
            "has_basal_injection": False,
        },
        {
            "name": "B_with_basal_injection",
            "basal_injections": [basal_injection] if basal_injection else [],
            "basal_daily_units": baseline_basal_units or (basal_entry.dose_u if basal_entry else 0.0),
            "has_basal_injection": basal_injection is not None,
        },
    ]

    rows: list[dict] = []
    summary: dict = {
        "user_id": user_id,
        "generated_at": timestamp,
        "slots": {},
    }

    for slot in config.slots:
        icr_slot = _slot_value(user_settings.cr, slot)
        isf_slot = _slot_value(user_settings.cf, slot)
        absorption_slot = _slot_value(user_settings.absorption, slot)
        target_bg = float(user_settings.targets.mid)
        dia_minutes = int(user_settings.iob.dia_hours * 60)
        insulin_peak_minutes = int(user_settings.iob.peak_minutes)
        insulin_model = user_settings.iob.curve
        onset_minutes = determine_onset_minutes(user_settings.insulin.name if user_settings.insulin else None)

        slot_summary = {}

        for basal_case in basal_cases:
            runs: list[dict] = []
            for carbs_g in config.carbs_grid:
                for bolus_u in config.bolus_grid:
                    events = ForecastEvents(
                        boluses=[
                            ForecastEventBolus(
                                time_offset_min=0,
                                units=float(bolus_u),
                                duration_minutes=0,
                            )
                        ]
                        if bolus_u > 0
                        else [],
                        carbs=[
                            ForecastEventCarbs(
                                time_offset_min=0,
                                grams=float(carbs_g),
                                absorption_minutes=absorption_slot,
                                icr=icr_slot,
                            )
                        ]
                        if carbs_g > 0
                        else [],
                        basal_injections=basal_case["basal_injections"],
                    )

                    sim_params = SimulationParams(
                        isf=isf_slot,
                        icr=icr_slot,
                        dia_minutes=dia_minutes,
                        carb_absorption_minutes=absorption_slot,
                        insulin_peak_minutes=insulin_peak_minutes,
                        insulin_model=insulin_model,
                        insulin_onset_minutes=onset_minutes,
                        basal_daily_units=float(basal_case["basal_daily_units"] or 0.0),
                        target_bg=target_bg,
                    )

                    payload = ForecastSimulateRequest(
                        start_bg=config.start_bg,
                        params=sim_params,
                        events=events,
                        horizon_minutes=config.horizon_minutes,
                        step_minutes=config.step_minutes,
                    )

                    response = ForecastEngine.calculate_forecast(payload)
                    metrics = _metrics_from_series(
                        response.series,
                        config.start_bg,
                        config.clamp_min,
                        config.clamp_max,
                    )

                    row = {
                        "slot": slot,
                        "basal_case": basal_case["name"],
                        "basal_injection_present": basal_case["has_basal_injection"],
                        "carbs_g": carbs_g,
                        "bolus_u": bolus_u,
                        "bg_min": metrics["bg_min"],
                        "t_min": metrics["t_min"],
                        "bg_t30": metrics["bg_t30"],
                        "bg_t60": metrics["bg_t60"],
                        "bg_t120": metrics["bg_t120"],
                        "bg_t180": metrics["bg_t180"],
                        "clamp_hits": metrics["clamp_hits"],
                        "slope_0_15": metrics["slope_0_15"],
                        "delta_0_60": metrics["delta_0_60"],
                    }
                    rows.append(row)
                    runs.append(row)

            matrix = {
                str(carbs): {
                    str(bolus): next(
                        (
                            r["bg_min"]
                            for r in runs
                            if r["carbs_g"] == carbs and r["bolus_u"] == bolus
                        ),
                        None,
                    )
                    for bolus in config.bolus_grid
                }
                for carbs in config.carbs_grid
            }

            flags = _summarize_flags(runs, config)
            slot_summary[basal_case["name"]] = {
                "matrix_bg_min": matrix,
                "flags": flags,
                "run_count": len(runs),
            }

        summary["slots"][slot] = slot_summary

    fieldnames = [
        "slot",
        "basal_case",
        "basal_injection_present",
        "carbs_g",
        "bolus_u",
        "bg_min",
        "t_min",
        "bg_t30",
        "bg_t60",
        "bg_t120",
        "bg_t180",
        "clamp_hits",
        "slope_0_15",
        "delta_0_60",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    json_path.write_text(
        __import__("json").dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if print_summary:
        print("Forecast sweep completed.")
        print(f"User: {user_id}")
        print(f"Runs: {len(rows)}")
        print(f"CSV: {csv_path}")
        print(f"JSON: {json_path}")
        for slot, slot_summary in summary["slots"].items():
            for basal_case, data in slot_summary.items():
                flags = data["flags"]
                print(
                    f"Slot {slot} | {basal_case} | issue_detected={flags['issue_detected']} "
                    f"clamp_ratio={flags['clamp_ratio']:.2f} "
                    f"insensitive_to_bolus={flags['insensitive_to_bolus']} "
                    f"carbs_ignored={flags['carbs_ignored']} "
                    f"basal_drift_issue={flags['basal_drift_issue']}"
                )

    return {
        "summary": summary,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
    }
