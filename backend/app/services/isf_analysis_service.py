import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.isf import IsfAnalysisResponse, IsfBucketStat, IsfEvent, IsfRunSummary
from app.models.isf_run import IsfRun
from app.models.schemas import Treatment, NightscoutSGV
from app.services.nightscout_client import NightscoutClient
from app.services.iob import compute_iob, InsulinActionProfile
from app.services.smart_filter import CompressionDetector, FilterConfig

logger = logging.getLogger(__name__)

BUCKETS = {
    "madrugada": (0, 6),
    "morn": (6, 12),
    "afternoon": (12, 18),
    "night": (18, 24)
}

BUCKET_LABELS = {
    "madrugada": "Madrugada (00-06)",
    "morn": "Mañana (06-12)",
    "afternoon": "Tarde (12-18)",
    "night": "Noche (18-24)"
}

RECENT_HYPO_HOURS = 12
CGM_GAP_MINUTES = 25
MAX_SLOPE_MGDL_PER_MIN = 5.0

class IsfAnalysisService:
    def __init__(
        self,
        ns_client: NightscoutClient,
        current_cf_settings: dict,
        profile_settings: dict,
        compression_config: Optional[FilterConfig] = None,
        db_session: Optional[AsyncSession] = None,
    ):
        self.ns = ns_client
        self.current_cf = current_cf_settings
        self.profile = InsulinActionProfile(
            dia_hours=float(profile_settings.get("dia_hours", 4.0)),
            curve=profile_settings.get("curve", "walsh"),
            peak_minutes=int(profile_settings.get("peak_minutes", 75))
        )
        self.compression_detector = (
            CompressionDetector(compression_config)
            if compression_config and compression_config.enabled
            else None
        )
        self.db_session = db_session

    def _get_bucket(self, dt: datetime) -> str:
        # User defined buckets: 0-6, 6-12, 12-18, 18-24
        # Adjust for local time? 
        # Usually treatments are UTC. We should convert to User Local Time?
        # User is in Europe/Madrid approx (based on "Madrugada" and log).
        # We need a timezone offset. Assuming inputs are UTC, we ideally convert to timezone.
        # But for now we use UTC hour or assume the input ts is offset-aware?
        # Nightscout treatments have `created_at` which is timezone aware.
        # We'll use the hour from that directly (assuming it reflects local time info or we assume UTC+1/2?)
        # Ideally we pass timezone info or use simple UTC+1 assumption.
        # NOTE: If ns_client returns UTC datetimes (which it does), the hour is UTC.
        # "Madrugada" at 00 UTC is 01/02 AM Local.
        # We will use UTC+1 (CET) as rough default or +2 (CEST).
        # Better: Rely on `created_at` if it has offset. The model converts to UTC.
        # We will shift by +1h fixed for now (simple) or assume user config.
        # Actually, let's just use UTC hour for simplicity unless user provided offset.
        # NOTE: 00-06 UTC is 01-07 Local. Close enough.
        h = dt.hour
        for k, (start, end) in BUCKETS.items():
            if start <= h < end:
                return k
        return "madrugada"

    def _get_configured_isf(self, bucket: str) -> float:
        mapping = {
            "morn": "breakfast",
            "afternoon": "lunch",
            "night": "dinner",
            "madrugada": "dinner" # Fallback
        }
        key = mapping.get(bucket, "lunch")
        return float(self.current_cf.get(key, 30.0))

    def _get_sgv_window(self, sgv_entries: List[dict], start_dt: datetime, end_dt: datetime) -> List[dict]:
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        window_entries = [e for e in sgv_entries if start_ms <= e["date"] <= end_ms]
        window_entries.sort(key=lambda e: e["date"])
        return window_entries

    def _has_cgm_gap(self, window_entries: List[dict], start_dt: datetime, end_dt: datetime) -> bool:
        if not window_entries:
            return True
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        prev_ms = start_ms
        for entry in window_entries:
            gap_minutes = (entry["date"] - prev_ms) / 60000.0
            if gap_minutes > CGM_GAP_MINUTES:
                return True
            prev_ms = entry["date"]
        final_gap = (end_ms - prev_ms) / 60000.0
        return final_gap > CGM_GAP_MINUTES

    def _has_unreliable_slope(self, window_entries: List[dict]) -> bool:
        sustained_count = 0
        for prev, curr in zip(window_entries, window_entries[1:]):
            dt_minutes = (curr["date"] - prev["date"]) / 60000.0
            if dt_minutes <= 0:
                continue
            slope = abs((curr["sgv"] - prev["sgv"]) / dt_minutes)
            if slope > MAX_SLOPE_MGDL_PER_MIN:
                sustained_count += 1
                if sustained_count >= 2:
                    return True
            else:
                sustained_count = 0
        return False

    async def _record_run(
        self,
        user_id: str,
        days: int,
        n_events: int,
        recommendation: Optional[str],
        diff_percent: Optional[float],
        flags: List[str],
    ) -> None:
        if not self.db_session:
            return
        run = IsfRun(
            user_id=user_id,
            timestamp=datetime.now(timezone.utc),
            days=days,
            n_events=n_events,
            recommendation=recommendation,
            diff_percent=diff_percent,
            flags=flags,
        )
        self.db_session.add(run)
        await self.db_session.commit()

    async def _get_recent_runs(self, user_id: str, limit: int = 5) -> List[IsfRunSummary]:
        if not self.db_session:
            return []
        result = await self.db_session.execute(
            select(IsfRun)
            .where(IsfRun.user_id == user_id)
            .order_by(IsfRun.timestamp.desc())
            .limit(limit)
        )
        runs = result.scalars().all()
        return [
            IsfRunSummary(
                timestamp=run.timestamp,
                days=run.days,
                n_events=run.n_events,
                recommendation=run.recommendation,
                diff_percent=run.diff_percent,
                flags=run.flags or [],
            )
            for run in runs
        ]

    async def run_analysis(self, user_id: str, days: int = 14) -> IsfAnalysisResponse:
        logger.info(f"Starting ISF Analysis for user {user_id}, days={days}")
        
        # 1. Fetch Data
        # We fetch 24h * days
        now_utc = datetime.now(timezone.utc)
        treatments = await self.ns.get_recent_treatments(hours=days*24, limit=2000)
        
        # Fetch SGV (Try to get ample range)
        # 14 days of SGV is ~4032 points.
        sgv_start = now_utc - timedelta(days=days) - timedelta(hours=4) # Buffer
        sgv_data = await self.ns.get_sgv_range(sgv_start, now_utc, count=5000)
        
        # Sort SGV by date ascending
        sgv_data.sort(key=lambda x: x.date)

        sgv_entries = [e.model_dump() for e in sgv_data]
        # Optional: detect suspected compression lows for analysis quality only
        if self.compression_detector and len(sgv_entries) > 1:
            treatments_dicts = [t.model_dump() for t in treatments]
            sgv_entries = self.compression_detector.detect(sgv_entries, treatments_dicts)

        recent_hypo_cutoff = now_utc - timedelta(hours=RECENT_HYPO_HOURS)
        recent_hypo_cutoff_ms = int(recent_hypo_cutoff.timestamp() * 1000)
        blocked_recent_hypo = any(
            e["date"] >= recent_hypo_cutoff_ms and e["sgv"] < 70
            for e in sgv_entries
        )
        global_reason_flags = ["recent_hypo"] if blocked_recent_hypo else []
        
        # Helper to find SGV at time
        # sgv.date is epoch ms
        def get_bg_at(dt: datetime, window_minutes=10) -> Optional[int]:
            target_ms = int(dt.timestamp() * 1000)
            window_ms = window_minutes * 60 * 1000
            
            # Binary search or simple scan? Scan is fast enough for 5k items
            # Optimization: could index
            closest = None
            min_diff = float("inf")
            
            for s in sgv_entries:
                diff = abs(s["date"] - target_ms)
                if diff < min_diff and diff < window_ms:
                    min_diff = diff
                    closest = s
            
            return int(closest["sgv"]) if closest else None

        # Filter Candidates
        candidates = []
        cutoff_time = now_utc - timedelta(hours=4) # Can't analyze if too recent
        
        for t in treatments:
            if not t.created_at: continue
            if t.created_at > cutoff_time: continue
            if not t.insulin or t.insulin <= 0.1: continue # Ignore micro-boluses < 0.1
            if t.carbs and t.carbs > 0: continue
            
            # Exclude Alcohol/Sick (User Request)
            if t.notes and any(x in t.notes.lower() for x in ['alcohol', 'sick', 'enfermedad']):
                continue
            
            candidates.append(t)
            
        clean_events: List[IsfEvent] = []
        
        bolus_history = [{"ts": x.created_at.isoformat(), "units": x.insulin} for x in treatments if x.insulin]

        for t in candidates:
            # 1. Check Noise
            valid = True
            reason = None
            
            t_start = t.created_at
            t_end = t_start + timedelta(hours=4) # 4h window
            
            # Check overlap
            for other in treatments:
                if not other.created_at: continue
                if other.id == t.id: continue
                
                if t_start < other.created_at < t_end:
                     if (other.carbs and other.carbs > 0) or (other.insulin and other.insulin > 0.1):
                        valid = False
                        reason = "Actividad en ventana 4h"
                        break
            
            if not valid: continue
            
            # 2. Check IOB (Stacking)
            iob_curr = compute_iob(t_start, bolus_history, self.profile)
            if iob_curr > 1.5: # User: "Exclude high IOB". 1.5U is reasonable safe guard.
                valid = False
                reason = f"Stacking (IOB={iob_curr:.1f}U)"
                
            if not valid: continue
            
            # 3. Deltas
            bg_start = get_bg_at(t_start)
            bg_end = get_bg_at(t_end)
            
            if not bg_start or not bg_end:
                # valid = False
                # reason = "Datos CGM faltantes"
                continue # Skip efficiently

            reason_flags = []
            window_entries = self._get_sgv_window(sgv_entries, t_start, t_end)
            if any(e.get("is_compression") for e in window_entries):
                reason_flags.append("compression")
            if self._has_cgm_gap(window_entries, t_start, t_end):
                reason_flags.append("cgm_gap")
            if self._has_unreliable_slope(window_entries):
                reason_flags.append("unreliable_cgm")
            quality_ok = len(reason_flags) == 0
                
            delta = bg_start - bg_end # Positive means Drop (Start 200, End 100 => Delta 100)
            # User Formula: ISF = DeltaBG / Units
            
            # Safety: If units is very small, ISF explodes.
            if t.insulin < 0.5:
                # Avoid analyzing micro-corrections which have high noise
                continue
                
            isf_obs = delta / t.insulin
            
            bucket = self._get_bucket(t_start)
            
            event = IsfEvent(
                id=t.id or "unknown",
                timestamp=t_start,
                correction_units=t.insulin,
                bg_start=bg_start,
                bg_end=bg_end,
                bg_delta=delta,
                isf_observed=round(isf_obs, 1),
                iob=round(iob_curr, 2),
                bucket=bucket,
                valid=quality_ok,
                reason=None,
                quality_ok=quality_ok,
                reason_flags=reason_flags
            )
            clean_events.append(event)
            
        # Aggregate
        bucket_stats = []
        
        for bucket_key, label in BUCKET_LABELS.items():
            events = [e for e in clean_events if e.bucket == bucket_key and e.quality_ok]
            current_isf = self._get_configured_isf(bucket_key)
            
            count = len(events)
            
            stat = IsfBucketStat(
                bucket=bucket_key,
                label=label,
                events_count=count,
                current_isf=current_isf,
                change_ratio=0.0,
                status="insufficient_data",
                median_isf=None,
                confidence="low"
            )
            
            if count >= 3: # Lowered from 6 to allow more results (Confidence scaled)
                isf_vals = [e.isf_observed for e in events]
                median_val = statistics.median(isf_vals)
                stat.median_isf = median_val
                
                # Rule: > +15% => Stronger (Wait)
                # Formula: (Observed - Current) / Current
                # Example: Obs=80, Curr=50. (80-50)/50 = 0.6 => +60%.
                # Obs=80 means 1U drops 80. Curr=50 means 1U drops 50.
                # Reality is "Stronger Drop" per unit => We are "Too Sensitive".
                # We need to INCREASE ISF number to correct less.
                
                diff_ratio = (median_val - current_isf) / current_isf
                stat.change_ratio = round(diff_ratio, 2)
                
                if diff_ratio > 0.15:
                    stat.status = "strong_drop" # Insulin drops MORE than expected
                    stat.suggestion_type = "increase" # Increase ISF number
                    
                    # Suggestion cap: 5-10% change max
                    suggested = current_isf * 1.05 # Start conservative 5%
                    # Better: If diff is massive (e.g. 50%), maybe go 10%?
                    if diff_ratio > 0.30:
                        suggested = current_isf * 1.10
                    
                    stat.suggested_isf = round(suggested, 1)
                    stat.confidence = "high" if count > 10 else "medium"
                    
                elif diff_ratio < -0.15:
                    # Example: Obs=30, Curr=50. (30-50)/50 = -0.4 (-40%).
                    # Insulin drops LESS. We are resistant.
                    # We need to DECREASE ISF number to give MORE insulin.
                    if blocked_recent_hypo:
                        stat.status = "blocked_recent_hypo"
                        stat.suggestion_type = None
                        stat.suggested_isf = None
                        stat.confidence = "low"
                    else:
                        stat.status = "weak_drop"
                        stat.suggestion_type = "decrease"
                        
                        suggested = current_isf * 0.95
                        if diff_ratio < -0.30:
                            suggested = current_isf * 0.90
                            
                        stat.suggested_isf = round(suggested, 1)
                        stat.confidence = "high" if count > 10 else "medium"
                else:
                    stat.status = "ok"
                    stat.confidence = "high"
            
            bucket_stats.append(stat)

        valid_events_count = len([e for e in clean_events if e.quality_ok])
        blocked_stat = next((s for s in bucket_stats if s.status == "blocked_recent_hypo"), None)
        actionable_stats = [s for s in bucket_stats if s.suggestion_type in ("increase", "decrease")]
        recommendation = None
        diff_percent = None
        if blocked_stat:
            recommendation = "blocked_recent_hypo"
            diff_percent = round(blocked_stat.change_ratio * 100, 1)
        elif actionable_stats:
            best_stat = max(actionable_stats, key=lambda s: abs(s.change_ratio))
            recommendation = best_stat.suggestion_type
            diff_percent = round(best_stat.change_ratio * 100, 1)
        else:
            recommendation = "none"

        await self._record_run(
            user_id=user_id,
            days=days,
            n_events=valid_events_count,
            recommendation=recommendation,
            diff_percent=diff_percent,
            flags=global_reason_flags,
        )
        runs = await self._get_recent_runs(user_id)

        return IsfAnalysisResponse(
            buckets=bucket_stats,
            clean_events=clean_events,
            blocked_recent_hypo=blocked_recent_hypo,
            global_reason_flags=global_reason_flags,
            runs=runs,
        )
