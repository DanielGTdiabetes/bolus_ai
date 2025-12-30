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
    TODO: Fetch from UserSettings in the future.
    """
    try:
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
