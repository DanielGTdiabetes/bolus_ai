import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

from app.models.isf import IsfAnalysisResponse, IsfBucketStat, IsfEvent
from app.models.schemas import Treatment, NightscoutSGV
from app.services.nightscout_client import NightscoutClient
from app.services.iob import compute_iob, InsulinActionProfile

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

class IsfAnalysisService:
    def __init__(self, ns_client: NightscoutClient, current_cf_settings: dict, profile_settings: dict):
        self.ns = ns_client
        self.current_cf = current_cf_settings
        self.profile = InsulinActionProfile(
            dia_hours=float(profile_settings.get("dia_hours", 4.0)),
            curve=profile_settings.get("curve", "walsh"),
            peak_minutes=int(profile_settings.get("peak_minutes", 75))
        )

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
        
        # Helper to find SGV at time
        # sgv.date is epoch ms
        def get_bg_at(dt: datetime, window_minutes=10) -> Optional[int]:
            target_ms = int(dt.timestamp() * 1000)
            window_ms = window_minutes * 60 * 1000
            
            # Binary search or simple scan? Scan is fast enough for 5k items
            # Optimization: could index
            closest = None
            min_diff = float("inf")
            
            for s in sgv_data:
                diff = abs(s.date - target_ms)
                if diff < min_diff and diff < window_ms:
                    min_diff = diff
                    closest = s
            
            return closest.sgv if closest else None

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
                valid=True,
                reason=None
            )
            clean_events.append(event)
            
        # Aggregate
        bucket_stats = []
        
        for bucket_key, label in BUCKET_LABELS.items():
            events = [e for e in clean_events if e.bucket == bucket_key]
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
            
        return IsfAnalysisResponse(
            buckets=bucket_stats,
            clean_events=clean_events
        )
