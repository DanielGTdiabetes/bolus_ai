
import logging
from datetime import datetime, date, timedelta, timezone
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Optional

from app.models.treatment import Treatment
from app.models.settings import UserSettings
from app.services.math.basal import BasalModels

logger = logging.getLogger(__name__)


class TDDDebugInfo:
    """Debug information for TDD calculation transparency."""
    def __init__(self):
        self.bolus_by_day: Dict[int, float] = {}
        self.basal_by_day: Dict[int, float] = {}
        self.basal_source: str = "unknown"
        self.recent_tdd: float = 0.0
        self.week_avg_tdd: float = 0.0
        self.weighted_tdd: float = 0.0
        self.baseline_tdd: float = 0.0
        self.final_ratio: float = 1.0
        self.safety_triggered: bool = False
        self.safety_reason: Optional[str] = None


class DynamicISFService:
    """
    Calculates Dynamic ISF adjustment based on Weighted TDD (Total Daily Dose).
    Ratio = Weighted_Current_TDD / Reference_TDD
    DynISF = BaseISF / Ratio

    If Ratio > 1 (Using MORE insulin) -> ISF decreases (Stronger correction).
    If Ratio < 1 (Using LESS insulin) -> ISF increases (Weaker correction).
    """

    @staticmethod
    async def _get_real_basal_doses(username: str, session: AsyncSession, days: int = 7) -> Dict[date, float]:
        """
        Fetch actual basal doses from basal_dose table.
        Returns dict mapping date -> dose_u
        """
        try:
            start_date = date.today() - timedelta(days=days)
            query = text("""
                SELECT effective_from, dose_u
                FROM basal_dose
                WHERE user_id = :user_id
                AND effective_from >= :start_date
                ORDER BY effective_from DESC, created_at DESC
            """)
            result = await session.execute(query, {"user_id": username, "start_date": start_date})
            rows = result.fetchall()

            # Build dict of date -> dose (latest entry per date wins)
            doses: Dict[date, float] = {}
            for row in rows:
                d = row.effective_from
                if d not in doses:  # Keep first (most recent) entry per date
                    doses[d] = float(row.dose_u)

            return doses
        except Exception as e:
            logger.warning(f"Failed to fetch real basal doses: {e}")
            return {}

    @staticmethod
    async def calculate_dynamic_ratio(
        username: str,
        session: AsyncSession,
        settings: UserSettings,
        return_debug: bool = False
    ) -> float:
        """
        Calculate dynamic ISF ratio based on TDD.

        Args:
            username: User identifier
            session: Database session
            settings: User settings
            return_debug: If True, returns tuple (ratio, TDDDebugInfo)
        """
        debug = TDDDebugInfo()

        try:
            # 1. Calculate Historical TDD (Looking back 7 days)
            now_utc = datetime.now(timezone.utc)
            today = now_utc.date()
            start_7d = now_utc - timedelta(days=7)

            stmt = (
                select(Treatment)
                .where(Treatment.user_id == username)
                .where(Treatment.created_at >= start_7d.replace(tzinfo=None))
            )
            res = await session.execute(stmt)
            rows = res.scalars().all()

            # Bucket boluses by day
            daily_bolus: Dict[int, float] = {}
            for r in rows:
                dt = r.created_at
                days_ago = (now_utc - dt.replace(tzinfo=timezone.utc)).days
                if days_ago < 0: days_ago = 0
                if days_ago > 6: days_ago = 6

                daily_bolus[days_ago] = daily_bolus.get(days_ago, 0.0) + (r.insulin or 0.0)

            debug.bolus_by_day = daily_bolus.copy()

            # 2. Get REAL basal doses from basal_dose table (PRIMARY SOURCE)
            real_basal_doses = await DynamicISFService._get_real_basal_doses(username, session, days=7)

            # 3. Determine daily basal for each day
            # Priority: Real dose > Schedule > settings.tdd_u heuristic
            daily_basal: Dict[int, float] = {}
            schedule_basal = 0.0

            if settings.bot.proactive.basal.schedule:
                schedule_basal = sum(item.units for item in settings.bot.proactive.basal.schedule)

            for days_ago in range(7):
                target_date = today - timedelta(days=days_ago)
                if target_date in real_basal_doses:
                    daily_basal[days_ago] = real_basal_doses[target_date]
                    debug.basal_source = "real_doses"
                elif schedule_basal > 0:
                    daily_basal[days_ago] = schedule_basal
                    if debug.basal_source == "unknown":
                        debug.basal_source = "schedule"
                elif settings.tdd_u and settings.tdd_u > 0:
                    # Heuristic: basal ~ 45% of TDD
                    daily_basal[days_ago] = settings.tdd_u * 0.45
                    if debug.basal_source == "unknown":
                        debug.basal_source = "tdd_heuristic"
                else:
                    daily_basal[days_ago] = 0.0
                    if debug.basal_source == "unknown":
                        debug.basal_source = "none"

            debug.basal_by_day = daily_basal.copy()

            logger.info(
                f"DynamicISF [{username}]: Basal source={debug.basal_source}, "
                f"Real doses found={len(real_basal_doses)}, Schedule={schedule_basal:.1f}U"
            )
            
            # 4. Calculate Weighted TDD
            tdd_sum_7d = 0.0
            day_count = 0

            for d in range(7):
                bolus = daily_bolus.get(d, 0.0)
                basal = daily_basal.get(d, 0.0)
                total = bolus + basal
                if total > 0:
                    tdd_sum_7d += total
                    day_count += 1

            if day_count == 0:
                logger.warning(f"No TDD history found for DynamicISF (user={username}).")
                debug.safety_triggered = True
                debug.safety_reason = "no_tdd_history"
                if return_debug:
                    return 1.0, debug
                return 1.0

            week_tdd_avg = tdd_sum_7d / day_count
            debug.week_avg_tdd = week_tdd_avg

            # Calculate exact last 24h sum
            recent_bolus_sum = sum(
                r.insulin or 0.0 for r in rows
                if (now_utc - r.created_at.replace(tzinfo=timezone.utc)).total_seconds() <= 86400
            )
            # Use today's basal (day 0) for recent TDD
            recent_basal = daily_basal.get(0, schedule_basal if schedule_basal > 0 else 0.0)
            recent_tdd = recent_bolus_sum + recent_basal
            debug.recent_tdd = recent_tdd

            # --- SAFETY GUARDRAIL ---
            if week_tdd_avg > 5.0:
                deviation = abs(recent_tdd - week_tdd_avg) / week_tdd_avg
                if deviation > 0.30:
                    logger.warning(
                        f"DynamicISF Safety Trigger: TDD Deviation {deviation:.2%} > 30% "
                        f"(Recent={recent_tdd:.1f}, Avg={week_tdd_avg:.1f}). "
                        "Fallback to Ratio 1.0."
                    )
                    debug.safety_triggered = True
                    debug.safety_reason = f"deviation_{deviation:.2%}"
                    if return_debug:
                        return 1.0, debug
                    return 1.0

            # Weighted TDD: 60% Recent, 40% Week Trend
            weighted_tdd = (recent_tdd * 0.6) + (week_tdd_avg * 0.4)
            debug.weighted_tdd = weighted_tdd

            # 5. Reference TDD
            baseline_tdd = settings.tdd_u
            if not baseline_tdd or baseline_tdd <= 0:
                baseline_tdd = week_tdd_avg

            debug.baseline_tdd = baseline_tdd

            if baseline_tdd <= 5.0:
                logger.warning(f"DynamicISF: baseline_tdd too low ({baseline_tdd:.1f})")
                debug.safety_triggered = True
                debug.safety_reason = "baseline_too_low"
                if return_debug:
                    return 1.0, debug
                return 1.0

            # 6. Ratio calculation
            ratio = weighted_tdd / baseline_tdd

            # Apply safety limits
            min_r = settings.autosens.min_ratio
            max_r = settings.autosens.max_ratio
            clamped_ratio = max(min_r, min(max_r, ratio))

            debug.final_ratio = round(clamped_ratio, 2)

            logger.info(
                f"DynamicISF [{username}]: Recent TDD={recent_tdd:.1f}, "
                f"Week Avg={week_tdd_avg:.1f}, Weighted={weighted_tdd:.1f}, "
                f"Baseline={baseline_tdd:.1f}, Ratio={clamped_ratio:.2f}"
            )

            if return_debug:
                return round(clamped_ratio, 2), debug
            return round(clamped_ratio, 2)

        except Exception as e:
            logger.error(f"DynamicISF calc failed: {e}")
            debug.safety_triggered = True
            debug.safety_reason = f"exception: {e}"
            if return_debug:
                return 1.0, debug
            return 1.0

