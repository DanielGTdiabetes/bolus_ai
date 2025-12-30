import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Dict, Any, List
from statistics import median

from app.services import basal_repo
from app.models.settings import UserSettings
from app.bot import tools # For getting settings if needed, or pass them in

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_GRACE_MINUTES = 120 # 2 hours after expected time
MIN_SAMPLES_FOR_INFERENCE = 3
DEFAULT_LOOKBACK_DAYS = 14

class BasalContext:
    def __init__(self, 
                 last_dose: Optional[Dict], 
                 expected_time: Optional[str], 
                 expected_units: Optional[float],
                 status: str,
                 reason: str,
                 next_due_utc: Optional[datetime] = None):
        self.last_dose = last_dose
        self.expected_time = expected_time # "HH:MM"
        self.expected_units = expected_units
        self.status = status # taken_today, missing_today, not_due_yet, late, insufficient_history
        self.reason = reason
        self.next_due_utc = next_due_utc

    def to_dict(self):
        return {
            "last_dose": self.last_dose,
            "expected_time": self.expected_time,
            "expected_units": self.expected_units,
            "status": self.status,
            "reason": self.reason,
            "next_due_utc": self.next_due_utc.isoformat() if self.next_due_utc else None
        }

async def get_basal_history_stats(user_id: str, days: int = 14) -> Dict[str, Any]:
    """
    Analyzes recent history to find median time and mode/median units.
    """
    history = await basal_repo.get_dose_history(user_id, days)
    if not history:
        return {"time": None, "units": None, "samples": 0}

    # Extract times (minutes from midnight)
    minutes_list = []
    units_list = []
    
    for entry in history:
        # Assuming created_at is the injection time.
        # If effective_from is accurate date, created_at time portion is what we want.
        # We need to be careful with UTC. created_at is likely UTC. 
        # We want "local time" perspective for routines.
        # Without explicit user timezone, we rely on the consistency of the 'hours' in stored timestamps.
        # If user is consistently UTC+1, the UTC hours will also cluster.
        ts = entry.get("created_at")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts:
             # Just use hour*60 + min of the UTC time for clustering
             # It acts as a proxy for routine even if shifted.
             m = ts.hour * 60 + ts.minute
             minutes_list.append(m)
             units_list.append(entry.get("dose_u", 0))

    if len(minutes_list) < MIN_SAMPLES_FOR_INFERENCE:
        return {"time": None, "units": None, "samples": len(minutes_list)}

    # Circular Median for time?
    # Simple median is fine if people don't inject around midnight (e.g. 23:59 vs 00:01).
    # If they inject at 23:00 and 01:00, median is 24:00 (avg 0). 
    # Let's assume most people inject morning or evening consistently.
    med_min = int(median(minutes_list))
    
    # Format "HH:MM"
    h = med_min // 60
    m = med_min % 60
    time_str = f"{h:02d}:{m:02d}"

    # Median units
    med_units = median(units_list)

    return {
        "time": time_str,
        "units": round(med_units, 1),
        "samples": len(minutes_list)
    }

async def get_basal_status(user_id: str, timezone_offset: int = 0) -> BasalContext:
    """
    Determines the current status of basal medication.
    timezone_offset: hours from UTC (estimate)
    """
    now_utc = datetime.now(timezone.utc)
    # Estimate local date
    # Ideally we get this from UserSettings, but we can pass it in or infer.
    # For now, rely on repo using effective_from as logical date.
    
    # 1. Get History
    last_dose = await basal_repo.get_latest_basal_dose(user_id)
    stats = await get_basal_history_stats(user_id, DEFAULT_LOOKBACK_DAYS)
    
    # 2. Check "Taken Today"
    # Logic: effective_from matches today's date (local).
    # We need to know "Today". 
    # If we don't have timezone, we might check if last_dose was < 20 hours ago?
    # Better: user explicit "effective_from" field.
    
    # Let's define "Today" relative to the user's routine.
    # If routine is 22:00, "Today" for basal means "the dose for this calendar day".
    
    # Approximate local now
    now_local_approx = now_utc + timedelta(hours=timezone_offset)
    today_local = now_local_approx.date()
    
    is_taken = False
    last_dose_dict = None
    
    if last_dose:
        raw_eff = last_dose.get("effective_from")
        eff_date = raw_eff if isinstance(raw_eff, date) else datetime.fromisoformat(str(raw_eff)).date()
        
        # Check if matched
        if eff_date >= today_local:
            is_taken = True
            
        # Reformat for context
        last_dose_dict = {
            "units": last_dose.get("dose_u"),
            "time": last_dose.get("created_at").isoformat() if last_dose.get("created_at") else None,
            "date": eff_date.isoformat()
        }

    # 3. Infer Expectations
    expected_time = stats.get("time") # UTC-based string "HH:MM"
    expected_units = stats.get("units")
    
    if not expected_time:
        return BasalContext(last_dose_dict, None, None, "insufficient_history", "need_more_samples")

    # 4. Determine Late/Due
    # Parse expected HH:MM (UTC) to today's datetime
    try:
        eh, em = map(int, expected_time.split(":"))
        expected_dt_utc = now_utc.replace(hour=eh, minute=em, second=0, microsecond=0)
        
        # Handle wrap around if we are near midnight boundaries?
        # Simpler: If expected is 22:00 and now is 01:00 (next day), 
        # delta is -21h?
        # Let's rely on standard day match.
        
        # Calculate diff in minutes
        diff_min = (now_utc - expected_dt_utc).total_seconds() / 60
        
        # If is_taken, we are good.
        if is_taken:
             # Check distinct duplicate risk? 
             # e.g. taken 1 hour ago?
             hours_since = 999
             if last_dose and last_dose.get("created_at"):
                 ts = last_dose.get("created_at")
                 if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
                 hours_since = (now_utc - ts).total_seconds() / 3600
             
             status = "taken_today"
             reason = "entry_exists"
             if hours_since < 4:
                 reason = "taken_recently"
                 
             return BasalContext(last_dose_dict, expected_time, expected_units, status, reason)
        
        # If not taken
        if diff_min > DEFAULT_GRACE_MINUTES:
            return BasalContext(last_dose_dict, expected_time, expected_units, "late", f"overdue_{int(diff_min)}_min")
        elif diff_min > -60: # Within 1 hour before
             return BasalContext(last_dose_dict, expected_time, expected_units, "due_soon", "upcoming_window")
        else:
             return BasalContext(last_dose_dict, expected_time, expected_units, "not_due_yet", "too_early")

    except Exception as e:
        logger.error(f"Error calculating basal status: {e}")
        return BasalContext(last_dose_dict, expected_time, expected_units, "error", str(e))
