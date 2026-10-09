
import logging
import os
import time
import httpx
from app.core.settings import get_settings
from app.core import config
from app.bot.service import notify_admin

logger = logging.getLogger(__name__)

class StabilityMonitor:
    """
    Monitors NAS health from the backup, including while in standby.
    Implements Hysteresis:
    - Alert immediately on failure (2 consecutive checks).
    - Alert recovery only after X minutes of stability.
    """
    
    _consecutive_failures: int = 0
    _consecutive_successes: int = 0
    _is_nas_down: bool = False
    _recovery_threshold_checks: int = 15 # Assuming 1 check/min -> 15 mins
    _urls_logged: bool = False
    _last_check_at: float | None = None
    _check_max_age_seconds: int = 120

    @classmethod
    def backup_can_notify(cls) -> bool:
        """Require two recent failures; a single success immediately yields to NAS."""
        return (
            bool(get_settings().nas_public_url)
            and cls._is_nas_down
            and cls._consecutive_failures >= 2
            and cls._consecutive_successes == 0
            and cls._last_check_at is not None
            and time.monotonic() - cls._last_check_at < cls._check_max_age_seconds
        )

    @staticmethod
    def _format_url_line(label: str, url: str | None) -> str:
        return f"{label}: {url}" if url else f"{label}: (URL no configurada)"

    @classmethod
    def _build_nas_down_message(cls, reason: str, render_url: str | None) -> str:
        return (
            "🚨 **ALERTA CRÍTICA**\n\n"
            "El NAS parece estar CAÍDO (o inalcanzable).\n"
            f"Error: {reason}\n\n"
            f"{cls._format_url_line('URL Render (emergencia)', render_url)}\n\n"
            "Usa la URL de Emergencia si es necesario."
        )

    @classmethod
    def _build_nas_recovery_message(cls, nas_url: str | None) -> str:
        return (
            "✅ **RECUPERACIÓN CONFIRMADA**\n\n"
            f"El NAS ha estado estable durante {cls._recovery_threshold_checks} minutos.\n"
            f"{cls._format_url_line('URL NAS', nas_url)}\n\n"
            "Ya es seguro volver a la URL principal."
        )
    
    @classmethod
    async def check_health(cls):
        settings = get_settings()
        if not config.is_backup_instance() and not settings.emergency_mode:
            return
            
        url = settings.nas_public_url
        render_url = os.environ.get("RENDER_EXTERNAL_URL")
        if not cls._urls_logged:
            logger.info(
                "NAS monitor URLs configured: nas=%s render=%s",
                "yes" if url else "no",
                "yes" if render_url else "no",
            )
            cls._urls_logged = True
        if not url:
            logger.warning("Monitoring skipped: NAS_PUBLIC_URL not configured")
            cls._last_check_at = None
            await cls._sync_backup_bot()
            return

        failure_reason = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # We check /api/health/check or just /healthz
                target = f"{url.rstrip('/')}/api/health/check"
                resp = await client.get(target)
                
                # A SPA fallback or proxy login page is not a healthy Bolus AI NAS.
                payload = resp.json() if resp.status_code == 200 else None
                if not isinstance(payload, dict) or payload.get("status") != "ok":
                    failure_reason = f"Invalid NAS health response (HTTP {resp.status_code})"
                    
        except Exception as e:
            failure_reason = str(e)

        if failure_reason is None:
            await cls._handle_success(url)
        else:
            await cls._handle_failure(failure_reason)

        # Keep Telegram lifecycle failures separate from NAS health failures.
        await cls._sync_backup_bot()

    @classmethod
    async def _sync_backup_bot(cls):
        if not config.is_backup_instance():
            return
        from app.bot.service import reconcile_backup_bot
        try:
            await reconcile_backup_bot()
        except Exception:
            logger.exception("Backup Telegram mode reconciliation failed")

    @classmethod
    async def _handle_failure(cls, reason: str):
        now = time.monotonic()
        if cls._last_check_at is None or now - cls._last_check_at >= cls._check_max_age_seconds:
            cls._consecutive_failures = 0
        cls._last_check_at = now
        cls._consecutive_successes = 0
        cls._consecutive_failures += 1
        
        logger.warning(f"NAS Check Failed ({cls._consecutive_failures}): {reason}")
        
        # Trigger alert on 2nd failure to avoid blips
        if cls._consecutive_failures >= 2 and not cls._is_nas_down:
            cls._is_nas_down = True
            render_url = os.environ.get("RENDER_EXTERNAL_URL")
            try:
                await notify_admin(cls._build_nas_down_message(reason, render_url))
            except Exception:
                logger.exception("NAS down notification failed")

    @classmethod
    async def _handle_success(cls, nas_url: str | None):
        cls._last_check_at = time.monotonic()
        cls._consecutive_failures = 0
        cls._consecutive_successes += 1
        
        if cls._is_nas_down:
            logger.info(f"NAS appears online. Stability check: {cls._consecutive_successes}/{cls._recovery_threshold_checks}")
            
            if cls._consecutive_successes >= cls._recovery_threshold_checks:
                cls._is_nas_down = False
                try:
                    await notify_admin(cls._build_nas_recovery_message(nas_url))
                except Exception:
                    logger.exception("NAS recovery notification failed")
                # Reset counter to keep tracking
                cls._consecutive_successes = 0
