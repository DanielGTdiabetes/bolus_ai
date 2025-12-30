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

def should_silence(event_type: str) -> bool:
    """
    Returns True if event should be silenced (too soon).
    """
    now = datetime.now(timezone.utc)
    last_at = _LAST_EVENTS.get(event_type)
    
    if not last_at:
        return False
        
    window = SILENCE_WINDOWS_MINUTES.get(event_type, 60)
    delta = (now - last_at).total_seconds() / 60
    
    return delta < window

def mark_event_sent(event_type: str) -> None:
    """Updates the last sent timestamp for an event."""
    _LAST_EVENTS[event_type] = datetime.now(timezone.utc)

def get_silence_status(event_type: str) -> str:
    if should_silence(event_type):
        return "silenced"
    return "allowed"
