from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.settings import UserSettings


class SimpleFileLock:
    def __init__(self, path: Path, timeout: float = 5.0):
        self.lock_path = str(path) + ".lock"
        self.timeout = timeout
        self._fd: int | None = None

    def acquire(self) -> None:
        start = time.time()
        while True:
            try:
                self._fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                return
            except FileExistsError:
                if time.time() - start > self.timeout:
                    raise TimeoutError(f"Timeout waiting for lock {self.lock_path}")
                time.sleep(0.05)

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            os.unlink(self.lock_path)
        except FileNotFoundError:
            pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


@contextmanager
def _json_lock(path: Path):
    with SimpleFileLock(path):
        yield


def _ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class DataStore:
    data_dir: Path

    def _path(self, filename: str) -> Path:
        return _ensure_parent(self.data_dir / filename)

    def read_json(self, filename: str, default: Any) -> Any:
        path = self._path(filename)
        template = deepcopy(default)
        with _json_lock(path):
            if not path.exists():
                self._write(path, template)
                return deepcopy(template)
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)

    def write_json(self, filename: str, data: Any) -> None:
        path = self._path(filename)
        with _json_lock(path):
            self._write(path, data)

    def _write(self, path: Path, data: Any) -> None:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    def load_settings(self) -> UserSettings:
        raw = self.read_json("settings.json", UserSettings.default().dict())
        return UserSettings.migrate(raw)

    def save_settings(self, settings: UserSettings) -> UserSettings:
        self.write_json("settings.json", settings.dict())
        return settings

    def load_events(self) -> list[dict[str, Any]]:
        return self.read_json("events.json", [])

    def save_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.write_json("events.json", events)
        return events
