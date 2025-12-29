import enum
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BotMode(str, enum.Enum):
    DISABLED = "disabled"
    WEBHOOK = "webhook"
    POLLING = "polling"
    ERROR = "error"


@dataclass
class BotHealthState:
    enabled: bool = False
    mode: BotMode = BotMode.DISABLED
    reason: str = "feature_flag_off"
    last_update_at: Optional[datetime] = None
    last_error: Optional[str] = None
    started_at: Optional[datetime] = None

    # Internal lock to avoid races if multiple tasks mutate quickly
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_mode(self, mode: BotMode, reason: str) -> None:
        with self._lock:
            self.mode = mode
            self.reason = reason
            if mode != BotMode.ERROR:
                self.last_error = None

    def set_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message
        logger.error(message)

    def mark_update(self) -> None:
        with self._lock:
            self.last_update_at = datetime.now(timezone.utc)

    def set_started(self) -> None:
        with self._lock:
            self.started_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode.value if isinstance(self.mode, BotMode) else self.mode,
            "reason": self.reason,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_update_at": self.last_update_at.isoformat() if self.last_update_at else None,
            "last_error": self.last_error,
        }


@dataclass
class CooldownState:
    """
    Simple in-memory cooldown tracking per key.
    Persisting to DB is overkill for single-user personal use and
    keeps Render light-weight.
    """

    cooldowns: Dict[str, float] = field(default_factory=dict)
    ttl_seconds: int = 3600

    def _now(self) -> float:
        return time.time()

    def is_ready(self, key: str, min_seconds: int) -> bool:
        now = self._now()
        last = self.cooldowns.get(key)
        if last is None:
            return True
        return (now - last) >= min_seconds

    def touch(self, key: str) -> None:
        self.cooldowns[key] = self._now()
        # prune lazily
        expired = [k for k, ts in self.cooldowns.items() if (self._now() - ts) > self.ttl_seconds]
        for k in expired:
            self.cooldowns.pop(k, None)


health = BotHealthState()
cooldowns = CooldownState()
