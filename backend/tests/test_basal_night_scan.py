import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.basal_engine import scan_night_service


@pytest.mark.asyncio
async def test_scan_night_service_persists_summary():
    user_id = str(uuid.uuid4())
    target_date = date(2024, 1, 1)

    client = AsyncMock()
    client.get_sgv_range.return_value = [
        SimpleNamespace(sgv=95),
        SimpleNamespace(sgv=65),
        SimpleNamespace(sgv=120),
    ]

    db = AsyncMock()
    db.add = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    db.execute.return_value = result

    res = await scan_night_service(
        user_id,
        target_date,
        client,
        db,
        write_enabled=True,
    )

    assert res["status"] == "ok"
    assert res["dry_run"] is False
    assert res["had_hypo"] is True
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
