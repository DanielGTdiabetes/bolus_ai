import logging
from typing import Optional

from fastapi import APIRouter, Request, Header, HTTPException, status

from app.core import config
from app.core.config import get_public_bot_url_with_source
from app.bot import service as bot_service
from app.bot.service import get_bot_application, _sanitize_url, refresh_webhook_registration
from app.bot.state import health, BotMode

logger = logging.getLogger(__name__)

router = APIRouter()
diag_router = APIRouter()

@router.post("/telegram", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    """
    Receives updates from Telegram. 
    Verifies secret token for security.
    """
    if not config.is_telegram_bot_enabled():
        return {"status": "disabled"}

    # Verify Secret if configured AND we are in Webhook Mode
    # (If we are in polling mode, Telegram won't be sending this header because we didn't setWebhook)
    public_url, _ = get_public_bot_url_with_source()
    is_webhook_mode = bool(public_url)
    
    expected_secret = config.get_telegram_webhook_secret()
    
    if is_webhook_mode and expected_secret:
        if x_telegram_bot_api_secret_token != expected_secret:
            logger.warning("Invalid Telegram Secret Token (Webhook Mode)")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Invalid Secret Token"
            )

    try:
        data = await request.json()
        health.mark_update()
        await bot_service.process_update(data)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error reading webhook payload: {e}")
        health.set_error(str(e))
        # Return 200 to telegram to prevent retries of bad payloads
        return {"status": "error", "message": str(e)}


@diag_router.get("/webhook", include_in_schema=False)
async def telegram_webhook_diagnostics():
    mode = health.mode.value if isinstance(health.mode, BotMode) else health.mode
    public_url, public_url_source = get_public_bot_url_with_source()
    expected_path = "/api/webhook/telegram"
    expected_url = f"{public_url}{expected_path}" if public_url else None

    token = config.get_telegram_bot_token()
    app = get_bot_application()
    webhook_info: Optional[dict] = None
    error = None

    if not token or not app:
        error = "missing_token" if not token else "bot_not_initialized"
    else:
        try:
            info = await app.bot.get_webhook_info()
            webhook_info = {
                "url": _sanitize_url(info.url) if info else None,
                "has_custom_certificate": getattr(info, "has_custom_certificate", None),
                "pending_update_count": getattr(info, "pending_update_count", None),
                "last_error_date": getattr(info, "last_error_date", None),
                "last_error_message": getattr(info, "last_error_message", None),
                "max_connections": getattr(info, "max_connections", None),
                "ip_address": getattr(info, "ip_address", None),
            }
        except Exception as exc:
            error = str(exc)

    return {
        "mode": mode,
        "public_url_source": public_url_source,
        "configured_public_url": _sanitize_url(public_url) if public_url else None,
        "expected_webhook_path": expected_path,
        "expected_webhook_url": _sanitize_url(expected_url) if expected_url else None,
        "telegram_webhook_info": webhook_info,
        "last_update_at": health.last_update_at.isoformat() if health.last_update_at else None,
        "last_error": health.last_error,
        "last_reply_at": health.last_reply_at.isoformat() if health.last_reply_at else None,
        "last_reply_error": health.last_reply_error,
        "error": error,
    }


@diag_router.post("/webhook/refresh", include_in_schema=False)
async def telegram_webhook_refresh(request: Request):
    admin_secret = config.get_admin_shared_secret()
    if not admin_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ADMIN_SHARED_SECRET not configured")

    provided = request.headers.get("X-Admin-Secret")
    if provided != admin_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    result = await refresh_webhook_registration()
    return result


@router.get("/health/bot", include_in_schema=False)
async def bot_health():
    from app.bot.state import health as bot_health_state
    return bot_health_state.to_dict()
