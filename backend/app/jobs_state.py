import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from app.core.scheduler import get_scheduler

logger = logging.getLogger(__name__)

JOB_KEYS_TO_SCHEDULER_IDS: dict[str, str] = {
    "glucose_monitor": "guardian_check",
    "premeal": "premeal_nudge",
    "basal": "basal_reminder",
    "morning_summary": "morning_summary",
    "learning_eval": "learning_eval",
}


@dataclass
class JobStatus:
    last_run_at: Optional[str] = None
    last_ok: Optional[bool] = None
    last_error: Optional[str] = None
    next_run_at: Optional[str] = None


_job_states: dict[str, JobStatus] = {
    job_key: JobStatus() for job_key in JOB_KEYS_TO_SCHEDULER_IDS.keys()
}


def _ensure_job_key(job_key: str) -> JobStatus:
    if job_key not in _job_states:
        _job_states[job_key] = JobStatus()
    return _job_states[job_key]


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def mark_job_start(job_key: str) -> None:
    state = _ensure_job_key(job_key)
    state.last_run_at = _to_iso(datetime.now(timezone.utc))


def mark_job_success(job_key: str) -> None:
    state = _ensure_job_key(job_key)
    state.last_ok = True
    state.last_error = None


def mark_job_error(job_key: str, error: BaseException) -> None:
    state = _ensure_job_key(job_key)
    state.last_ok = False
    state.last_error = str(error)


def set_next_run(job_key: str, next_run: Optional[datetime]) -> None:
    state = _ensure_job_key(job_key)
    state.next_run_at = _to_iso(next_run)


def refresh_next_run(job_key: str) -> None:
    scheduler = get_scheduler()
    job_id = JOB_KEYS_TO_SCHEDULER_IDS.get(job_key)
    if not scheduler or not job_id:
        return

    try:
        job = scheduler.get_job(job_id)
        next_run = job.next_run_time if job else None
        set_next_run(job_key, next_run)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Unable to refresh next run for %s: %s", job_key, exc)


def get_all_states() -> dict[str, dict[str, object]]:
    for job_key in list(_job_states.keys()):
        refresh_next_run(job_key)
    return {job_key: asdict(state) for job_key, state in _job_states.items()}


async def run_job(
    job_key: str,
    func: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    mark_job_start(job_key)
    try:
        result = await func(*args, **kwargs)
        mark_job_success(job_key)
        return result
    except Exception as exc:
        mark_job_error(job_key, exc)
        raise
    finally:
        refresh_next_run(job_key)
