#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import fcntl
except ImportError:  # pragma: no cover - the service runs on Linux; enables local unit tests on Windows.
    fcntl = None

BASE_DIR = Path(os.getenv("HERMES_MFP_DIR", "/opt/hermes-mcp/myfitnesspal"))
SCRIPT = BASE_DIR / "scripts" / "sync_to_bolus.py"
PYTHON = BASE_DIR / "venv" / "bin" / "python"
LOCK_PATH = Path.home() / ".hermes" / "state" / "mfp_sync_trigger.lock"
HOST = os.getenv("MFP_SYNC_TRIGGER_HOST", "0.0.0.0")
PORT = int(os.getenv("MFP_SYNC_TRIGGER_PORT", "8776"))
TIMEOUT_SECONDS = int(os.getenv("MFP_SYNC_TRIGGER_TIMEOUT", "120"))
OUTPUT_TAIL_LIMIT = 4000

SYNC_COMPLETE_RE = re.compile(
    r"\bsync\s+complete\b[^\r\n]*?\bposted\s*=\s*(\d+)[^\r\n]*?\bqueued\s*=\s*(\d+)",
    re.IGNORECASE,
)
POSTED_RE = re.compile(r"\bposted\s*=\s*(\d+)", re.IGNORECASE)
QUEUED_RE = re.compile(r"\bqueued\s*=\s*(\d+)", re.IGNORECASE)
MFP_METADATA_REQUEST_RE = re.compile(
    r"\bmfp\s+request\s+status\s*=\s*(\d{3})[^\r\n]*"
    r"url\s*=\s*https?://api\.myfitnesspal\.com/v2/users/",
    re.IGNORECASE,
)

METADATA_STATUSES = {"success", "fallback_recovered", "failed", "unknown", "not_attempted"}
INGEST_STATUSES = {"success", "no_changes", "retry_scheduled", "failed", "unknown", "not_attempted"}
NOTIFICATION_STATUSES = {
    "queued",
    "sent",
    "retry_scheduled",
    "delivery_unknown",
    "failed",
    "not_required",
    "unknown",
}


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


def _last_int(pattern: re.Pattern[str], output: str) -> int | None:
    values = [int(match.group(1)) for match in pattern.finditer(output)]
    return values[-1] if values else None


def _structured_summary(output: str) -> dict:
    """Return the last child JSON object that looks like a sync summary."""
    summary: dict = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            candidate = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(candidate, dict) and any(
            key in candidate
            for key in (
                "posted",
                "posted_count",
                "queued",
                "queued_count",
                "metadata_status",
                "ingest_status",
                "notification_status",
            )
        ):
            summary = candidate
    return summary


def _summary_count(summary: dict, *keys: str) -> int | None:
    for key in keys:
        value = summary.get(key)
        if isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def classify_sync_output(output: str, returncode: int | None, *, timed_out: bool = False) -> dict:
    """Classify the complete child output before any diagnostic truncation."""
    summary = _structured_summary(output)
    complete_matches = list(SYNC_COMPLETE_RE.finditer(output))
    complete_match = complete_matches[-1] if complete_matches else None

    posted_count = _summary_count(summary, "posted_count", "posted")
    queued_count = _summary_count(summary, "queued_count", "queued")
    if complete_match is not None:
        posted_count = posted_count if posted_count is not None else int(complete_match.group(1))
        queued_count = queued_count if queued_count is not None else int(complete_match.group(2))
    if posted_count is None:
        posted_count = _last_int(POSTED_RE, output)
    if queued_count is None:
        queued_count = _last_int(QUEUED_RE, output)

    ingest_status = str(summary.get("ingest_status", "")).strip().lower()
    if ingest_status not in INGEST_STATUSES:
        if timed_out:
            ingest_status = "failed"
        elif queued_count is not None and queued_count > 0:
            ingest_status = "retry_scheduled"
        elif posted_count is not None and posted_count > 0:
            ingest_status = "success"
        elif posted_count == 0 and queued_count == 0:
            ingest_status = "no_changes"
        elif returncode not in (0, None):
            ingest_status = "failed"
        else:
            ingest_status = "unknown"

    metadata_status = str(summary.get("metadata_status", "")).strip().lower()
    if metadata_status not in METADATA_STATUSES:
        metadata_codes = [int(match.group(1)) for match in MFP_METADATA_REQUEST_RE.finditer(output)]
        if not metadata_codes:
            metadata_status = "unknown"
        elif metadata_codes[-1] in range(200, 300):
            metadata_status = "success"
        elif ingest_status in {"success", "no_changes", "retry_scheduled"}:
            metadata_status = "fallback_recovered"
        else:
            metadata_status = "failed"

    notification_status = str(summary.get("notification_status", "")).strip().lower()
    if notification_status not in NOTIFICATION_STATUSES:
        notification_status = "unknown"

    if timed_out:
        status = "failed"
    elif ingest_status == "retry_scheduled":
        status = "retry_scheduled"
    elif returncode not in (0, None) or ingest_status == "failed":
        status = "failed"
    elif (
        metadata_status in {"fallback_recovered", "failed"}
        or ingest_status == "unknown"
        or notification_status in {"queued", "retry_scheduled", "delivery_unknown", "failed"}
    ):
        status = "success_with_warning"
    elif ingest_status == "no_changes":
        status = "no_changes"
    else:
        status = "success"

    return {
        "status": status,
        "metadata_status": metadata_status,
        "ingest_status": ingest_status,
        "notification_status": notification_status,
        "posted_count": posted_count,
        "queued_count": queued_count,
    }


def build_sync_response(
    *,
    sync_id: str,
    output: str,
    returncode: int | None,
    duration_ms: int,
    timed_out: bool = False,
    message: str | None = None,
) -> tuple[dict, int]:
    classification = classify_sync_output(output, returncode, timed_out=timed_out)
    status = classification["status"]
    response = {
        "sync_id": sync_id,
        # Numeric success is retained for clients deployed before the structured contract.
        "success": 1 if returncode == 0 and not timed_out else 0,
        **classification,
        "returncode": returncode,
        "duration_ms": duration_ms,
        "output_tail": output[-OUTPUT_TAIL_LIMIT:],
    }
    if message:
        response["message"] = message

    if timed_out:
        http_status = 504
    elif status == "failed":
        http_status = 500
    elif status == "retry_scheduled":
        http_status = 202
    else:
        http_status = 200
    return response, http_status


def build_not_started_response(sync_id: str, status: str, message: str) -> dict:
    return {
        "sync_id": sync_id,
        "success": 0,
        "status": status,
        "metadata_status": "not_attempted",
        "ingest_status": "retry_scheduled" if status == "retry_scheduled" else "not_attempted",
        "notification_status": "not_required",
        "posted_count": None,
        "queued_count": None,
        "returncode": None,
        "duration_ms": 0,
        "message": message,
        "output_tail": "",
    }


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

    def log_sync(self, sync_id: str, message: str) -> None:
        sys.stderr.write(f"sync_id={sync_id} {message}\n")

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if path == "/healthz":
            self.json_response({"status": "ok", "service": "mfp-sync-trigger"})
            return
        self.json_response({"error": "not found", "endpoints": ["GET /healthz", "POST /mfp/sync-now"]}, 404)

    def do_POST(self) -> None:
        sync_id = str(uuid.uuid4())
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path != "/mfp/sync-now":
            self.json_response(build_not_started_response(sync_id, "failed", "not found"), 404)
            return
        if not self.authorized():
            self.log_sync(sync_id, "status=failed reason=unauthorized")
            self.json_response(build_not_started_response(sync_id, "failed", "unauthorized"), 401)
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
            if fcntl is None:
                self.log_sync(sync_id, "status=failed reason=file_locking_unavailable")
                self.json_response(build_not_started_response(sync_id, "failed", "file locking is unavailable"), 500)
                return
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.log_sync(sync_id, "status=retry_scheduled reason=already_running")
                self.json_response(
                    build_not_started_response(sync_id, "retry_scheduled", "sync already running"),
                    409,
                )
                return

            started = time.time()
            self.log_sync(sync_id, "status=started")
            try:
                proc = subprocess.run(
                    args,
                    cwd=str(BASE_DIR),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=TIMEOUT_SECONDS,
                    env={**os.environ, "BOLUS_AI_SYNC_ID": sync_id},
                )
                output = proc.stdout or ""
                response, status_code = build_sync_response(
                    sync_id=sync_id,
                    output=output,
                    returncode=proc.returncode,
                    duration_ms=int((time.time() - started) * 1000),
                )
            except subprocess.TimeoutExpired as error:
                raw_output = error.stdout or ""
                output = raw_output.decode(errors="replace") if isinstance(raw_output, bytes) else raw_output
                response, status_code = build_sync_response(
                    sync_id=sync_id,
                    output=output,
                    returncode=-1,
                    duration_ms=int((time.time() - started) * 1000),
                    timed_out=True,
                    message=f"sync timed out after {TIMEOUT_SECONDS}s",
                )
            except OSError as error:
                response, status_code = build_sync_response(
                    sync_id=sync_id,
                    output="",
                    returncode=-1,
                    duration_ms=int((time.time() - started) * 1000),
                    message=f"unable to start sync: {error}",
                )
            self.log_sync(
                sync_id,
                " ".join(
                    (
                        f"status={response['status']}",
                        f"metadata_status={response['metadata_status']}",
                        f"ingest_status={response['ingest_status']}",
                        f"notification_status={response['notification_status']}",
                        f"posted={response['posted_count']}",
                        f"queued={response['queued_count']}",
                        f"duration_ms={response['duration_ms']}",
                    )
                ),
            )
            self.json_response(response, status_code)


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
