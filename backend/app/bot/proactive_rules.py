from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time
from typing import Dict, Optional
from app.bot.state import health
from app.core.settings import get_settings

# Store last event timestamps in memory
# Key: event_type, Value: datetime (UTC)
_LAST_EVENTS: Dict[str, datetime] = {}

SILENCE_WINDOWS_MINUTES = {
    "premeal": 60,
    "high_bg": 90,
    "low_bg": 30, # More urgent, shorter silence
    "basal": 180,
    "morning_summary": 1200, # Once a day essentially
    "combo_followup": 45,
}

@dataclass
class SilenceResult:
    should_silence: bool
    reason: str
    remaining_min: Optional[int] = None
    window_min: Optional[int] = None

def _is_quiet_hours(start_str: str, end_str: str) -> bool:
    try:
        now_time = datetime.now().time()
        start = datetime.strptime(start_str, "%H:%M").time()
        end = datetime.strptime(end_str, "%H:%M").time()
        
        if start < end:
            return start <= now_time <= end
        else: # Crosses midnight
            return now_time >= start or now_time <= end
    except Exception:
        return False

def check_silence(event_type: str) -> SilenceResult:
    """
    Checks if event should be silenced. Returns detailed result.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    
    # 1. Quiet Hours Check (Specific to combo_followup for now)
    if event_type == "combo_followup":
        conf = settings.proactive.combo_followup
        if conf.quiet_hours_start and conf.quiet_hours_end:
            if _is_quiet_hours(conf.quiet_hours_start, conf.quiet_hours_end):
                return SilenceResult(True, "silenced_quiet_hours(combo_followup)")
                
        window = conf.silence_minutes
    else:
        window = SILENCE_WINDOWS_MINUTES.get(event_type, 60)

    # 2. Cooldown Check
    last_at = _LAST_EVENTS.get(event_type)
    
    if not last_at:
        return SilenceResult(False, "no_previous_event")
        
    delta_min = (now - last_at).total_seconds() / 60
    
    if delta_min < window:
        remaining = int(window - delta_min)
        reason_str = f"silenced_recent({event_type}, remaining={remaining}m, window={window}m)"
        return SilenceResult(
            True, 
            reason_str,
            remaining_min=remaining,
            window_min=window
        )
        
    return SilenceResult(False, "cooldown_expired")

def should_silence(event_type: str) -> bool:
    """
    Returns True if event should be silenced (too soon).
    Legacy wrapper around check_silence.
    """
    return check_silence(event_type).should_silence

def mark_event_sent(event_type: str) -> None:
    """Updates the last sent timestamp for an event."""
    _LAST_EVENTS[event_type] = datetime.now(timezone.utc)

def get_silence_status(event_type: str) -> str:
    res = check_silence(event_type)
    if res.should_silence:
        return "silenced"
    return "allowed"

