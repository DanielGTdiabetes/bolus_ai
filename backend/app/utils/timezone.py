from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from typing import Optional, Union

# Default to Europe/Madrid as requested for this user context
DEFAULT_TIMEZONE = "Europe/Madrid"

def get_user_timezone(username: str = "admin") -> ZoneInfo:
    """
    Returns the user's timezone.
    Attempts to resolving from UserSettings, otherwise falls back to DEFAULT_TIMEZONE.
    """
    try:
        # Optimization: Try to read from environment or cached settings if possible?
        # For now, we stick to default or safe fallback to avoid sync I/O in async path if possible
        # BUT: to respect user settings we need to know the user's pref.
        # Since this is a synchronous util, we can't easily await async DB.
        # We rely on the DEFAULT_TIMEZONE for now, or if passed explicitly in 'to_local'
        return ZoneInfo(DEFAULT_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")

def to_local(dt: datetime, tz: Optional[ZoneInfo] = None) -> datetime:
    """
    Converts a datetime to the local timezone.
    Assumes naive datetimes are UTC.
    """
    if dt is None:
        return None
    
    if tz is None:
        tz = get_user_timezone()

    if dt.tzinfo is None:
         dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.astimezone(tz)

def format_time(dt: datetime, tz: Optional[ZoneInfo] = None) -> str:
    """
    Returns HH:MM in local time.
    """
    local_dt = to_local(dt, tz)
    if not local_dt:
        return "?"
    return local_dt.strftime("%H:%M")

def format_datetime(dt: datetime, tz: Optional[ZoneInfo] = None) -> str:
    """
    Returns YYYY-MM-DD HH:MM in local time.
    """
    local_dt = to_local(dt, tz)
    if not local_dt:
        return "?"
    return local_dt.strftime("%Y-%m-%d %H:%M")
