
import asyncio
import logging
import httpx
from datetime import datetime
from app.core.settings import get_settings
from app.bot.service import notify_admin

logger = logging.getLogger(__name__)

class StabilityMonitor:
    """
    Monitors NAS health from Render (Emergency Mode).
    Implements Hysteresis:
    - Alert immediately on failure (2 consecutive checks).
    - Alert recovery only after X minutes of stability.
    """
    
    _consecutive_failures: int = 0
    _consecutive_successes: int = 0
    _is_nas_down: bool = False
    _recovery_threshold_checks: int = 15 # Assuming 1 check/min -> 15 mins
    
    @classmethod
    async def check_health(cls):
        settings = get_settings()
        if not settings.emergency_mode:
            return # Only run in Emergency Mode
            
        url = settings.nas_public_url
        if not url:
            logger.warning("Monitoring skipped: NAS_PUBLIC_URL not configured")
            return

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # We check /api/health/check or just /healthz
                target = f"{url.rstrip('/')}/api/health/check"
                resp = await client.get(target)
                
                if resp.status_code == 200:
                    await cls._handle_success()
                else:
                    await cls._handle_failure(f"Status {resp.status_code}")
                    
        except Exception as e:
            await cls._handle_failure(str(e))

    @classmethod
    async def _handle_failure(cls, reason: str):
        cls._consecutive_successes = 0
        cls._consecutive_failures += 1
        
        logger.warning(f"NAS Check Failed ({cls._consecutive_failures}): {reason}")
        
        # Trigger alert on 2nd failure to avoid blips
        if cls._consecutive_failures == 2 and not cls._is_nas_down:
            cls._is_nas_down = True
            await notify_admin(f"🚨 **ALERTA CRÍTICA**\n\nEl NAS parece estar CAÍDO (o inalcanzable).\nError: {reason}\n\nUsa la URL de Emergencia si es necesario.")

    @classmethod
    async def _handle_success(cls):
        cls._consecutive_failures = 0
        cls._consecutive_successes += 1
        
        if cls._is_nas_down:
            logger.info(f"NAS appears online. Stability check: {cls._consecutive_successes}/{cls._recovery_threshold_checks}")
            
            if cls._consecutive_successes >= cls._recovery_threshold_checks:
                cls._is_nas_down = False
                await notify_admin(f"✅ **RECUPERACIÓN CONFIRMADA**\n\nEl NAS ha estado estable durante {cls._recovery_threshold_checks} minutos.\nYa es seguro volver a la URL principal.")
                # Reset counter to keep tracking
                cls._consecutive_successes = 0

