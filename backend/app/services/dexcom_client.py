import logging
import asyncio
from typing import Optional, Dict
from pydexcom import Dexcom
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Cache instances to avoid repeated logins (Dexcom is sensitive to this)
_CLIENT_CACHE: Dict[str, Dexcom] = {}

@dataclass
class GlucoseReading:
    sgv: int
    trend: str
    date: datetime
    delta: Optional[float] = None

class DexcomClient:
    def __init__(self, username: str, password: str, region: str = "ous"):
        self.username = username
        self.password = password
        self.region = region.lower()
        self.cache_key = f"{username}_{region}"

    async def _get_client(self):
        """
        Retrieves a cached Dexcom client or creates a new one (login).
        """
        global _CLIENT_CACHE
        
        if self.cache_key not in _CLIENT_CACHE:
            def _init_dexcom():
                logger.info(f"Dexcom: Performing fresh login for {self.username}")
                return Dexcom(username=self.username, password=self.password, region=self.region)
            
            try:
                _CLIENT_CACHE[self.cache_key] = await asyncio.to_thread(_init_dexcom)
            except Exception as e:
                logger.error(f"Dexcom Login Failed for {self.username}: {e}")
                raise e
                
        return _CLIENT_CACHE[self.cache_key]

    async def get_latest_sgv(self) -> Optional[GlucoseReading]:
        try:
            client = await self._get_client()
            
            # Run blocking call in executor
            bg = await asyncio.to_thread(client.get_current_glucose_reading)
            
            if not bg:
                return None
            
            # Pydexcom typical bg.datetime is aware or we need to ensure it
            bg_dt = bg.datetime
            
            # Timezone Fix: Pydexcom returns naive times. We need to be careful.
            if bg_dt:
                now_utc = datetime.now(timezone.utc)
                
                if bg_dt.tzinfo is None:
                    try:
                        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
                        candidate = bg_dt.replace(tzinfo=local_tz).astimezone(timezone.utc)
                    except Exception as exc:
                        logger.warning(f"Dexcom naive timestamp; defaulting to UTC: {exc}")
                        candidate = bg_dt.replace(tzinfo=timezone.utc)
                else:
                    candidate = bg_dt.astimezone(timezone.utc)
                
                diff_sec = abs((now_utc - candidate).total_seconds())
                
                if diff_sec > 3600: # 1 hour tolerance
                    logger.warning(f"Dexcom time drift detected (TS={bg_dt} vs Now={now_utc}). Snapping to NOW.")
                    bg_dt = now_utc
                else:
                    bg_dt = candidate
            else:
                 bg_dt = datetime.now(timezone.utc)
            
            return GlucoseReading(
                sgv=bg.value,
                trend=bg.trend_arrow or "",
                date=bg_dt or datetime.now(timezone.utc),
                delta=None
            )
        except Exception as e:
            logger.error(f"Dexcom Share Fetch Error: {e}")
            # If fetch fails, maybe session expired? Clear cache to force re-login next time
            if self.cache_key in _CLIENT_CACHE:
                del _CLIENT_CACHE[self.cache_key]
            return None

    async def get_sgv_range(self, start_dt: datetime, end_dt: datetime) -> list[GlucoseReading]:
        try:
            client = await self._get_client()

            def _fetch():
                return client.get_glucose_readings(start_dt=start_dt, end_dt=end_dt)

            readings = await asyncio.to_thread(_fetch)
            results: list[GlucoseReading] = []
            if not readings:
                return results
            for bg in readings:
                bg_dt = getattr(bg, "datetime", None) or getattr(bg, "timestamp", None)
                if not bg_dt:
                    continue
                if isinstance(bg_dt, datetime):
                    if bg_dt.tzinfo is None:
                        bg_dt = bg_dt.replace(tzinfo=timezone.utc)
                    else:
                        bg_dt = bg_dt.astimezone(timezone.utc)
                else:
                    bg_dt = datetime.fromtimestamp(bg_dt, tz=timezone.utc)
                results.append(
                    GlucoseReading(
                        sgv=getattr(bg, "value", None) or getattr(bg, "sgv", 0),
                        trend=getattr(bg, "trend_arrow", None) or "",
                        date=bg_dt,
                        delta=None,
                    )
                )
            return results
        except Exception as exc:
            logger.error(f"Dexcom Share Range Fetch Error: {exc}")
            if self.cache_key in _CLIENT_CACHE:
                del _CLIENT_CACHE[self.cache_key]
            return []
