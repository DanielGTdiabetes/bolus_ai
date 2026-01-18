import os
import sys
import asyncio
import tempfile
from pathlib import Path

# SET ENV VARS FOR TESTS (Before imports)
TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="bolus-ai-test-db-"))
os.environ.setdefault("JWT_SECRET", "test-secret-autofix-12345")
os.environ.setdefault("ADMIN_SHARED_SECRET", "test-admin-shared-secret")
os.environ.setdefault("APP_SECRET_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{TEST_DB_DIR / 'test.db'}")
os.environ.setdefault("VISION_PROVIDER", "none")
os.environ.setdefault("GOOGLE_API_KEY", "dummy")
os.environ.setdefault("DATA_DIR", str(TEST_DB_DIR / "data"))

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app"
for path in (ROOT, APP_PATH):
    str_path = str(path)
    if str_path not in sys.path:
        sys.path.insert(0, str_path)


import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    from app.core.datastore import UserStore  # noqa: WPS433
    from app.core.db import init_db, create_tables  # noqa: WPS433
    from app.services.auth_repo import init_auth_db  # noqa: WPS433

    data_dir = Path(os.environ["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    UserStore(data_dir / "users.json").ensure_seed_admin()

    init_db()
    import app.models  # noqa: WPS433
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(create_tables())
        loop.run_until_complete(init_auth_db())
    finally:
        loop.close()
