
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.treatment import Treatment
from app.models.settings import UserSettings
from app.services.math.basal import BasalModels

logger = logging.getLogger(__name__)

class DynamicISFService:
    """
    Calculates Dynamic ISF adjustment based on Weighted TDD (Total Daily Dose).
    Ratio = Weighted_Current_TDD / Reference_TDD
    DynISF = BaseISF / Ratio

    If Ratio > 1 (Using MORE insulin) -> ISF decreases (Stronger correction).
    If Ratio < 1 (Using LESS insulin) -> ISF increases (Weaker correction).
    """

    @staticmethod
    async def calculate_dynamic_ratio(
        username: str, 
        session: AsyncSession, 
        settings: UserSettings
    ) -> float:
        try:
            # 1. Calculate Historical TDD (Looking back 7 days)
            # We want daily buckets.
            now_utc = datetime.now(timezone.utc)
            start_7d = now_utc - timedelta(days=7)
            
            stmt = (
                select(Treatment)
                .where(Treatment.user_id == username)
                .where(Treatment.created_at >= start_7d.replace(tzinfo=None))
                # Note: created_at usually naive UTC in DB, caution with tz
            )
            res = await session.execute(stmt)
            rows = res.scalars().all()
            
            # Bucket by day
            daily_bolus = {}
            for r in rows:
                dt = r.created_at
                # rudimentary date key relative to now
                # Days ago: 0 to 6
                days_ago = (now_utc - dt.replace(tzinfo=timezone.utc)).days
                if days_ago < 0: days_ago = 0 # future safety
                if days_ago > 6: days_ago = 6
                
                daily_bolus[days_ago] = daily_bolus.get(days_ago, 0.0) + (r.insulin or 0.0)

            # 2. Add Basal to TDD
            # We assume basal schedule is constant for this estimation (simplified)
            # Or we should try to fetch actual basal history if available?
            # For robustness, we use the current scheduled basal total.
            daily_basal = 0.0
            
            # Using Basal Reminder Schedule as main source if available
            if settings.bot.proactive.basal.schedule:
                daily_basal = sum(item.units for item in settings.bot.proactive.basal.schedule)
            # Fallback legacy
            elif settings.tdd_u:
                # heuristic: basal is usually 40-50% of TDD in well managed.
                # But safer to just use settings.tdd_u as Reference TDD entirely if basal unknown.
                pass
            
            # 3. Calculate Weighted TDD
            # Weight: Today/Yesterday (0-1 days ago) = 60%, Past (2-6) = 40%
            # Actually DynamicISF typically uses:
            # Avg(Past 24h) * weight + Avg(Past 7d) * weight
            
            tdd_sum_7d = 0.0
            day_count = 0
            
            week_tdd_avg = 0.0
            
            for d in range(7):
                bolus = daily_bolus.get(d, 0.0)
                total = bolus + daily_basal
                if total > 0:
                    tdd_sum_7d += total
                    day_count += 1
            
            if day_count == 0:
                logger.warning("No TDD history found for DynamicISF.")
                return 1.0
                
            week_tdd_avg = tdd_sum_7d / day_count
            
            # Short term (last 24h) -> Day 0
            # Note: Day 0 in loop above is 'last 24h' roughly relative to Now? 
            # 'days_ago' logic is trunc(delta.days). 
            # 0 means < 24h separation? No, it means calendar days difference usually.
            # Let's be more precise for "Recent TDD".
            
            # Re-calculate exact last 24h sum
            recent_bolus_sum = sum(
                r.insulin or 0.0 for r in rows 
                if (now_utc - r.created_at.replace(tzinfo=timezone.utc)).total_seconds() <= 86400
            )
            recent_tdd = recent_bolus_sum + daily_basal
            
            # --- SAFETY GUARDRAIL ---
            # If recent TDD (24h) deviates significantly (>30%) from 7d Average, 
            # we likely have missing data or an anomaly. Unsafe to use Dynamic ISF.
            if week_tdd_avg > 5.0:
                deviation = abs(recent_tdd - week_tdd_avg) / week_tdd_avg
                if deviation > 0.30:
                    logger.warning(
                        f"DynamicISF Safety Trigger: TDD Deviation {deviation:.2%} > 30% "
                        f"(Recent={recent_tdd:.1f}, Avg={week_tdd_avg:.1f}). "
                        "Fallback to Ratio 1.0."
                    )
                    return 1.0

            # Weighted TDD
            # 60% Recent, 40% Week Trend (Responsiveness vs Stability)
            weighted_tdd = (recent_tdd * 0.6) + (week_tdd_avg * 0.4)
            
            # 4. Reference TDD
            # Ideally the user's "Settings TDD" (settings.tdd_u).
            # If not set, we use the 7-day average as the baseline "Normal".
            baseline_tdd = settings.tdd_u
            if not baseline_tdd or baseline_tdd <= 0:
                baseline_tdd = week_tdd_avg
                
            if baseline_tdd <= 5.0: # Too low to be valid or new user
                return 1.0
                
            # 5. Ratio calculation
            # Ratio = Current_Need / Baseline
            ratio = weighted_tdd / baseline_tdd
            
            # Safety Limits (Min 0.7, Max 1.3 usually safe)
            # Autosens limits from settings
            min_r = settings.autosens.min_ratio
            max_r = settings.autosens.max_ratio
            
            ratio = max(min_r, min(max_r, ratio))
            
            return round(ratio, 2)
            
        except Exception as e:
            logger.error(f"DynamicISF calc failed: {e}")
            return 1.0

