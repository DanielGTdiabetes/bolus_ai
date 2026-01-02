from datetime import datetime

from fastapi import APIRouter, Depends, Response, Request

from app import __version__, jobs_state
from app.core.settings import get_settings, Settings
from app.services.nightscout_client import NightscoutClient

router = APIRouter()

_start_time = datetime.utcnow()


def _uptime_seconds() -> float:
    return (datetime.utcnow() - _start_time).total_seconds()


@router.api_route("", methods=["GET", "HEAD"], summary="Liveness probe", response_model=None)
async def health(request: Request):
    if request.method == "HEAD":
        return Response(status_code=200)
    return {"ok": True}


@router.options("/", include_in_schema=False)
async def health_options() -> Response:
    return Response(status_code=200)


from app.core.security import get_current_user, CurrentUser

@router.get("/full", summary="Full health check")
async def full_health(
    settings: Settings = Depends(get_settings),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    status: dict[str, object] = {
        "ok": True,
        "uptime_seconds": _uptime_seconds(),
        "version": __version__,
    }

    ns_config = settings.nightscout
    if ns_config.base_url:
        try:
            client = NightscoutClient(
                base_url=str(ns_config.base_url),
                token=ns_config.token,
                api_secret=ns_config.api_secret,
                timeout_seconds=ns_config.timeout_seconds,
            )
            try:
                ns_status = await client.get_status()
                status["nightscout"] = {"reachable": True, "status": ns_status}
            finally:
                await client.aclose()
        except Exception as exc:  # pragma: no cover - defensive fallback
            # Audit H6: Sanitize error
            status["nightscout"] = {"reachable": False, "error": "Connection Failed"}
    else:
        status["nightscout"] = {"reachable": False, "reason": "Not configured (system)"}

    from app.core.db import check_db_health
    status["database"] = await check_db_health()

    status["server"] = {"host": settings.server.host, "port": settings.server.port}
    return status


@router.get("/jobs", summary="Background jobs state")
async def jobs_health() -> dict:
    return jobs_state.get_all_states()

@router.get("/wake", summary="Keep-alive Endpoint")
async def wake_endpoint():
    """
    Lightweight endpoint to wake up the server or keep it alive.
    External monitors (UptimeRobot, etc.) should ping this.
    """
    return {"status": "awake", "time": datetime.utcnow()}
