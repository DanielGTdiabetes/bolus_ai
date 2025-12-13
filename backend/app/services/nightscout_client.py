import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from app.core.settings import get_settings, Settings
from app.models.schemas import NightscoutSGV, NightscoutStatus, Treatment

logger = logging.getLogger(__name__)


class NightscoutError(Exception):
    """Raised when Nightscout interaction fails."""


class NightscoutClient:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or httpx.AsyncClient(
            base_url=str(self.settings.nightscout.base_url),
            timeout=self.settings.nightscout.timeout_seconds,
            headers=self._auth_headers(),
        )

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        token = self.settings.nightscout.token
        api_secret = self.settings.nightscout.api_secret
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if api_secret:
            # Nightscout typically expects SHA1 hash of the secret via API-SECRET header
            hashed = hashlib.sha1(api_secret.encode("utf-8")).hexdigest()
            headers["API-SECRET"] = hashed
        return headers

    async def _handle_response(self, response: httpx.Response) -> Any:
        try:
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Nightscout API error", extra={"status_code": exc.response.status_code, "body": exc.response.text})
            raise NightscoutError(f"Nightscout returned status {exc.response.status_code}") from exc
        except ValueError as exc:  # pragma: no cover - invalid JSON
            logger.error("Invalid JSON from Nightscout", extra={"body": response.text})
            raise NightscoutError("Nightscout returned invalid JSON") from exc

    async def get_status(self) -> NightscoutStatus:
        endpoint_candidates = ["/api/v1/status.json", "/status.json"]
        last_error: Optional[Exception] = None
        for endpoint in endpoint_candidates:
            try:
                response = await self.client.get(endpoint)
                data = await self._handle_response(response)
                return NightscoutStatus.parse_obj(data)
            except Exception as exc:  # pragma: no cover - fallback attempts
                last_error = exc
                logger.warning("Nightscout status endpoint failed", extra={"endpoint": endpoint, "error": str(exc)})
        raise NightscoutError(f"Unable to fetch Nightscout status: {last_error}")

    async def get_latest_sgv(self) -> NightscoutSGV:
        response = await self.client.get("/api/v1/entries/sgv.json", params={"count": 1})
        data = await self._handle_response(response)
        if not data:
            raise NightscoutError("No SGV data available")
        entry = data[0]
        return NightscoutSGV.parse_obj(entry)

    async def get_recent_treatments(self, hours: int = 24, limit: int = 200) -> list[Treatment]:
        since = datetime.utcnow() - timedelta(hours=hours)
        params = {
            "find[created_at][$gte]": since.isoformat(),
            "count": limit,
            "sort[created_at]": -1,
        }
        response = await self.client.get("/api/v1/treatments.json", params=params)
        data = await self._handle_response(response)
        return [Treatment.parse_obj(item) for item in data]

    @classmethod
    async def depends(cls) -> "NightscoutClient":
        return cls()

    async def aclose(self) -> None:
        await self.client.aclose()
