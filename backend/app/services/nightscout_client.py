import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
import uuid
import json

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
        headers["Accept"] = "application/json"
        
        # Prepare valid query parameters for authentication
        # We generally avoid sending credentials in query params for security (logs, browser history).
        # We rely on 'API-SECRET' header (hashed) or 'Authorization: Bearer' (JWT).
        params = {}
        params = {}
        # Support for Access Tokens (Subject-Hash) which some NS versions require as query param 'token'
        # Heuristic: Access tokens often start with 'app-' or contain hyphens, and are NOT JWTs
        is_jwt_token = self.token and len(self.token) > 20 and self.token.count(".") >= 2
        if self.token and not is_jwt_token and "-" in self.token:
            params["token"] = self.token

        self.client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            headers=headers,
            params=params, 
        )

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        
        # Primary auth token/secret coming from settings
        # We try to determine if it's a JWT or a raw API Secret
        effective_token = self.token
        
        if effective_token:
            # Simple heuristic: JWTs are usually long and contains dots
            is_jwt = len(effective_token) > 20 and effective_token.count(".") >= 2
            
            if is_jwt:
                headers["Authorization"] = f"Bearer {effective_token}"
            else:
                # It is likely an API Secret (Password) OR an Access Token.
                # If we assume it is a Secret, we Hash it.
                # If it was an Access Token, hashing breaks it. 
                # BUT, Access Tokens usually work via 'token' query param which we set in __init__?
                # Actually, in __init__ we only set 'token' param if it HAD a dash.
                # Now we found out that API SECRETS can have dashes too.
                
                # Strategy:
                # 1. We ALREADY added it to query params in __init__ if it had a dash.
                # 2. We ALSO add it here as API-SECRET (Hashed).
                # Nightscout usually checks API-SECRET first. If valid, good.
                # If invalid (because it was an Access Token hashed), it checks query param.
                
                # So the safest bet is to ALWAYS send API-SECRET header (hashed) for non-JWTs.
                # Even if it is an Access Token, sending a garbage API-SECRET header usually gets ignored if a valid token param exists?
                # Or does it block? 
                # Let's assume sending API-SECRET is priority for "connection settings" which usually implies the Master Secret.
                
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
        endpoint_candidates = ["/api/v1/status", "/api/v1/status.json", "/status.json"]
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
        response = await self.client.get("/api/v1/entries/sgv", params={"count": 1})
        data = await self._handle_response(response)
        if not data:
            raise NightscoutError("No SGV data available")
        entry = data[0] if isinstance(data, list) else data
        return NightscoutSGV.model_validate(entry)

    async def get_recent_treatments(self, hours: int = 24, limit: int = 200) -> list[Treatment]:
        try:
             # Prepare Params - Fallback to basic count to ensure compatibility
            params = {
                "count": limit, 
            }
            
            # Use a slightly longer timeout for fetching large lists, but capped
            # We use an internal loop for retries since httpx transport retries are basic
            import asyncio
            retries = 2
            last_err = None

            for attempt in range(retries + 1):
                try:
                    req_id = uuid.uuid4().hex[:8]
                    # Explicit timeout per attempt (8s)
                    response = await self.client.get("/api/v1/treatments", params=params, timeout=8.0)
                    
                    # Manual Handling
                    if response.status_code in (401, 403):
                        raise NightscoutError(f"Unauthorized: {response.status_code}")
                    
                    response.raise_for_status()
                    
                    # Relaxed Empty Body Check Logic
                    raw_bytes = response.content
                    n_bytes = len(raw_bytes)
                    
                    if n_bytes == 0:
                        # Empty body often means no results in some NS versions or empty results
                        logger.debug("Empty body from Nightscout treatments, returning []")
                        return []
                    
                    try:
                        data = json.loads(raw_bytes)
                    except ValueError:
                         logger.error(f"Invalid JSON in treatments.")
                         raise NightscoutError("Invalid JSON received")

                    break # Success
                except httpx.TimeoutException:
                     last_err = NightscoutError("Timeout connecting to Nightscout")
                except httpx.HTTPStatusError as e:
                     logger.warning(f"NS Error {e.response.status_code} fetching treatments.")
                     if e.response.status_code in (401, 403):
                         raise NightscoutError("Unauthorized")
                     last_err = e
                except Exception as e:
                    last_err = e
                
                # If we are here, we failed an attempt
                if attempt < retries:
                     wait_ms = 250 if attempt == 0 else 750
                     await asyncio.sleep(wait_ms / 1000.0)

            # Check if we have data or exhausted retries
            # If 'data' is not bound (loop finished without break), raise last error
            if 'data' not in locals():
                 raise last_err or NightscoutError("Unknown fetch failure")

            if not isinstance(data, list):
                logger.warning(f"Expected list for treatments, got {type(data)}")
                return []

            # Client-side validation & Filtering
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
                    # Replace Z with +00:00 for fromisoformat compatibility
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
                    
                    # Only include if within requested window (hours)
                    if dt >= cutoff:
                        valid_treatments.append(Treatment.model_validate(item))
                except Exception as e:
                    # Skip malformed items
                    logger.error(f"Skipping treatment due to error: {e}. Item: {item}")
                    continue
                    
            logger.info(f"Fetched {len(data)} treatments, {len(valid_treatments)} valid after filtering ({hours}h).")
            return valid_treatments
            
        except NightscoutError:
            raise
        except Exception as e:
             logger.error(f"Error fetching treatments: {str(e)}")
             raise NightscoutError(f"Fetch failed: {str(e)}")

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
        
        response = await self.client.get("/api/v1/entries/sgv", params=params)
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
        # Warning: Some Nightscout versions are strict about the 'enteredBy' field.
        # Ensure it is present in all treatments.
        for t in treatments:
            if "enteredBy" not in t or not t["enteredBy"]:
                t["enteredBy"] = "BolusAI"
        
        # We explicitly ensure we are posting JSON
        # The client is already configured with headers, but let's double check content-type
        
        response = await self.client.post("/api/v1/treatments", json=treatments)
        
        # Special handling for uploads:
        # Some Nightscout versions return 200 OK via empty body on success?
        # Or just the created objects?
        
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # If 401, trying to upload without write permissions?
            logger.error(f"Nightscout Upload Failed: {e.response.status_code} - {e.response.text}")
            raise NightscoutError(f"Upload failed: {e.response.status_code}")
            
        if not response.content.strip():
            # If successful but empty, assume success
            return {"status": "success", "uploaded_count": len(treatments)}
            
        return response.json()

    async def update_treatment(self, treatment_id: str, updates: dict) -> Any:
        response = await self.client.put(f"/api/v1/treatments/{treatment_id}", json=updates)
        return await self._handle_response(response)

    async def delete_treatment(self, treatment_id: str) -> None:
        response = await self.client.delete(f"/api/v1/treatments/{treatment_id}")
        if response.status_code not in (200, 204):
             response.raise_for_status()

    async def aclose(self) -> None:
        await self.client.aclose()
