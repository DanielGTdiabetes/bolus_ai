import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Dict, Any, List
from statistics import median

from app.services import basal_repo
from app.models.settings import UserSettings
from app.bot import tools # For getting settings if needed, or pass them in
from app.utils import timezone as tz_utils

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
        self.expected_time = expected_time # "HH:MM" (Local inferred)
        self.expected_units = expected_units
        self.status = status 
        self.reason = reason
        self.next_due_utc = next_due_utc
        
        # Derived Local View
        self.last_dose_time_local = None
        if last_dose and last_dose.get("time"):
             try:
                 dt = datetime.fromisoformat(last_dose["time"])
                 self.last_dose_time_local = tz_utils.format_time(dt)
                 # Add date also? The user context might just need HH:MM usually.
                 # Let's add full localized timestamp to last_dose dict for easier consumption
                 last_dose["time_local"] = self.last_dose_time_local
                 last_dose["datetime_local"] = tz_utils.format_datetime(dt)
             except Exception:
                 pass

    def to_dict(self):
        return {
            "last_dose": self.last_dose,
            "expected_time": self.expected_time,
            "expected_units": self.expected_units,
            "status": self.status,
            "reason": self.reason,
            "next_due_utc": self.next_due_utc.isoformat() if self.next_due_utc else None,
            "last_dose_time_local": self.last_dose_time_local
        }

async def get_basal_history_stats(user_id: str, days: int = 14) -> Dict[str, Any]:
    """
    Analyzes recent history to find median time (LOCAL) and median units.
    """
    history = await basal_repo.get_dose_history(user_id, days)
    if not history:
        return {"time": None, "units": None, "samples": 0}

    minutes_list = []
    units_list = []
    
    user_tz = tz_utils.get_user_timezone(user_id)
    
    for entry in history:
        ts = entry.get("created_at")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        
        if ts:
             # Convert to local time to handle DST consistency
             local_ts = tz_utils.to_local(ts, user_tz)
             m = local_ts.hour * 60 + local_ts.minute
             minutes_list.append(m)
             units_list.append(entry.get("dose_u", 0))

    if len(minutes_list) < MIN_SAMPLES_FOR_INFERENCE:
        return {"time": None, "units": None, "samples": len(minutes_list)}

    med_min = int(median(minutes_list))
    
    # Format "HH:MM"
    h = med_min // 60
    m = med_min % 60
    time_str = f"{h:02d}:{m:02d}"

    med_units = median(units_list)

    return {
        "time": time_str,
        "units": round(med_units, 1),
        "samples": len(minutes_list)
    }

async def get_basal_status(user_id: str, _offset_unused: int = 0) -> BasalContext:
    """
    Determines status using ZoneInfo for correctness.
    """
    now_utc = datetime.now(timezone.utc)
    user_tz = tz_utils.get_user_timezone(user_id)
    now_local = now_utc.astimezone(user_tz)
    today_local_date = now_local.date()
    
    # 1. Get History
    last_dose = await basal_repo.get_latest_basal_dose(user_id)
    stats = await get_basal_history_stats(user_id, DEFAULT_LOOKBACK_DAYS)
    
    is_taken = False
    last_dose_dict = None
    
    if last_dose:
        # Effective from is usually a date object or string "YYYY-MM-DD"
        raw_eff = last_dose.get("effective_from")
        eff_date = raw_eff if isinstance(raw_eff, date) else datetime.fromisoformat(str(raw_eff)).date()
        
        # Basic check: if effective date matches today local
        if eff_date >= today_local_date:
            is_taken = True
            
        last_dose_dict = {
            "units": last_dose.get("dose_u"),
            "time": last_dose.get("created_at").isoformat() if last_dose.get("created_at") else None,
            "date": eff_date.isoformat()
        }

    # 3. Infer Expectations (Local Time)
    expected_time_local_str = stats.get("time") # "HH:MM" in Local
    expected_units = stats.get("units")
    
    if not expected_time_local_str:
        return BasalContext(last_dose_dict, None, None, "insufficient_history", "need_more_samples")

    try:
        eh, em = map(int, expected_time_local_str.split(":"))
        
        # Create expected datetime local
        expected_dt_local = now_local.replace(hour=eh, minute=em, second=0, microsecond=0)
        
        # Calculate diff in minutes
        diff_min = (now_local - expected_dt_local).total_seconds() / 60
        
        if is_taken:
             # Check distinct duplicate risk (e.g. taken < 4h ago relative to real time)
             hours_since = 999
             if last_dose and last_dose.get("created_at"):
                 ts_utc = last_dose.get("created_at")
                 if ts_utc.tzinfo is None: ts_utc = ts_utc.replace(tzinfo=timezone.utc)
                 hours_since = (now_utc - ts_utc).total_seconds() / 3600
             
             status = "taken_today"
             reason = "entry_exists"
             if hours_since < 4:
                 reason = "taken_recently"
                 
             return BasalContext(last_dose_dict, expected_time_local_str, expected_units, status, reason)
        
        # Logic is same just using local diffs
        if diff_min > DEFAULT_GRACE_MINUTES:
            return BasalContext(last_dose_dict, expected_time_local_str, expected_units, "late", f"overdue_{int(diff_min)}_min")
        elif diff_min > -60: 
             return BasalContext(last_dose_dict, expected_time_local_str, expected_units, "due_soon", "upcoming_window")
        else:
             return BasalContext(last_dose_dict, expected_time_local_str, expected_units, "not_due_yet", "too_early")

    except Exception as e:
        logger.error(f"Error calculating basal status: {e}")
        return BasalContext(last_dose_dict, expected_time_local_str, expected_units, "error", str(e))
