from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Sequence

from app.models.settings import UserSettings
from app.services.store import DataStore

logger = logging.getLogger(__name__)


@dataclass
class InsulinActionProfile:
    dia_hours: float
    curve: Literal["walsh", "bilinear"]
    peak_minutes: int = 75


def _clamp(value: float, min_value: float = 0.0, max_value: float | None = None) -> float:
    if max_value is not None:
        value = min(value, max_value)
    return max(value, min_value)


def _parse_timestamp(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def insulin_activity_fraction(t_minutes: float, profile: InsulinActionProfile) -> float:
    dia_minutes = profile.dia_hours * 60
    if t_minutes <= 0:
        return 1.0
    if t_minutes >= dia_minutes:
        return 0.0

    if profile.curve == "bilinear":
        peak = max(1, profile.peak_minutes)
        if peak >= dia_minutes:
            peak = dia_minutes / 2
        # Linear decay to mid-point at the peak, then faster decay to DIA
        slope1 = 0.5 / peak
        slope2 = 0.5 / (dia_minutes - peak)
        if t_minutes <= peak:
            remaining = 1.0 - slope1 * t_minutes
        else:
            remaining = 0.5 - slope2 * (t_minutes - peak)
        return _clamp(remaining)

    # Smoothstep curve used as a stable approximation of the Walsh IOB model.
    # It provides a smooth, monotonic decay from 1.0 at t=0 to 0.0 at DIA with
    # zero slope at both ends, avoiding oscillations without external libs.
    x = t_minutes / dia_minutes
    smooth = 1 - (3 * x**2 - 2 * x**3)
    return _clamp(smooth)


def compute_iob(now: datetime, boluses: Sequence[dict[str, float]], profile: InsulinActionProfile) -> float:
    total = 0.0
    for bolus in boluses:
        ts_raw = bolus.get("ts")
        units = float(bolus.get("units", 0))
        if not ts_raw or units <= 0:
            continue
        ts = _parse_timestamp(str(ts_raw))
        elapsed = (now - ts).total_seconds() / 60
        fraction = insulin_activity_fraction(elapsed, profile)
        total += units * fraction
    return max(total, 0.0)


def _boluses_from_events(events: list[dict]) -> list[dict[str, float]]:
    boluses: list[dict[str, float]] = []
    for event in events:
        if event.get("type") != "bolus":
            continue
        units = float(event.get("units", 0))
        ts = event.get("ts")
        if units > 0 and ts:
            boluses.append({"ts": ts, "units": units})
    return boluses


def _boluses_from_treatments(treatments) -> list[dict[str, float]]:
    boluses: list[dict[str, float]] = []
    for treatment in treatments:
        units = getattr(treatment, "insulin", None)
        ts = getattr(treatment, "created_at", None)
        if units is None or ts is None:
            continue
        boluses.append({"ts": ts.isoformat(), "units": float(units)})
    return boluses


async def compute_iob_from_sources(
    now: datetime,
    settings: UserSettings,
    nightscout_client,
    data_store: DataStore,
) -> tuple[float, list[dict[str, float]]]:
    profile = InsulinActionProfile(
        dia_hours=settings.iob.dia_hours,
        curve=settings.iob.curve,
        peak_minutes=settings.iob.peak_minutes,
    )

    boluses: list[dict[str, float]] = []
    breakdown: list[dict[str, float]] = []

    if nightscout_client:
        try:
            hours = max(1, math.ceil(settings.iob.dia_hours))
            treatments = await nightscout_client.get_recent_treatments(hours=hours)
            boluses.extend(_boluses_from_treatments(treatments))
        except Exception as exc:  # pragma: no cover - network failure paths
            logger.warning("Nightscout treatments unavailable", extra={"error": str(exc)})

    if not boluses:
        boluses.extend(_boluses_from_events(data_store.load_events()))

    total = 0.0
    for bolus in boluses:
        ts_raw = bolus.get("ts")
        units = float(bolus.get("units", 0))
        if not ts_raw:
            continue
        ts = _parse_timestamp(str(ts_raw))
        elapsed = (now - ts).total_seconds() / 60
        fraction = insulin_activity_fraction(elapsed, profile)
        contribution = max(units * fraction, 0.0)
        total += contribution
        breakdown.append({"ts": ts.isoformat(), "units": units, "iob": contribution})

    breakdown.sort(key=lambda item: item["ts"], reverse=True)
    return max(total, 0.0), breakdown
