import os
import sys
from pathlib import Path

# SET ENV VARS FOR TESTS (Before imports)
os.environ["JWT_SECRET"] = "test-secret-autofix"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["VISION_PROVIDER"] = "none"
os.environ["GOOGLE_API_KEY"] = "dummy"

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app"
for path in (ROOT, APP_PATH):
    str_path = str(path)
    if str_path not in sys.path:
        sys.path.insert(0, str_path)
