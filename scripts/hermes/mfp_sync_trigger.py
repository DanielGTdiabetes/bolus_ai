#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(os.getenv("HERMES_MFP_DIR", "/opt/hermes-mcp/myfitnesspal"))
SCRIPT = BASE_DIR / "scripts" / "sync_to_bolus.py"
PYTHON = BASE_DIR / "venv" / "bin" / "python"
LOCK_PATH = Path.home() / ".hermes" / "state" / "mfp_sync_trigger.lock"
HOST = os.getenv("MFP_SYNC_TRIGGER_HOST", "0.0.0.0")
PORT = int(os.getenv("MFP_SYNC_TRIGGER_PORT", "8776"))
TIMEOUT_SECONDS = int(os.getenv("MFP_SYNC_TRIGGER_TIMEOUT", "120"))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))


load_env_file(BASE_DIR / ".env")
load_env_file(Path.home() / ".hermes" / ".env")


def expected_key() -> str:
    return (
        os.getenv("HERMES_MFP_TRIGGER_KEY")
        or os.getenv("NUTRITION_INGEST_KEY")
        or os.getenv("NUTRITION_INGEST_SECRET")
        or os.getenv("BOLUS_AI_NUTRITION_INGEST_KEY")
        or ""
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesMfpSyncTrigger/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def json_response(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        key = expected_key()
        if not key:
            return False
        provided = self.headers.get("X-Ingest-Key", "") or self.headers.get("X-Hermes-Key", "")
        return provided == key

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if path == "/healthz":
            self.json_response({"status": "ok", "service": "mfp-sync-trigger"})
            return
        self.json_response({"error": "not found", "endpoints": ["GET /healthz", "POST /mfp/sync-now"]}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path != "/mfp/sync-now":
            self.json_response({"error": "not found"}, 404)
            return
        if not self.authorized():
            self.json_response({"error": "unauthorized"}, 401)
            return

        params = parse_qs(parsed.query)
        args = [str(PYTHON), str(SCRIPT)]
        date = (params.get("date") or [""])[0].strip()
        if date:
            args.extend(["--date", date])
        if (params.get("force") or [""])[0].lower() in {"1", "true", "yes"}:
            args.append("--force")

        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOCK_PATH.open("w") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.json_response({"success": 0, "status": "busy", "message": "sync already running"}, 409)
                return

            started = time.time()
            proc = subprocess.run(
                args,
                cwd=str(BASE_DIR),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=TIMEOUT_SECONDS,
            )
            output = (proc.stdout or "")[-4000:]
            self.json_response(
                {
                    "success": 1 if proc.returncode == 0 else 0,
                    "status": "ok" if proc.returncode == 0 else "error",
                    "returncode": proc.returncode,
                    "duration_ms": int((time.time() - started) * 1000),
                    "output_tail": output,
                },
                200 if proc.returncode == 0 else 500,
            )


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MFP sync trigger listening on {HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
