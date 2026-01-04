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
            if bg_dt and bg_dt.tzinfo is None:
                bg_dt = bg_dt.replace(tzinfo=timezone.utc)
            
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
