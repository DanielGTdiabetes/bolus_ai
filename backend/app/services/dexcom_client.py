import logging
import asyncio
from typing import Optional
from pydexcom import Dexcom
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

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
        self.region = region.lower() # pydexcom expects lowercase 'us' or 'ous'
        self._dexcom = None

    async def _get_client(self):
        """
        Pydexcom is synchronous. We initialize it on first use.
        Ideally we should run this in a thread executor to avoid blocking the loop 
        blocking calls are usually fast but network IO should be async.
        """
        if not self._dexcom:
            # Run blocking init in executor
            self._dexcom = await asyncio.to_thread(
                Dexcom, self.username, self.password, False, self.region
            )
        return self._dexcom

    async def get_latest_sgv(self) -> Optional[GlucoseReading]:
        try:
            client = await self._get_client()
            
            # Run blocking call in executor
            bg = await asyncio.to_thread(client.get_current_glucose_reading)
            
            if not bg:
                return None
            
            # Convert pydexcom object to our internal simple structure
            # pydexcom Trend Description is text (e.g. "Flat"), we might want arrow?
            # bg.trend_arrow gives the arrow symbol directly (e.g. '→')
            
            return GlucoseReading(
                sgv=bg.value,
                trend=bg.trend_arrow or "", # "→", "↗", etc.
                date=bg.datetime,
                delta=None # pydexcom doesn't give delta explicitly in 'get_current', calculation needed if history
            )
        except Exception as e:
            logger.error(f"Dexcom Share Fetch Error: {e}")
            # Reset client to force re-auth on next try if it was a session issue
            self._dexcom = None 
            return None
