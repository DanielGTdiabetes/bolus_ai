"""Persistent snapshot storage for bolus confirmations.

Replaces the in-memory SNAPSHOT_STORAGE dict with a JSON file on disk.
Snapshots expire after TTL_SECONDS (default 30 min) and are purged on load.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SnapshotStore:
    TTL_SECONDS = 1800  # 30 minutos

    def __init__(self, data_dir: Path):
        self.path = data_dir / "bot_snapshots.json"
        self._cache: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                now = datetime.now(timezone.utc).timestamp()
                self._cache = {
                    k: v for k, v in data.items()
                    if v.get("expires_at", 0) > now
                }
                expired = len(data) - len(self._cache)
                if expired > 0:
                    logger.info(f"SnapshotStore: purged {expired} expired snapshots")
                self._persist()
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"SnapshotStore: failed to load, starting fresh: {e}")
                self._cache = {}

    def _persist(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, default=str)
        except IOError as e:
            logger.error(f"SnapshotStore: failed to persist: {e}")

    def get(self, key: str) -> Optional[dict]:
        item = self._cache.get(key)
        if item and item.get("expires_at", 0) <= datetime.now(timezone.utc).timestamp():
            self._cache.pop(key, None)
            self._persist()
            return None
        return item

    def set(self, key: str, value: dict):
        value["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=self.TTL_SECONDS)
        ).timestamp()
        self._cache[key] = value
        self._persist()

    def pop(self, key: str, default: Any = None) -> Any:
        result = self._cache.pop(key, default)
        self._persist()
        return result

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __len__(self) -> int:
        return len(self._cache)

    def keys(self):
        return self._cache.keys()

    def clear(self):
        self._cache.clear()
        self._persist()
