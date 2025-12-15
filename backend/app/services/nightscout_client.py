import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from app.models.schemas import NightscoutSGV, NightscoutStatus, Treatment

logger = logging.getLogger(__name__)


class NightscoutError(Exception):
    """Raised when Nightscout interaction fails."""


class NightscoutClient:
    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        api_secret: Optional[str] = None,
        timeout_seconds: int = 10,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.api_secret = api_secret
        self.timeout_seconds = timeout_seconds
        
        headers = self._auth_headers()
        self.client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            headers=headers,
        )

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        
        # Primary auth token/secret coming from settings
        # We try to determine if it's a JWT or a raw API Secret
        effective_token = self.token
        
        if effective_token:
            # Simple heuristic: JWTs are usually long and contain dots (header.payload.signature)
            is_jwt = len(effective_token) > 20 and effective_token.count(".") >= 2
            
            if is_jwt:
                headers["Authorization"] = f"Bearer {effective_token}"
            else:
                # Assume it's an API Secret -> SHA1 hash
                hashed = hashlib.sha1(effective_token.encode("utf-8")).hexdigest()
                headers["API-SECRET"] = hashed

        # If explicit api_secret was passed (legacy param), it overrides/adds to headers
        if self.api_secret:
            hashed = hashlib.sha1(self.api_secret.encode("utf-8")).hexdigest()
            headers["API-SECRET"] = hashed
            
        return headers

    async def _handle_response(self, response: httpx.Response) -> Any:
        try:
            response.raise_for_status()
            if not response.content.strip():
                # Empty body is sometimes returned by Nightscout instead of []
                return []
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Nightscout API error", extra={"status_code": exc.response.status_code, "body": exc.response.text})
            raise NightscoutError(f"Nightscout returned status {exc.response.status_code}") from exc
        except ValueError as exc:  # pragma: no cover - invalid JSON
            preview = response.text[:200]
            if not preview.strip():
                # Should be caught above, but just in case
                return []
            logger.error(f"Invalid JSON from Nightscout. Body: {preview!r}")
            raise NightscoutError(f"Nightscout returned invalid JSON (Body: {preview!r})") from exc

    async def get_status(self) -> NightscoutStatus:
        # Added /api/v1/status (no json) as some deployments might prefer it
        endpoint_candidates = ["/api/v1/status.json", "/status.json", "/api/v1/status"]
        last_error: Optional[Exception] = None
        for endpoint in endpoint_candidates:
            try:
                response = await self.client.get(endpoint)
                data = await self._handle_response(response)
                # If status returns list (shouldn't), handle it? status usually dict.
                if isinstance(data, list):
                     raise ValueError("Expected dict for status, got list")
                return NightscoutStatus.model_validate(data)
            except Exception as exc:  # pragma: no cover - fallback attempts
                last_error = exc
                logger.warning("Nightscout status endpoint failed", extra={"endpoint": endpoint, "error": str(exc)})
        raise NightscoutError(f"Unable to fetch Nightscout status: {last_error}")

    async def get_latest_sgv(self) -> NightscoutSGV:
        # 'count=1' gets the single most recent entry
        response = await self.client.get("/api/v1/entries/sgv.json", params={"count": 1})
        data = await self._handle_response(response)
        if not data:
            raise NightscoutError("No SGV data available")
        entry = data[0] if isinstance(data, list) else data
        return NightscoutSGV.model_validate(entry)

    async def get_recent_treatments(self, hours: int = 24, limit: int = 200) -> list[Treatment]:
        # Fetching without date filter to avoid empty body issues on some NS versions
        params = {
            "count": limit,
            "sort[created_at]": -1,
        }
        
        response = await self.client.get("/api/v1/treatments.json", params=params)
        data = await self._handle_response(response)
        
        if not isinstance(data, list):
            logger.warning(f"Expected list for treatments, got {type(data)}")
            return []

        # Client-side filtering
        valid_treatments = []
        
        # Use timezone-aware UTC for comparison
        from datetime import timezone
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(hours=hours)
        
        for item in data:
            try:
                # 'created_at' usually contains ISO string: "2023-10-27T10:00:00.000Z"
                created_at_str = item.get("created_at")
                if not created_at_str:
                    continue
                
                # Robust parsing
                # Replace Z with +00:00 for fromisoformat compatibility in some versions (though 3.11+ handles Z)
                clean_ts = created_at_str.replace("Z", "+00:00")
                try:
                    dt = datetime.fromisoformat(clean_ts)
                except ValueError:
                    # Fallback for simple format if needed
                     dt = datetime.strptime(clean_ts, "%Y-%m-%dT%H:%M:%S")

                # Normalize to aware UTC
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                
                if dt >= cutoff:
                    valid_treatments.append(Treatment.model_validate(item))
            except Exception as e:
                # Skip malformed items
                continue
                
        logger.info(f"Fetched {len(data)} treatments, {len(valid_treatments)} valid after filtering ({hours}h).")
        return valid_treatments

    async def get_sgv_range(self, start_dt: datetime, end_dt: datetime, count: int = 288) -> list[NightscoutSGV]:
        """
        Fetches SGV entries within a date range (server query or client filter).
        Nightscout API supports find[dateString][$gte] etc, but date formats vary.
        Using direct epoch milliseconds is safer: find[date][$gte]=...
        """
        # Convert to epoch ms
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        
        params = {
            "find[date][$gte]": start_ms,
            "find[date][$lte]": end_ms,
            "count": count
        }
        
        response = await self.client.get("/api/v1/entries/sgv.json", params=params)
        data = await self._handle_response(response)
        
        if not isinstance(data, list):
             # Should be list of entries
             return []
             
        # Convert
        results = []
        for d in data:
            try:
                results.append(NightscoutSGV.model_validate(d))
            except Exception:
                continue
        return results

    async def upload_treatments(self, treatments: list[dict]) -> Any:
        response = await self.client.post("/api/v1/treatments.json", json=treatments)
        return await self._handle_response(response)

    async def aclose(self) -> None:
        await self.client.aclose()
