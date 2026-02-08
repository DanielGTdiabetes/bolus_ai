from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from typing import Optional, Union

# Default to Europe/Madrid as requested for this user context
DEFAULT_TIMEZONE = "Europe/Madrid"

# Module-level cache for the users' configured timezones (set at startup or settings load)
_cached_user_tz: dict[str, str] = {}


def set_user_timezone(tz_name: str, username: str = "admin") -> None:
    """Cache the user's timezone from settings for synchronous access."""
    if not username:
        return
    if not tz_name:
        _cached_user_tz.pop(username, None)
        return
    try:
        ZoneInfo(tz_name)  # validate it's a real IANA timezone
        _cached_user_tz[username] = tz_name
    except (KeyError, Exception):
        _cached_user_tz.pop(username, None)


def get_user_timezone(username: str = "admin") -> ZoneInfo:
    """
    Returns the user's timezone.
    Uses cached value from settings if available, otherwise falls back to DEFAULT_TIMEZONE.
    """
    tz_name = _cached_user_tz.get(username, DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(tz_name)
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
