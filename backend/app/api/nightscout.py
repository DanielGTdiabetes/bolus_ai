from pathlib import Path
from typing import Optional, Literal
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import get_current_user
from app.core.settings import get_settings, Settings
from app.models.settings import UserSettings
from app.models.schemas import NightscoutSGV
from app.services.nightscout_client import NightscoutClient, NightscoutError
from app.services.store import DataStore
from app.core.db import get_db_session
from app.services.nightscout_secrets_service import get_ns_config, upsert_ns_config
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import CurrentUser

router = APIRouter()



class NightscoutStatusResponse(BaseModel):
    enabled: bool
    url: Optional[str]
    ok: bool
    error: Optional[str] = None


class StatelessConfig(BaseModel):
    url: str
    token: Optional[str] = None
    units: Optional[str] = "mgdl"


class CurrentGlucoseResponse(BaseModel):
    ok: bool
    configured: bool = False
    bg_mgdl: Optional[float] = None
    trend: Optional[str] = None
    trendArrow: Optional[str] = None
    age_minutes: Optional[float] = None
    date: Optional[int] = None
    stale: bool = False
    source: Literal["nightscout"] = "nightscout"
    error: Optional[str] = None
    
    # Compression Flags
    is_compression: bool = False
    compression_reason: Optional[str] = None


def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))


@router.get("/status", response_model=NightscoutStatusResponse, summary="Get Nightscout status (Server-Stored)")
async def get_status(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    ns = await get_ns_config(session, user.username)
    
    ok = False
    error = None
    url = None
    enabled = False
    
    if ns and ns.enabled and ns.url:
        url = ns.url
        enabled = ns.enabled
        try:
            client = NightscoutClient(base_url=ns.url, token=ns.api_secret, timeout_seconds=5)
            try:
                await client.get_status()
                ok = True
            except Exception as e:
                error = str(e)
            finally:
                await client.aclose()
        except Exception as e:
             error = str(e)
    
    return NightscoutStatusResponse(
        enabled=enabled,
        url=url,
        ok=ok,
        error=error,
    )


@router.post("/current", response_model=CurrentGlucoseResponse, summary="Get current glucose (Stateless)")
async def get_current_glucose_stateless(
    config: StatelessConfig,
    _: dict = Depends(get_current_user),
):
    import logging
    logger = logging.getLogger(__name__)

    if not config.url:
        # Request says: 400 if missing url, but we can also return JSON with configured=False
        # "IMPORTANTE: no devolver 200 con “no configurado”." -> implies 400 or checking configured.
        # But if body has empty url, raising HTTPException(400) is standard.
        raise HTTPException(status_code=400, detail="Missing Nightscout URL")

    logger.debug(f"Fetching Nightscout glucose from: {config.url} (token hidden)")

    try:
        client = NightscoutClient(base_url=config.url, token=config.token, timeout_seconds=10)
        try:
            # We don't check "status" first, just get SGV to be fast
            sgv: NightscoutSGV = await client.get_latest_sgv()
            
            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            diff_ms = now_ms - sgv.date
            diff_min = diff_ms / 60000.0

            # Trend arrow mapping
            arrows = {
                "DoubleUp": "↑↑", "SingleUp": "↑", "FortyFiveUp": "↗",
                "Flat": "→", "FortyFiveDown": "↘", "SingleDown": "↓", "DoubleDown": "↓↓",
                "NOT COMPUTABLE": "---", "RATE OUT OF RANGE": "---", "NONE": "---"
            }
            arrow = arrows.get(sgv.direction, sgv.direction)

            return CurrentGlucoseResponse(
                ok=True,
                configured=True,
                bg_mgdl=float(sgv.sgv),
                trend=sgv.direction,
                trendArrow=arrow,
                age_minutes=diff_min,
                date=int(sgv.date),
                stale=diff_min > 10,
                source="nightscout"
            )

        except NightscoutError as nse:
            logger.error(f"Nightscout client error: {nse}")
            # Request says 502 if Nightscout fails
            raise HTTPException(status_code=502, detail="Nightscout Unreachable")
        except Exception as e:
            logger.exception("Unexpected error fetching glucose")
            raise HTTPException(status_code=502, detail=f"Unexpected Error: {str(e)}")
        finally:
            await client.aclose()

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Global error in current glucose")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current", response_model=CurrentGlucoseResponse, summary="Get current glucose (Server-Stored)")
async def get_current_glucose_server(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings)
):
    ns = await get_ns_config(session, user.username)
    if not ns or not ns.enabled or not ns.url:
         raise HTTPException(status_code=400, detail="Nightscout is not configured")
    
    import logging
    logger = logging.getLogger(__name__)
    
    # Filter Config
    from app.services.smart_filter import CompressionDetector, FilterConfig
    f_config = FilterConfig(
        enabled=settings.nightscout.filter_compression,
        night_start_hour=settings.nightscout.filter_night_start,
        night_end_hour=settings.nightscout.filter_night_end,
        drop_threshold_mgdl=settings.nightscout.filter_drop_mgdl,
        rebound_threshold_mgdl=settings.nightscout.filter_rebound_mgdl,
        rebound_window_minutes=settings.nightscout.filter_window_min
    )
    
    try:
        client = NightscoutClient(base_url=ns.url, token=ns.api_secret, timeout_seconds=10)
        try:
            # We need history to detect compression. 
            # Fetch last 12 entries (~1 hour) instead of just 1.
            # Using get_sgv_range is better than get_latest_sgv
            
            # End = now + margin, Start = now - 60 min
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(minutes=60)
            
            entries = await client.get_sgv_range(start_dt, end_dt, count=12)
            
            # Fallback for stale data: If window search yields nothing, get absolute latest
            # This ensures we display *something* (even if stale) like the stateless endpoint does.
            if not entries:
                 try:
                     latest_single = await client.get_latest_sgv()
                     entries = [latest_single]
                 except Exception:
                     # If even this fails, then truly no data
                     pass

            if not entries:
                raise HTTPException(status_code=404, detail="No BG data found")
                
            # Sort old -> new for detector
            entries.sort(key=lambda x: x.date)
            latest_entry = entries[-1]
            
            is_comp = False
            comp_reason = None
            
            # Only run compression detection if we have enough recent data (at least 2 points)
            # and the data isn't incredibly old (e.g. > 2 hours). 
            # If we fell back to a single stale point, detection is impossible.
            if f_config.enabled and len(entries) > 1:
                # Check staleness of latest entry for detection valididity? 
                # Detector logic handles intervals, but let's avoid running it on 1-day old data blocks.
                
                # We also need treatments probably?
                # Optimization: Only fetch treatments if potential low/drop detected?
                # For now, let's just run detector on SGV. Detector handles missing treatments (assumes none).
                # If we want to be safe, we should fetch treatments.
                treatments = []
                # Simple heuristic: Only fetch treatments if latest value is < 80 or drop is large?
                # Or just fetch them (clients usually cache or small payload).
                treatments = await client.get_recent_treatments(hours=2, limit=10)
                
                detector = CompressionDetector(config=f_config)
                
                # Convert to dicts
                e_dicts = [e.model_dump() for e in entries]
                t_dicts = [t.model_dump() for t in treatments]
                
                processed = detector.detect(e_dicts, t_dicts)
                
                # Check the latest entry in processed list
                # It should match our latest_entry by date
                if processed:
                    last_proc = processed[-1]
                    if last_proc.get("date") == latest_entry.date:
                        is_comp = last_proc.get("is_compression", False)
                        comp_reason = last_proc.get("compression_reason")
            
            # Prepare Response
            sgv = latest_entry
            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            diff_ms = now_ms - sgv.date
            diff_min = diff_ms / 60000.0

            arrows = {
                "DoubleUp": "↑↑", "SingleUp": "↑", "FortyFiveUp": "↗",
                "Flat": "→", "FortyFiveDown": "↘", "SingleDown": "↓", "DoubleDown": "↓↓",
                "NOT COMPUTABLE": "---", "RATE OUT OF RANGE": "---", "NONE": "---"
            }
            arrow = arrows.get(sgv.direction, sgv.direction)

            return CurrentGlucoseResponse(
                ok=True,
                configured=True,
                bg_mgdl=float(sgv.sgv),
                trend=sgv.direction,
                trendArrow=arrow,
                age_minutes=diff_min,
                date=int(sgv.date),
                stale=diff_min > 10,
                source="nightscout",
                is_compression=is_comp,
                compression_reason=comp_reason
            )
            
        finally:
            await client.aclose()
    except NightscoutError as nse:
        logger.error(f"Nightscout Error: {nse}")
        raise HTTPException(status_code=502, detail="Nightscout Unreachable")
    except Exception as e:
        logger.exception("Error fetching current glucose (server)")
        raise HTTPException(status_code=500, detail=str(e))


class TestResponse(BaseModel):
    ok: bool
    reachable: bool
    message: str
    nightscoutVersion: Optional[str] = None


@router.post("/test", response_model=TestResponse, summary="Test Nightscout connection (Stateless)")
async def test_connection_stateless(
    config: StatelessConfig,
    _: dict = Depends(get_current_user),
):
    if not config.url:
        return TestResponse(ok=False, reachable=False, message="URL is required")

    try:
        client = NightscoutClient(base_url=config.url, token=config.token, timeout_seconds=10)
        try:
            status = await client.get_status()
            # Try to get version from status? NightscoutStatus model might have it or not.
            # Assuming status has 'version' field if defined in schema, otherwise explicit check? 
            # NightscoutStatus schema in backend/app/models/schemas.py isn't visible here but lets assume.
            return TestResponse(
                ok=True, 
                reachable=True, 
                message="Conexión exitosa a Nightscout",
                nightscoutVersion=getattr(status, "version", "Unknown")
            )
        except Exception as e:
            return TestResponse(ok=False, reachable=False, message=f"Error conectando: {str(e)}")
        finally:
            await client.aclose()
    except Exception as e:
        return TestResponse(ok=False, reachable=False, message=f"System error: {str(e)}")


class LegacyConfigPayload(BaseModel):
    url: str
    token: str
    enabled: bool = True

@router.put("/config", summary="Update Nightscout configuration (Legacy Backwards Compatibility)")
async def update_config_legacy(
    payload: LegacyConfigPayload,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    # Map 'token' to 'api_secret'
    await upsert_ns_config(session, user.username, payload.url, payload.token, payload.enabled)
    return {"message": "Config updated via legacy endpoint"}


@router.get("/treatments", summary="Get recent treatments (Hybrid: Local + Nightscout)")
async def get_treatments_server(
    count: int = 50,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    store: DataStore = Depends(_data_store)
):
    """
    Fetches recent treatments, merging local 'events' (backup), DB, and Nightscout data.
    Provides resilience if Nightscout is down or unconfigured.
    Deduplicates entries to avoid showing the same bolus multiple times.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Parse Dates
    start_dt = None
    end_dt = None
    ns_hours = 48 # Default if no date
    
    if from_date:
        try:
            # handle 'YYYY-MM-DD' or ISO
            start_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
            if start_dt.tzinfo: start_dt = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
            
            # Calculate hours for NS (since it uses hours=X)
            diff = datetime.utcnow() - start_dt
            ns_hours = int(diff.total_seconds() / 3600) + 2 # +2 buffer
            # Audit H12: Limit to 1 week (168h) to prevent huge queries
            if ns_hours > 168: 
                ns_hours = 168
            
            # If explicit range, boost count limit but cap it
            if count < 1000: count = 1000 
            if count > 2000: count = 2000 
        except:
             pass

    if to_date:
        try:
            end_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
            if end_dt.tzinfo: end_dt = end_dt.astimezone(timezone.utc).replace(tzinfo=None)
        except:
            pass

    # --- 1. Load from all sources ---

    # A. Local File (Backup)
    local_treatments = []
    try:
        events = store.load_events()
        # Filter/Format
        for e in events:
            t = e.copy()
            # Harmonize keys
            if "created_at" in t:
                # Local created_at usually string. Keep it.
                t["date"] = t["created_at"] 
            local_treatments.append(t)
    except Exception as ex:
        logger.warning(f"Error loading local events: {ex}")

    # B. Nightscout (Legacy/Backup Source - DISABLED for History Source of Truth)
    # User Request: "Migration to Local DB as source of truth".
    # We no longer pull from Nightscout to avoid data loss (cleaning of fiber/tags).
    ns_treatments = []
    # if ns and ns.enabled and ns.url:
    #     ... (Legacy logic disabled)
    db_treatments = []
    if session:
        try:
            from app.models.treatment import Treatment as DBTreatment
            from sqlalchemy import select
            
            # Simple query: last N treatments for this user
            stmt = select(DBTreatment).where(DBTreatment.user_id == user.username)
            
            if start_dt:
                stmt = stmt.where(DBTreatment.created_at >= start_dt)
            
            if end_dt:
                stmt = stmt.where(DBTreatment.created_at <= end_dt)

            stmt = stmt.order_by(DBTreatment.created_at.desc()).limit(count)
            
            result = await session.execute(stmt)
            rows = result.scalars().all()
            
            for row in rows:
                # DB stores naive UTC. 
                # We MUST tell frontend this is UTC by appending Z.
                # If we don't, frontend perceives it as Local time, causing the 1-hour ghost duplicate.
                created_iso = row.created_at.isoformat()
                if not created_iso.endswith("Z") and "+" not in created_iso:
                     created_iso += "Z"
                
                db_treatments.append({
                    "_id": str(row.id),
                    "eventType": row.event_type,
                    "created_at": created_iso,
                    "date": row.created_at.replace(tzinfo=timezone.utc).timestamp() * 1000,
                    "insulin": row.insulin,
                    "carbs": row.carbs,
                    "fat": getattr(row, 'fat', 0), # Added
                    "protein": getattr(row, 'protein', 0), # Added
                    "fiber": getattr(row, 'fiber', 0), # Added
                    "notes": row.notes,
                    "enteredBy": row.entered_by,
                    "is_uploaded": row.is_uploaded,
                    "source": "db"
                })
        except Exception as db_ex:
            logger.error(f"Error reading treatments from DB: {db_ex}")
            
    # --- 2. Merge and Deduplicate ---
    
    # helper to get timestamp (ms)
    def get_ts(x):
        d = x.get("date")
        if isinstance(d, (int, float)): return d
        c = x.get("created_at")
        if isinstance(c, str):
            try:
                # Handle varying ISO formats
                c = c.replace('Z', '+00:00')
                dt = datetime.fromisoformat(c)
                if dt.tzinfo is None:
                    # Assume local if no tz? Or assume UTC? 
                    # Best effort.
                    pass
                return dt.timestamp() * 1000
            except: 
                pass
        return 0
    
    # Combine all (NS preferred first in sort order if times identical?) 
    # Actually deduplication logic will keep the first one encountered.
    # So if we want NS to "win", we should process NS first?
    # But later we sort by time. 
    # Let's verify we just filter duplicates effectively.
    
    # D. Basal History (DB)
    basal_treatments = []
    try:
        from app.services import basal_repo
        # Fetch based on time window (convert hours to days, with buffer)
        basal_days = max(2, int(ns_hours / 24) + 1)
        basal_history = await basal_repo.get_dose_history(user.username, days=basal_days)
        
        for b in basal_history:
            # Check created_at
            cat = b.get("created_at")
            if not cat: continue
            
            # Ensure UTC aware if naive
            if cat.tzinfo is None:
                cat = cat.replace(tzinfo=timezone.utc)
            
            created_iso = cat.isoformat().replace("+00:00", "Z")
            
            basal_treatments.append({
                "_id": str(b.get("id")),
                "eventType": "Basal",
                "created_at": created_iso,
                "date": cat.timestamp() * 1000,
                "insulin": float(b.get("dose_u") or 0),
                "carbs": 0,
                "notes": "Basal Dose",
                "enteredBy": "BolusAI",
                "source": "basal_db"
            })
            
    except Exception as basal_ex:
        logger.error(f"Error reading basal history: {basal_ex}")

    # Combine all (NS preferred first in sort order if times identical?) 
    # Actually deduplication logic will keep the first one encountered.
    # So if we want NS to "win", we should process NS first?
    # But later we sort by time. 
    # Let's verify we just filter duplicates effectively.
    
    all_raw = ns_treatments + db_treatments + local_treatments + basal_treatments
    
    # Sort by time descending (Newest first)
    try:
        all_raw.sort(key=get_ts, reverse=True)
    except Exception as e:
        logger.error(f"Sort failed: {e}")

    unique_treatments = []
    
    for item in all_raw:
        item_ts = get_ts(item)
        item_ins = item.get("insulin") or 0
        item_carbs = item.get("carbs") or 0
        
        is_duplicate = False
        
        # Check against already added (which are newer/same-time)
        # We only check the last few added to valid list 
        # (Actually since we traverse New -> Old, and valid list is New->Old, 
        # we check the *end* of the valid list? No, valid list grows.
        # We want to check all recently added items.)
        
        for existing in unique_treatments[-10:]: 
            ex_ts = get_ts(existing)
            
            # Tolerance: 2 minutes (120000 ms)
            # This handles small clock drifts or execution delays between sources
            if abs(ex_ts - item_ts) < 120000:
                ex_ins = existing.get("insulin") or 0
                ex_carbs = existing.get("carbs") or 0
                
                # Check content equality
                if abs(ex_ins - item_ins) < 0.001 and abs(ex_carbs - item_carbs) < 0.1:
                    is_duplicate = True
                    # Merge Metadata: If the discarded item has Fat/Protein that the existing one lacks, keep it.
                    # This fixes the case where NS record (Fat=0) shadows DB/Local record (Fat=45).
                    if not existing.get("fat") and item.get("fat"):
                        existing["fat"] = item["fat"]
                    if not existing.get("protein") and item.get("protein"):
                        existing["protein"] = item["protein"]
                    if not existing.get("fiber") and item.get("fiber"):
                        existing["fiber"] = item["fiber"]
                    break
        
        if not is_duplicate:
            unique_treatments.append(item)
            
    return unique_treatments[:count] 


@router.get("/entries", summary="Get SGV entries with optional filtering")
async def get_entries(
    count: int = 288,
    full_history: bool = False, # If true, might fetch more?
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), # To access filter settings
):
    ns = await get_ns_config(session, user.username)
    if not ns or not ns.enabled or not ns.url:
         raise HTTPException(status_code=400, detail="Nightscout is not configured")
    
    from app.services.smart_filter import CompressionDetector, FilterConfig
    
    # 1. Fetch raw entries
    entries = []
    treatments = []
    
    # Construct Filter Config from Settings (or NS Settings if we moved them to DB? 
    # For now, we use global settings as per prompt request "Add in config")
    f_config = FilterConfig(
        enabled=settings.nightscout.filter_compression,
        night_start_hour=settings.nightscout.filter_night_start,
        night_end_hour=settings.nightscout.filter_night_end,
        drop_threshold_mgdl=settings.nightscout.filter_drop_mgdl,
        rebound_threshold_mgdl=settings.nightscout.filter_rebound_mgdl,
        rebound_window_minutes=settings.nightscout.filter_window_min
    )
    
    try:
        client = NightscoutClient(base_url=ns.url, token=ns.api_secret, timeout_seconds=10)
        try:
            # Parallel fetch?
            # entries = await client.get_sgv_range(...) # client needs update to expose get_sgv_range public or reuse internal
            # We used _handle_response so get_sgv_range is available in client instance
            
            # Calc start date for 'count' or 'hours'
            # Default 24h
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(hours=24)
            
            # Fetch Entries
            entries = await client.get_sgv_range(start_dt, end_dt, count=count)
            
            # Fetch Treatments (for context)
            if f_config.enabled:
                treatments = await client.get_recent_treatments(hours=24, limit=100)
                
        finally:
            await client.aclose()
            
        # 2. Run Filter
        detector = CompressionDetector(config=f_config)
        
        # Convert Pydanitc models to dicts for enriching
        entries_dicts = [e.model_dump() for e in entries]
        treatments_dicts = [t.model_dump() for t in treatments]
        
        processed_entries = detector.detect(entries_dicts, treatments_dicts)
        
        return processed_entries
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Entries fetch failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))


class TreatmentUpdate(BaseModel):
    insulin: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    protein: Optional[float] = None
    fiber: Optional[float] = None
    created_at: Optional[str] = None # ISO format
    notes: Optional[str] = None

@router.put("/treatments/{id}", summary="Update treatment (Local DB / Nightscout)")
async def update_treatment(
    id: str,
    payload: TreatmentUpdate,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    import logging
    logger = logging.getLogger(__name__)
    
    from app.models.treatment import Treatment
    from app.models.basal import BasalEntry
    from sqlalchemy import select
    
    updated_in_db = False
    
    # 1. Local DB (Treatments/Bolus)
    import uuid
    is_uuid = len(id) >= 24
    try:
        # Try with current user first
        stmt = select(Treatment).where(Treatment.id == id, Treatment.user_id == user.username)
        res = await session.execute(stmt)
        db_item = res.scalar_one_or_none()
        
        # Fallback: Search by ID only if it looks like a unique identifier
        if not db_item and is_uuid:
            stmt = select(Treatment).where(Treatment.id == id)
            res = await session.execute(stmt)
            db_item = res.scalar_one_or_none()
        
        if db_item:
             if payload.insulin is not None: db_item.insulin = payload.insulin
             if payload.carbs is not None: db_item.carbs = payload.carbs
             if payload.fat is not None: db_item.fat = payload.fat
             if payload.protein is not None: db_item.protein = payload.protein
             if payload.fiber is not None: db_item.fiber = payload.fiber
             if payload.notes is not None: db_item.notes = payload.notes
             if payload.created_at:
                 try:
                     dt = datetime.fromisoformat(payload.created_at.replace("Z", "+00:00"))
                     db_item.created_at = dt.astimezone(timezone.utc).replace(tzinfo=None)
                 except:
                     pass
             
             db_item.is_uploaded = False
             await session.commit()
             updated_in_db = True
             
    except Exception as e:
        logger.error(f"Error updating local DB treatment: {e}")
        
    # 1.1 Local DB (Basal)
    if not updated_in_db:
        try:
            # Handle UUID conversion for basal_dose table
            target_uuid = None
            try: target_uuid = uuid.UUID(id)
            except: pass
            
            if target_uuid:
                stmt = select(BasalEntry).where(BasalEntry.id == target_uuid, BasalEntry.user_id == user.username)
                res = await session.execute(stmt)
                basal_item = res.scalar_one_or_none()
                
                # Fallback: ID only
                if not basal_item:
                    stmt = select(BasalEntry).where(BasalEntry.id == target_uuid)
                    res = await session.execute(stmt)
                    basal_item = res.scalar_one_or_none()
            
                if basal_item:
                    if payload.insulin is not None: basal_item.dose_u = payload.insulin
                    if payload.created_at:
                        try:
                            dt = datetime.fromisoformat(payload.created_at.replace("Z", "+00:00"))
                            basal_item.effective_from = dt.date()
                            basal_item.created_at = dt.astimezone(timezone.utc).replace(tzinfo=None)
                        except:
                            pass
                    
                    await session.commit()
                    updated_in_db = True
        except Exception as e:
            logger.error(f"Error updating local basal dose: {e}")
            
    # 2. Nightscout (Propagate or Primary)
    ns_updated = False
    
    is_uuid = len(id) >= 24 # Relaxed check to include potential UUIDs or Nightscout IDs
    
    if not updated_in_db:
         ns = await get_ns_config(session, user.username)
         if ns and ns.enabled and ns.url:
             try:
                 client = NightscoutClient(ns.url, ns.api_secret)
                 ns_payload = {}
                 if payload.insulin is not None: ns_payload["insulin"] = payload.insulin
                 if payload.carbs is not None: ns_payload["carbs"] = payload.carbs
                 if payload.fat is not None: ns_payload["fat"] = payload.fat
                 if payload.protein is not None: ns_payload["protein"] = payload.protein
                 if payload.fiber is not None: ns_payload["fiber"] = payload.fiber
                 if payload.notes is not None: ns_payload["notes"] = payload.notes
                 if payload.created_at: ns_payload["created_at"] = payload.created_at
                 
                 await client.update_treatment(id, ns_payload)
                 await client.aclose()
                 ns_updated = True
             except Exception as e:
                 logger.error(f"Error updating NS treatment: {e}")
                 # If it had a UUID length, we expected to find it locally. 
                 # But we still tried NS. If both failed, we'll return 404 below.
                 if not updated_in_db and not is_uuid:
                      raise HTTPException(status_code=500, detail=f"Failed to update treatment: {str(e)}")

    if not updated_in_db and not ns_updated:
        raise HTTPException(status_code=404, detail="Treatment not found in Local DB or Nightscout")

    return {"success": True, "updated_db": updated_in_db, "updated_ns": ns_updated}


@router.delete("/treatments/{id}", summary="Delete treatment")
async def delete_treatment(
    id: str,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    store: DataStore = Depends(_data_store)
):
    from app.models.treatment import Treatment
    from app.models.basal import BasalEntry
    from sqlalchemy import select
    import logging
    logger = logging.getLogger(__name__)
    
    deleted_in_db = False
    
    # 1. Local DB (Treatments)
    import uuid
    is_uuid = len(id) >= 24
    try:
        # Try with current user first
        stmt = select(Treatment).where(Treatment.id == id, Treatment.user_id == user.username)
        res = await session.execute(stmt)
        db_item = res.scalar_one_or_none()
        
        # Fallback: Search by ID only
        if not db_item and is_uuid:
            stmt = select(Treatment).where(Treatment.id == id)
            res = await session.execute(stmt)
            db_item = res.scalar_one_or_none()
            
        if db_item:
            await session.delete(db_item)
            await session.commit()
            deleted_in_db = True
    except Exception as e:
         logger.error(f"Error deleting from DB: {e}")
         
    # 1.1 Local DB (Basal)
    if not deleted_in_db:
        try:
            # Handle UUID conversion for basal_dose table
            target_uuid = None
            try: target_uuid = uuid.UUID(id)
            except: pass
            
            if target_uuid:
                stmt = select(BasalEntry).where(BasalEntry.id == target_uuid, BasalEntry.user_id == user.username)
                res = await session.execute(stmt)
                basal_item = res.scalar_one_or_none()
                
                # Fallback: ID only
                if not basal_item:
                    stmt = select(BasalEntry).where(BasalEntry.id == target_uuid)
                    res = await session.execute(stmt)
                    basal_item = res.scalar_one_or_none()
                    
                if basal_item:
                    await session.delete(basal_item)
                    await session.commit()
                    deleted_in_db = True
        except Exception as e:
             logger.error(f"Error deleting basal from DB: {e}")

    # 1.5 Local File Store (Backup)
    # Ensure it doesn't reappear from the backup file
    try:
        events = store.load_events()
        original_len = len(events)
        # Filter (check both 'id' and '_id')
        filtered_events = [e for e in events if str(e.get('id', '')) != id and str(e.get('_id', '')) != id]
        
        if len(filtered_events) < original_len:
            store.save_events(filtered_events)
            logger.info(f"Deleted treatment {id} from local file store.")
    except Exception as e:
        logger.error(f"Error deleting from local file store: {e}")

             
    # 2. Nightscout (Always attempt sync)
    ns_deleted = False
    
    ns = await get_ns_config(session, user.username)
    if ns and ns.enabled and ns.url:
         try:
             client = NightscoutClient(ns.url, ns.api_secret)
             await client.delete_treatment(id)
             await client.aclose()
             ns_deleted = True
         except Exception as e:
             logger.error(f"Error deleting from NS: {e}")
             # Only raise error if we failed both Local AND Nightscout
             if not deleted_in_db:
                  is_uuid = len(id) >= 24
                  if not is_uuid:
                       raise HTTPException(status_code=500, detail=f"Failed to delete: {str(e)}")

    if not deleted_in_db and not ns_deleted:
        # If we found it in file store, it's effectively a success too?
        # But we usually require DB/NS presence.
        # Let's verify file store deletion count? 
        # Actually returning 404 is fine if it wasn't in DB/NS as those are primary.
        # But if it was ONLY in file store (unlikely for "treatment"), we might want to say success.
        pass
        
    # Simplify return: if we deleted from ANY source, it's success.
    # But effectively, if we didn't raise exception above, we are OK or 404.
    if not deleted_in_db and not ns_deleted:
         raise HTTPException(status_code=404, detail="Treatment not found")
         
    return {"success": True, "deleted_db": deleted_in_db, "deleted_ns": ns_deleted}
