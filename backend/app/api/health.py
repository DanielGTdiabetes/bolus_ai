from datetime import datetime

from fastapi import APIRouter, Depends

from app import __version__
from app.core.settings import get_settings, Settings
from app.services.nightscout_client import NightscoutClient

router = APIRouter()

_start_time = datetime.utcnow()


def _uptime_seconds() -> float:
    return (datetime.utcnow() - _start_time).total_seconds()


@router.get("/", summary="Liveness probe")
async def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/full", summary="Full health check")
async def full_health(
    settings: Settings = Depends(get_settings),
    nightscout_client: NightscoutClient = Depends(NightscoutClient.depends),
) -> dict:
    status: dict[str, object] = {
        "ok": True,
        "uptime_seconds": _uptime_seconds(),
        "version": __version__,
    }

    try:
        ns_status = await nightscout_client.get_status()
        status["nightscout"] = {"reachable": True, "status": ns_status}
    except Exception as exc:  # pragma: no cover - defensive fallback
        status["nightscout"] = {"reachable": False, "error": str(exc)}

    status["server"] = {"host": settings.server.host, "port": settings.server.port}
    return status
