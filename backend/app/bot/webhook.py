import logging
from fastapi import APIRouter, Request, Header, HTTPException, status
from app.core import config
from app.bot import service as bot_service

logger = logging.getLogger(__name__)

router = APIRouter()

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

    # Verify Secret
    expected_secret = config.get_telegram_webhook_secret()
    if x_telegram_bot_api_secret_token != expected_secret:
        logger.warning("Invalid Telegram Secret Token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Invalid Secret Token"
        )

    try:
        data = await request.json()
        await bot_service.process_update(data)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error reading webhook payload: {e}")
        # Return 200 to telegram to prevent retries of bad payloads
        return {"status": "error", "message": str(e)}
