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
    last_error_id: Optional[str] = None
    last_error_type: Optional[str] = None
    last_error_message: Optional[str] = None
    last_error_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    last_reply_at: Optional[datetime] = None
    last_reply_error: Optional[str] = None
    last_action_at: Optional[datetime] = None
    last_action_type: Optional[str] = None
    last_action_ok: Optional[bool] = None
    last_action_error: Optional[str] = None
    last_llm_at: Optional[datetime] = None
    last_llm_ok: Optional[bool] = None
    last_llm_ok: Optional[bool] = None
    last_llm_error: Optional[str] = None
    last_tool_calls: list[str] = field(default_factory=list)
    last_event_type: Optional[str] = None
    last_event_sent: Optional[bool] = None
    last_event_reason: Optional[str] = None

    # Internal lock to avoid races if multiple tasks mutate quickly
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_mode(self, mode: BotMode, reason: str) -> None:
        with self._lock:
            self.mode = mode
            self.reason = reason
            if mode != BotMode.ERROR:
                self.last_error = None

    def set_error(self, message: str, error_id: Optional[str] = None, exc: Optional[Exception] = None) -> None:
        with self._lock:
            self.last_error = message
            self.last_error_at = datetime.now(timezone.utc)
            if error_id:
                self.last_error_id = error_id
            if exc:
                self.last_error_type = type(exc).__name__
                self.last_error_message = str(exc)
        logger.error(message)

    def clear_error(self) -> None:
        with self._lock:
            self.last_error = None
            return self.last_error

    def mark_update(self) -> None:
        with self._lock:
            self.last_update_at = datetime.now(timezone.utc)

    def mark_reply_success(self) -> None:
        with self._lock:
            self.last_reply_at = datetime.now(timezone.utc)
            self.last_reply_error = None

    def set_reply_error(self, message: str) -> None:
        with self._lock:
            self.last_reply_error = message

    def set_started(self) -> None:
        with self._lock:
            self.started_at = datetime.now(timezone.utc)

    def record_action(self, action_type: str, ok: bool, error: Optional[str] = None) -> None:
        with self._lock:
            self.last_action_at = datetime.now(timezone.utc)
            self.last_action_type = action_type
            self.last_action_ok = ok
            self.last_action_ok = ok
            self.last_action_error = error if not ok else None

    def record_llm(self, ok: bool, error: Optional[str] = None, tools_used: list[str] = None) -> None:
        with self._lock:
            self.last_llm_at = datetime.now(timezone.utc)
            self.last_llm_ok = ok
            self.last_llm_error = error
            if tools_used:
                self.last_tool_calls = tools_used[:10]  # Keep last 10

    def record_event(self, event_type: str, sent: bool, reason: str) -> None:
        with self._lock:
            self.last_event_type = event_type
            self.last_event_sent = sent
            self.last_event_reason = reason

    def get_last_error(self) -> Optional[str]:
        with self._lock:
            return self.last_error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode.value if isinstance(self.mode, BotMode) else self.mode,
            "reason": self.reason,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_update_at": self.last_update_at.isoformat() if self.last_update_at else None,
            "last_error": self.last_error,
            "last_error_id": self.last_error_id,
            "last_error_type": self.last_error_type,
            "last_error_message": self.last_error_message,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
            "last_reply_at": self.last_reply_at.isoformat() if self.last_reply_at else None,
            "last_reply_error": self.last_reply_error,
            "last_action_at": self.last_action_at.isoformat() if self.last_action_at else None,
            "last_action_type": self.last_action_type,
            "last_action_ok": self.last_action_ok,
            "last_action_error": self.last_action_error,
            "last_llm_at": self.last_llm_at.isoformat() if self.last_llm_at else None,
            "last_llm_ok": self.last_llm_ok,
            "last_llm_error": self.last_llm_error,
            "last_tool_calls": self.last_tool_calls,
            "last_event_type": self.last_event_type,
            "last_event_sent": self.last_event_sent,
            "last_event_reason": self.last_event_reason,
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
