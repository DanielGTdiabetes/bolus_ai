#!/usr/bin/env python3
"""Stable, fail-closed MyFitnessPal -> Bolus AI synchronizer.

This file is deployed inside /opt/hermes-mcp/myfitnesspal/scripts.  It imports
the host's authenticated mfp_adapter, but deliberately contains no credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import error, request
from zoneinfo import ZoneInfo


BASE_DIR = Path(os.getenv("HERMES_MFP_DIR", "/opt/hermes-mcp/myfitnesspal"))
sys.path.insert(0, str(BASE_DIR))
if BASE_DIR.exists():
    os.chdir(BASE_DIR)

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")
    load_dotenv(Path.home() / ".hermes" / ".env")

import mfp_adapter  # type: ignore  # noqa: E402


STATE_DIR = Path(os.getenv("HERMES_MFP_BOLUS_STATE_DIR", str(Path.home() / ".hermes" / "state")))
STATE_PATH = Path(os.getenv("HERMES_MFP_BOLUS_STATE_FILE", str(STATE_DIR / "mfp_bolus_sync.json")))
LOG_PATH = Path(os.getenv("HERMES_MFP_BOLUS_LOG", str(BASE_DIR / "logs" / "bolus_sync.log")))
STABILITY_DELAY_SECONDS = max(2.0, min(float(os.getenv("MFP_STABILITY_DELAY_SECONDS", "4")), 10.0))
MAX_STABILITY_READS = 3

MEAL_TIMES = {
    "breakfast": "08:30:00", "desayuno": "08:30:00",
    "lunch": "14:00:00", "almuerzo": "14:00:00", "comida": "14:00:00",
    "dinner": "21:00:00", "cena": "21:00:00",
    "snacks": "17:30:00", "snack": "17:30:00", "aperitivos": "17:30:00",
}


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=os.getenv("HERMES_MFP_BOLUS_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)],
    )


def num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def load_state() -> dict[str, Any]:
    try:
        state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
        return state if isinstance(state, dict) else {}
    except Exception:
        logging.warning("state_read_failed path=%s", STATE_PATH)
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    tmp.replace(STATE_PATH)


def canonical_foods(meal: dict[str, Any]) -> list[dict[str, Any]]:
    foods = []
    for food in meal.get("foods") or []:
        name = str(food.get("name") or food.get("short_name") or "").strip()
        if not name:
            continue
        foods.append({
            "name": name,
            "quantity": str(food.get("quantity") or "").strip(),
            "unit": str(food.get("unit") or "").strip(),
            "carbs_g": round(num(food.get("carbs_g")), 2),
            "fat_g": round(num(food.get("fat_g")), 2),
            "protein_g": round(num(food.get("protein_g")), 2),
            "fiber_g": round(num(food.get("fiber_g")), 2),
        })
    # Preserve display order while canonical JSON handles stable key ordering.
    return foods


def meal_name(meal: dict[str, Any]) -> str:
    return str(meal.get("meal") or meal.get("slot") or "unknown").strip().lower() or "unknown"


def stable_meal_id(day: str, meal: dict[str, Any]) -> str:
    return f"hermes-mfp:{day}:{meal_name(meal)}"


def meal_revision(day: str, meal: dict[str, Any]) -> str:
    canonical = {
        "date": day,
        "meal": meal_name(meal),
        "source_carbs": round(num(meal.get("carbs_g")), 2),
        "fat": round(num(meal.get("fat_g")), 2),
        "protein": round(num(meal.get("protein_g")), 2),
        "fiber": round(num(meal.get("fiber_g")), 2),
        "foods": canonical_foods(meal),
    }
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def legacy_fingerprint(day: str, meal: dict[str, Any]) -> str:
    """Recognize state written by v1 so deployment does not replay today's meals."""
    foods = []
    for food in meal.get("foods") or []:
        name = str(food.get("name") or food.get("short_name") or "").strip()
        if not name:
            continue
        foods.append({
            "name": name,
            "quantity": str(food.get("quantity") or "").strip(),
            "unit": str(food.get("unit") or "").strip(),
            "calories": round(num(food.get("calories")), 2),
            "carbs_g": round(num(food.get("carbs_g")), 2),
            "fat_g": round(num(food.get("fat_g")), 2),
            "protein_g": round(num(food.get("protein_g")), 2),
            "fiber_g": round(num(food.get("fiber_g")), 2),
        })
    foods.sort(key=lambda item: (item["name"].lower(), item["quantity"], item["unit"]))
    value = {
        "source": "hermes-myfitnesspal", "date": day, "meal": meal_name(meal),
        "totals": {
            "calories": round(num(meal.get("calories")), 2),
            "carbs_g": round(num(meal.get("carbs_g")), 2),
            "fat_g": round(num(meal.get("fat_g")), 2),
            "protein_g": round(num(meal.get("protein_g")), 2),
            "fiber_g": round(num(meal.get("fiber_g")), 2),
        },
        "foods": foods,
    }
    digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    return f"hermes-mfp:{day}:{meal_name(meal)}:{digest}"


def meal_timestamp(day: str, name: str) -> str:
    hhmmss = MEAL_TIMES.get(name, "12:00:00")
    tz = ZoneInfo(os.getenv("HERMES_MFP_BOLUS_TIMEZONE", "Europe/Madrid"))
    return datetime.strptime(f"{day} {hhmmss}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz).isoformat()


def read_day(day: str | None, read_number: int) -> tuple[str, dict[str, dict[str, Any]]]:
    started = time.perf_counter()
    logging.info("[MFP_SYNC] T1 request_mfp read=%s date=%s", read_number, day or "today")
    result = mfp_adapter.get_day(day)
    duration_ms = int((time.perf_counter() - started) * 1000)
    resolved_day = str(result.get("date") or day or datetime.now().date().isoformat())
    meals: dict[str, dict[str, Any]] = {}
    for meal in result.get("meals") or []:
        if not isinstance(meal, dict):
            continue
        if sum(num(meal.get(key)) for key in ("carbs_g", "fat_g", "protein_g", "fiber_g")) <= 0:
            continue
        key = stable_meal_id(resolved_day, meal)
        meals[key] = {"day": resolved_day, "meal": meal, "revision": meal_revision(resolved_day, meal)}
    logging.info("[MFP_SYNC] T2 response_mfp read=%s duration_ms=%s meals=%s", read_number, duration_ms, len(meals))
    logging.info("[MFP_SYNC] T3 parsing_complete read=%s", read_number)
    return resolved_day, meals


def stable_candidates(day: str | None) -> tuple[dict[str, dict[str, Any]], int]:
    _, previous = read_day(day, 1)
    for read_number in range(2, MAX_STABILITY_READS + 1):
        time.sleep(STABILITY_DELAY_SECONDS)
        _, current = read_day(day, read_number)
        stable = {
            key: value for key, value in current.items()
            if key in previous and previous[key]["revision"] == value["revision"]
        }
        changed = sorted(
            key for key in set(previous) | set(current)
            if previous.get(key, {}).get("revision") != current.get(key, {}).get("revision")
        )
        if not changed:
            return stable, read_number
        logging.warning("[MFP_SYNC] unstable read=%s changed_meals=%s", read_number, changed)
        previous = current
    return stable, MAX_STABILITY_READS


def build_payload(item: dict[str, Any], stable_read_count: int) -> dict[str, Any]:
    day = item["day"]
    meal = item["meal"]
    name = meal_name(meal)
    return {
        "sync_id": os.getenv("BOLUS_AI_SYNC_ID") or None,
        "source": "MyFitnessPal-Hermes",
        "provider": "hermes-myfitnesspal",
        "meal_id": stable_meal_id(day, meal),
        "meal_revision": item["revision"],
        "date": day,
        "meal": name,
        "timestamp": meal_timestamp(day, name),
        "source_carbs": round(num(meal.get("carbs_g")), 1),
        "fat": round(num(meal.get("fat_g")), 1),
        "protein": round(num(meal.get("protein_g")), 1),
        "fiber": round(num(meal.get("fiber_g")), 1),
        "foods": canonical_foods(meal),
        "stability_confirmed": True,
        "stable_read_count": stable_read_count,
        "timing": {"stability_delay_seconds": STABILITY_DELAY_SECONDS},
    }


def bolus_config() -> tuple[str, str]:
    base_url = (os.getenv("BOLUS_AI_BASE_URL") or "").rstrip("/")
    key = os.getenv("NUTRITION_INGEST_KEY") or os.getenv("NUTRITION_INGEST_SECRET") or os.getenv("BOLUS_AI_NUTRITION_INGEST_KEY")
    if not base_url or not key:
        raise RuntimeError("Bolus AI endpoint or ingest key is not configured")
    return base_url, key


def post_to_bolus(payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    base_url, key = bolus_config()
    if dry_run:
        return {"success": 1, "dry_run": True, "notification_status": "not_required"}
    headers = {"Content-Type": "application/json", "User-Agent": "HermesMfpBolusSync/2.0", "X-Ingest-Key": key}
    if payload.get("sync_id"):
        headers["X-Sync-Id"] = str(payload["sync_id"])
    req = request.Request(
        f"{base_url}/api/integrations/nutrition",
        data=json.dumps(payload, ensure_ascii=False).encode(), method="POST", headers=headers,
    )
    with request.urlopen(req, timeout=int(os.getenv("HERMES_MFP_BOLUS_TIMEOUT", "20"))) as response:
        return json.loads(response.read().decode())


def dates_to_sync(args: argparse.Namespace) -> list[str | None]:
    if args.date:
        return [args.date]
    today = datetime.now().date()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(max(0, int(os.getenv("HERMES_MFP_BOLUS_DAYS_BACK", "0"))) + 1)]


def sync_once(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    logging.info("[MFP_SYNC] T0 poll_start sync_id=%s", os.getenv("BOLUS_AI_SYNC_ID") or "standalone")
    state = load_state()
    sent = dict(state.get("sent") or {})
    posted = skipped = failures = unstable = 0
    notification_statuses: list[str] = []

    try:
        candidates: dict[str, dict[str, Any]] = {}
        read_counts: dict[str, int] = {}
        for day in dates_to_sync(args):
            stable, count = stable_candidates(day)
            candidates.update(stable)
            read_counts.update({key: count for key in stable})
        for identity, item in candidates.items():
            revision = item["revision"]
            legacy_id = legacy_fingerprint(item["day"], item["meal"])
            if identity not in sent and legacy_id in sent and not args.force:
                sent[identity] = {
                    "revision": revision,
                    "sent_at": sent[legacy_id].get("sent_at"),
                    "migrated_from": legacy_id,
                }
                skipped += 1
                continue
            if sent.get(identity, {}).get("revision") == revision and not args.force:
                skipped += 1
                continue
            payload = build_payload(item, read_counts[identity])
            try:
                result = post_to_bolus(payload, args.dry_run)
                if result.get("success") != 1:
                    raise RuntimeError(f"Bolus rejected candidate: {result}")
                notification_statuses.append(str(result.get("notification_status") or "unknown"))
                if not args.dry_run:
                    sent[identity] = {"revision": revision, "sent_at": datetime.now().isoformat(timespec="seconds")}
                posted += 1
            except (OSError, error.URLError, error.HTTPError, RuntimeError, ValueError) as exc:
                failures += 1
                logging.warning("[MFP_SYNC] ingest_failed meal_id=%s error=%s", identity, type(exc).__name__)
        # Anything seen but not stable remains blocked and is never read from old state.
        unstable = max(0, len(read_counts) - len(candidates))
    except Exception as exc:
        failures += 1
        logging.error("[MFP_SYNC] fetch_failed fail_closed=true error=%s", type(exc).__name__)

    if not args.dry_run:
        state["sent"] = sent
        state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        state["last_result"] = {"posted": posted, "skipped": skipped, "failures": failures, "unstable": unstable}
        save_state(state)
    notification_status = (
        "retry_scheduled" if any(value in {"queued", "retry_scheduled", "delivery_unknown"} for value in notification_statuses)
        else notification_statuses[-1] if notification_statuses else "not_required"
    )
    summary = {
        "posted_count": posted, "queued_count": 0,
        "metadata_status": "success" if not failures else "failed",
        "ingest_status": "failed" if failures else ("success" if posted else "no_changes"),
        "notification_status": notification_status,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }
    print(json.dumps(summary, sort_keys=True), flush=True)
    logging.info("sync complete posted=%s queued=0 skipped=%s failures=%s unstable=%s", posted, skipped, failures, unstable)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    setup_logging()
    return sync_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
