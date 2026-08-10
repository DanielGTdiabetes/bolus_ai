from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from app.models.settings import UserSettings
from app.services.smart_filter import FilterConfig


# Guardrails that are intended to neutralize dynamic dosing, not merely one
# component of the hybrid Autosens calculation.
BLOCKING_AUTOSENS_FLAGS = frozenset({"recent_hypos"})


@dataclass(frozen=True)
class HybridAutosensDecision:
    ratio: float
    raw_ratio: float
    blocked: bool
    reason: str
    blocking_flags: tuple[str, ...] = ()


def build_compression_config(settings: UserSettings) -> FilterConfig:
    """Build the same compression policy used by the dedicated Autosens API."""
    ns = settings.nightscout
    return FilterConfig(
        enabled=ns.filter_compression,
        night_start_hour=ns.filter_night_start_hour,
        night_end_hour=ns.filter_night_end_hour,
        treatments_lookback_minutes=ns.treatments_lookback_minutes,
    )


def combine_hybrid_autosens(
    *,
    tdd_ratio: float,
    local_ratio: float,
    min_ratio: float,
    max_ratio: float,
    local_reason_flags: Iterable[str] = (),
    local_error: Optional[str] = None,
) -> HybridAutosensDecision:
    """Combine TDD and local Autosens conservatively.

    A clinical guardrail such as recent hypoglycaemia applies to the entire
    dynamic adjustment. Otherwise TDD could re-introduce an aggressive change
    after the local component had deliberately returned 1.0 for safety.

    Unexpected failure of the local component also fails neutral (1.0) rather
    than silently turning the configured hybrid algorithm into TDD-only dosing.
    """
    if min_ratio <= 0 or max_ratio <= 0 or min_ratio > max_ratio:
        raise ValueError("Invalid Autosens ratio bounds")

    if local_error:
        return HybridAutosensDecision(
            ratio=1.0,
            raw_ratio=tdd_ratio,
            blocked=True,
            reason=f"Autosens neutralizado: componente local no disponible ({local_error})",
        )

    flags = tuple(sorted(set(local_reason_flags).intersection(BLOCKING_AUTOSENS_FLAGS)))
    if flags:
        return HybridAutosensDecision(
            ratio=1.0,
            raw_ratio=tdd_ratio * local_ratio,
            blocked=True,
            reason=f"Autosens neutralizado por guardrail: {', '.join(flags)}",
            blocking_flags=flags,
        )

    raw_ratio = tdd_ratio * local_ratio
    ratio = max(min_ratio, min(max_ratio, raw_ratio))
    return HybridAutosensDecision(
        ratio=ratio,
        raw_ratio=raw_ratio,
        blocked=False,
        reason=f"Híbrido: TDD {tdd_ratio:.2f}x * Local {local_ratio:.2f}x = {ratio:.2f}x",
    )
