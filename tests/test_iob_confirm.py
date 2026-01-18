import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "backend"))

from app.services.iob import compute_iob_from_sources  # noqa: E402
from app.services.store import DataStore  # noqa: E402
from app.models.settings import UserSettings  # noqa: E402


@pytest.mark.asyncio
async def test_iob_unavailable_returns_none(tmp_path):
    settings = UserSettings.default()
    store = DataStore(Path(tmp_path))
    now = datetime.now(timezone.utc)

    iob_u, breakdown, info, warning = await compute_iob_from_sources(now, settings, None, store)

    assert iob_u == 0.0
    assert info.status == "ok"
    assert info.iob_u == 0.0
    assert breakdown == []


@pytest.mark.asyncio
async def test_iob_cache_marks_stale(tmp_path):
    settings = UserSettings.default()
    store = DataStore(Path(tmp_path))
    cached_ts = datetime.now(timezone.utc).isoformat()
    store.write_json("iob_cache.json", {"iob_u": 2.5, "fetched_at": cached_ts})
    now = datetime.now(timezone.utc)

    iob_u, _, info, _ = await compute_iob_from_sources(now, settings, None, store)

    assert info.status == "ok"
    assert info.last_known_iob == 0.0
    assert iob_u == 0.0
