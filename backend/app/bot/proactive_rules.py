from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from app.bot.state import health

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

def check_silence(event_type: str) -> SilenceResult:
    """
    Checks if event should be silenced. Returns detailed result.
    """
    now = datetime.now(timezone.utc)
    last_at = _LAST_EVENTS.get(event_type)
    
    if not last_at:
        return SilenceResult(False, "no_previous_event")
        
    window = SILENCE_WINDOWS_MINUTES.get(event_type, 60)
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

