import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import select

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.append(str(backend_dir))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("forecast_sweep")

# Load .env manually
env_path = backend_dir.parent / ".env"
if env_path.exists():
    logger.info(f"Loading .env from {env_path}")
    with env_path.open("r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

from app.core.db import init_db, SessionLocal  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.models.basal import BasalEntry  # noqa: E402
from app.models.settings import UserSettings  # noqa: E402
from app.services.forecast_diagnostics import run_forecast_sweep  # noqa: E402
from app.services.settings_service import get_user_settings_service  # noqa: E402


async def _load_settings(user_id: str):
    init_db()
    async with SessionLocal() as session:
        data = await get_user_settings_service(user_id, session)
        if not data or not data.get("settings"):
            raise RuntimeError(f"No settings found for user '{user_id}'")
        user_settings = UserSettings.migrate(data["settings"])

        result = await session.execute(
            select(BasalEntry)
            .where(BasalEntry.user_id == user_id)
            .order_by(BasalEntry.created_at.desc())
            .limit(1)
        )
        basal_entry = result.scalars().first()
        return user_settings, basal_entry


async def main():
    parser = argparse.ArgumentParser(description="Run forecast sweep diagnostics.")
    parser.add_argument("--user", default="admin", help="User ID (username) to load settings.")
    args = parser.parse_args()

    user_settings, basal_entry = await _load_settings(args.user)
    settings = get_settings()
    output_dir = settings.data.data_dir / "diagnostics"

    run_forecast_sweep(
        user_settings=user_settings,
        user_id=args.user,
        basal_entry=basal_entry,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    asyncio.run(main())
