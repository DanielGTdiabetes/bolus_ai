import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BotMode(str, enum.Enum):
    DISABLED = "disabled"
    WEBHOOK = "webhook"
    POLLING = "polling"
    ERROR = "error"


@dataclass
class BotHealth:
    enabled: bool = False
    mode: BotMode = BotMode.DISABLED
    last_update_at: Optional[float] = None
    last_error: Optional[str] = None
    mode_reason: Optional[str] = None

    def mark_update(self) -> None:
        self.last_update_at = time.time()

    def mark_error(self, message: str) -> None:
        logger.error(message)
        self.last_error = message


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


health = BotHealth()
cooldowns = CooldownState()

