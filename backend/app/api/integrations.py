import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.user_settings_resolver import resolve_bot_user_settings
from app.core import config
from app.core.db import get_db_session
from app.core.security import TokenManager, get_token_manager, get_current_user, CurrentUser
from app.core.settings import Settings, get_settings
from app.services.store import DataStore

router = APIRouter()
logger = logging.getLogger(__name__)

def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    from pathlib import Path
    return DataStore(Path(settings.data.data_dir))


def _extract_value(payload: Dict[str, Any], keys: List[str]) -> Optional[float]:
    for key in keys:
        current = payload
        parts = key.split(".")
        try:
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    current = None
                    break
            if current is None:
                continue
            if isinstance(current, (int, float, str)):
                return float(current)
        except Exception:
            continue
    return None


def normalize_nutrition_payload(payload: Dict[str, Any]) -> Dict[str, Optional[float]]:
    carbs = _extract_value(payload, [
        "carbs", "dietary_carbohydrates", "total_carbs", "Carbohydrates",
        "carbohydrates_total_g", "nutrition.carbs", "nutrients.carbs"
    ])
    fat = _extract_value(payload, [
        "fat", "dietary_fat", "total_fat", "fat_total_g",
        "nutrition.fat", "nutrients.fat"
    ])
    protein = _extract_value(payload, [
        "protein", "dietary_protein", "total_protein", "protein_total_g",
        "nutrition.protein", "nutrients.protein"
    ])
    fiber = _extract_value(payload, [
        "fiber", "fiber_total_g", "fiber_alt", "dietary_fiber", "total_fiber",
        "fibra", "t_fiber", "nutrients.fiber", "nutrition.fiber"
    ])
    timestamp = payload.get("date") or payload.get("timestamp") or payload.get("created_at")
    return {
        "carbs": carbs,
        "fat": fat,
        "protein": protein,
        "fiber": fiber,
        "timestamp": timestamp
    }


def should_update_fiber(existing_fiber: Optional[float], new_fiber: Optional[float], tolerance: float = 0.1) -> bool:
    if new_fiber is None:
        return False
    base = existing_fiber or 0.0
    return abs(base - new_fiber) >= tolerance


def is_valid_ingestion(carbs: float, fat: float, protein: float, fiber: float) -> bool:
    total_grams = (carbs or 0.0) + (fat or 0.0) + (protein or 0.0) + (fiber or 0.0)
    return total_grams > 0.0


def _resolve_import_source(notes: Optional[str]) -> str:
    if not notes:
        return "Auto Export"
    normalized = notes.lower()
    if "myfitnesspal" in normalized:
        return "MyFitnessPal"
    if "healthkit" in normalized:
        return "HealthKit"
    if "auto export" in normalized or "autoexport" in normalized:
        return "Auto Export"
    if "health auto export" in normalized or "imported from health" in normalized:
        return "Auto Export"
    return "Auto Export"

# Modelo flexible para Health Auto Export o n8n
class NutritionPayload(BaseModel):
    # Campos comunes en exportaciones de salud
    carbs: Optional[float] = Field(default=0, alias="dietary_carbohydrates")
    fat: Optional[float] = Field(default=0, alias="dietary_fat")
    protein: Optional[float] = Field(default=0, alias="dietary_protein")
    
    # Soporte para nombres alternativos (n8n o MFP directo)
    carbs_alt: Optional[float] = Field(default=None, alias="carbohydrates_total_g")
    fat_alt: Optional[float] = Field(default=None, alias="fat_total_g")
    protein_alt: Optional[float] = Field(default=None, alias="protein_total_g")
    fiber_alt: Optional[float] = Field(default=None, alias="fiber_total_g")
    
    # Common simple names
    fiber: Optional[float] = Field(default=0, alias="dietary_fiber")

    food_name: Optional[str] = Field(default=None, alias="name")
    calories: Optional[float] = Field(default=0, alias="active_energy_burned") # A veces viene aquí o en dietary_energy
    
    timestamp: Optional[str] = Field(default=None, alias="date") # ISO format preferred
    
    # Generic bucket
    metrics: Optional[List[Dict[str, Any]]] = None # Health Auto Export suele mandar una lista de métricas

@router.post("/nutrition", summary="Webhook for Health Auto Export / External Nutrition")
async def ingest_nutrition(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    ingest_key_header: Optional[str] = Header(None, alias="X-Ingest-Key"),
    session: AsyncSession = Depends(get_db_session),
    token_manager: TokenManager = Depends(get_token_manager),
    settings: Settings = Depends(get_settings),
):
    """
    Recibe datos de nutrición externos (Health Auto Export, n8n, Shortcuts).
    Crea un tratamiento con insulin=0 (Orphan) para que el frontend lo detecte.
    Es "silencioso": si falla, no rompe nada, solo loguea error.
    """
    # Payload Safety Check (2MB Limit) - Added for Audit Remediation
    body_bytes = await request.body()
    if len(body_bytes) > 2 * 1024 * 1024:
        logger.warning(f"Payload too large: {len(body_bytes)} bytes")
        raise HTTPException(status_code=413, detail="Payload too large (>2MB)")

    # Initialize DataStore locally or via dependency if preferred, here we use settings for path
    
    # 0. EMERGENCY MODE CHECK
    if settings.emergency_mode:
        logger.warning("⛔ Nutrition Ingest REJECTED due to Emergency Mode.")
        return {"success": 0, "message": "Ignored: System in Emergency Mode"}

    from pathlib import Path
    from app.services.store import DataStore
    ds = DataStore(Path(settings.data.data_dir))
    
    # 0. DEBUG LOGGING
    ingest_id = str(uuid.uuid4())[:8]
    log_entry = {
        "id": ingest_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "headers": {
            "user_agent": request.headers.get("user-agent"),
            "content_type": request.headers.get("content-type"),
            "x_ingest_key": "REDACTED" if ingest_key_header else None
        },
        "status": "pending",
        "result": None
    }
    
    # Helper to append log safely
    def append_log(entry):
        try:
            logs = ds.read_json("ingest_logs.json", [])
            # Keep last 50
            logs.insert(0, entry)
            if len(logs) > 50:
                logs = logs[:50]
            ds.write_json("ingest_logs.json", logs)
        except Exception as e:
            logger.error(f"Failed to write ingest log: {e}")

    try:

        auth_error = HTTPException(
            status_code=401,
            detail={"success": 0, "error": "Authentication required for nutrition ingest"},
        )

        username: Optional[str] = None
        bearer_value = authorization or ""
        bearer_token = None

        if bearer_value.lower().startswith("bearer "):
            bearer_token = bearer_value.split(" ", 1)[1].strip()

        if bearer_token:
            try:
                payload_token = token_manager.decode_token(bearer_token, expected_type="access")
                subject = payload_token.get("sub")
                username = str(subject) if subject is not None else None
            except HTTPException:
                raise auth_error
        else:
            query_params = request.query_params
            provided_key = ingest_key_header or (query_params.get("key") if hasattr(query_params, "get") else None)
            ingest_secret = os.getenv("NUTRITION_INGEST_SECRET") or os.getenv("NUTRITION_INGEST_KEY")

            if ingest_secret and provided_key == ingest_secret:
                source = "header" if ingest_key_header else "query"
                logger.info("nutrition_ingest authorized via key (%s)", source)
            else:
                reason = "missing secret" if not ingest_secret else "invalid key"
                logger.warning("Nutrition ingest rejected via key (%s)", reason)
                log_entry["status"] = "error"
                log_entry["result"] = {"error": "Authentication failed", "reason": reason}
                append_log(log_entry)
                raise auth_error

        if not username:
            # Align webhook user with bot/default user resolution so the app sees the meal
            username = config.get_bot_default_username() or None

        if not username:
            try:
                # Reuse the bot resolver to pick the active user (prefers non-default settings)
                _, resolved_user = await resolve_bot_user_settings()
                username = resolved_user
            except Exception as resolver_exc:
                logger.warning(f"Nutrition ingest: failed to resolve user, falling back to admin: {resolver_exc}")
                username = None

        if not username:
            username = "admin"

        raw_payload = payload
        is_wrapper_payload = isinstance(payload, dict) and isinstance(payload.get("payload"), dict)
        real_payload = (
            payload.get("payload")
            if is_wrapper_payload
            else payload
        )
        source_payload = real_payload if isinstance(real_payload, dict) else raw_payload
        source = source_payload.get("source") or source_payload.get("provider") or source_payload.get("app") or source_payload.get("origin") or "unknown"
        norm_log = normalize_nutrition_payload(source_payload)
        logger.info(
            "nutrition_ingest_start ingest_id=%s user_id=%s source=%s carbs=%s fat=%s protein=%s fiber=%s timestamp=%s",
            ingest_id,
            username,
            source,
            norm_log.get("carbs"),
            norm_log.get("fat"),
            norm_log.get("protein"),
            norm_log.get("fiber"),
            norm_log.get("timestamp"),
        )
        logger.info(
            "nutrition_ingest_payload ingest_id=%s wrapper=%s",
            ingest_id,
            "wrapper" if is_wrapper_payload else "direct",
        )

        # 1. Normalización de Datos (Health Auto Export manda una lista "data": [...])
        # Buscamos carbs, fat, protein en el payload bruto
        
        # 1. Complex Parser for Health Auto Export (Aggregated Metrics)
        # Structure: { "data": { "metrics": [ { "name": "total_fat", "data": [ {date, qty}, ... ] }, ... ] } }
        
        parsed_meals = {} # Key: timestamp string -> {c: 0, f: 0, p: 0, dt: datetime}
        
        metrics_list = []
        # Locate the metrics array deeply nested or flat
        if "data" in real_payload and isinstance(real_payload["data"], dict) and "metrics" in real_payload["data"]:
             metrics_list = real_payload["data"]["metrics"]
        elif "data" in real_payload and isinstance(real_payload["data"], list):
             # Sometimes it's a list of export objects?
             if len(real_payload["data"]) > 0 and "metrics" in real_payload["data"][0]:
                 metrics_list = real_payload["data"][0].get("metrics", [])
                 # Or weird structure in user example: [ { data: { metrics: [...] } } ]
                 if not metrics_list and "data" in real_payload["data"][0]:
                      metrics_list = real_payload["data"][0]["data"].get("metrics", [])
        elif "metrics" in real_payload:
             metrics_list = real_payload["metrics"]

        
        if metrics_list:
            logger.info("nutrition_ingest_metrics ingest_id=%s metric_groups=%s", ingest_id, len(metrics_list))
            for metric in metrics_list:
                # Normalize name: lower case AND replace spaces with underscores (e.g. "Dietary Fiber" -> "dietary_fiber")
                m_name = metric.get("name", "").lower().replace(" ", "_")
                m_data = metric.get("data", [])
                
                metric_type = None
                if m_name in ["carbohydrates", "dietary_carbohydrates", "total_carbs", "hkquantitytypeidentifierdietarycarbohydrates"]: metric_type = "c"
                elif m_name in ["total_fat", "dietary_fat", "fat", "hkquantitytypeidentifierdietaryfattotal"]: metric_type = "f"
                elif m_name in ["protein", "dietary_protein", "total_protein", "hkquantitytypeidentifierdietaryprotein"]: metric_type = "p"
                elif m_name in ["fiber", "dietary_fiber", "total_fiber", "hkquantitytypeidentifierdietaryfiber", "fibra", "fibra_dietetica", "fibra_total"]: metric_type = "fib"
                
                if metric_type and isinstance(m_data, list):
                    for entry in m_data:
                        # entry: {date: "2025-...", qty: "..."}
                        raw_date = entry.get("date")
                        entry_source = entry.get("source")
                        
                        # Fix Qty logic:
                        # Sometimes qty is string "36.6", sometimes number 36.6
                        raw_qty_val = entry.get("qty", 0)
                        try:
                            raw_qty = float(raw_qty_val)
                        except:
                            raw_qty = 0.0
                        
                        # Normalize date key (strip seconds/timezone to group near-simultaneous entries?)
                        # HealthKit data for same meal usually shares EXACT timestamp down to second
                        if raw_date:
                            if raw_date not in parsed_meals:
                                parsed_meals[raw_date] = {
                                    "c": 0.0,
                                    "f": 0.0,
                                    "p": 0.0,
                                    "fib": 0.0,
                                    "ts": raw_date,
                                    "source": entry_source,
                                    "fiber_provided": False,
                                }
                            elif entry_source and not parsed_meals[raw_date].get("source"):
                                parsed_meals[raw_date]["source"] = entry_source
                            
                            # Add to existing (in case multiple entries for same type/time? unlikely but safe)
                            # Actually, usually unique per type per time.
                            parsed_meals[raw_date][metric_type] += raw_qty
                            if metric_type == "fib":
                                parsed_meals[raw_date]["fiber_provided"] = True
        
        else:
             # Support for "Type", "Value" flat format (Shortcuts/Raw Export)
             if "Type" in real_payload and "Value" in real_payload:
                 p_type = real_payload.get("Type", "")
                 p_val = real_payload.get("Value", 0)
                 p_date = real_payload.get("Date") or real_payload.get("StartDate")
                 
                 # Map Type
                 metric_type = None
                 if p_type in ["DietaryFiber", "Fiber", "DietaryFiber"]: metric_type = "fib"
                 elif p_type in ["DietaryCarbohydrates", "Carbohydrates", "Carbs"]: metric_type = "c"
                 elif p_type in ["DietaryFatTotal", "Fat", "DietaryFat"]: metric_type = "f"
                 elif p_type in ["DietaryProtein", "Protein"]: metric_type = "p"
                 
                 if metric_type:
                     try:
                         val = float(p_val)
                         # Use Date or Now
                         ts_key = p_date or datetime.now(timezone.utc).isoformat()
                         
                         if ts_key not in parsed_meals:
                             parsed_meals[ts_key] = {"c":0.0, "f":0.0, "p":0.0, "fib":0.0, "ts": ts_key, "fiber_provided": False}
                         
                         parsed_meals[ts_key][metric_type] += val
                         if metric_type == "fib":
                             parsed_meals[ts_key]["fiber_provided"] = True
                         logger.info(f"Parsed Flat Payload: {metric_type}={val} from {p_type}")
                         
                     except ValueError:
                         pass
            
             else:
                 # FALLBACK: Try Direct Flat Keys (Simple JSON / n8n / Shortcuts)
                 norm = normalize_nutrition_payload(real_payload)
                 c_raw = norm.get("carbs")
                 f_raw = norm.get("fat")
                 p_raw = norm.get("protein")
                 fib_raw = norm.get("fiber")

                 c = float(c_raw) if c_raw is not None else 0.0
                 f = float(f_raw) if f_raw is not None else 0.0
                 p = float(p_raw) if p_raw is not None else 0.0
                 fib = float(fib_raw) if fib_raw is not None else None
                 fiber_provided = fib_raw is not None
                 
                 if c > 0 or f > 0 or p > 0 or (fib is not None and fib > 0):
                     ts_key = norm.get("timestamp") or real_payload.get("timestamp") or real_payload.get("created_at") or datetime.now(timezone.utc).isoformat()
                     parsed_meals[ts_key] = {
                         "c": c,
                         "f": f,
                         "p": p,
                         "fib": fib if fib is not None else 0.0,
                         "ts": ts_key,
                         "fiber_provided": fiber_provided
                     }
                     logger.info(f"Parsed Direct Payload: C={c} F={f} P={p} Fib={fib}")

        if not parsed_meals:
             res = {"success": 0, "message": "No parseable metrics found in payload"}
             log_entry["status"] = "rejected"
             log_entry["result"] = res
             append_log(log_entry)
             return res

        # 2. Process distinct meals found
        # Sort by date descending (newest first)
        sorted_keys = sorted(parsed_meals.keys(), reverse=True)
        logger.info("nutrition_ingest_timestamps ingest_id=%s unique_timestamps=%s", ingest_id, len(sorted_keys))

        for date_key in sorted_keys:
            meal = parsed_meals[date_key]
            logger.info(
                "nutrition_ingest_meal ingest_id=%s timestamp=%s carbs=%s fat=%s protein=%s fiber=%s source=%s",
                ingest_id,
                date_key,
                meal.get("c"),
                meal.get("f"),
                meal.get("p"),
                meal.get("fib"),
                meal.get("source"),
            )

        created_ids = []
        updated_ids = []
        updated_count = 0
        skipped_count = 0
        
        if session:
            from app.models.treatment import Treatment
            
            # Use top 500 recent meals (extended history)
            count = 0 
            for date_key in sorted_keys:
                if count >= 500: break
                
                meal = parsed_meals[date_key]
                t_carbs = round(meal["c"], 1)
                t_fat = round(meal["f"], 1)
                t_protein = round(meal["p"], 1)
                fiber_provided = meal.get("fiber_provided", False)
                t_fiber_raw = meal.get("fib", 0)
                t_fiber = round(float(t_fiber_raw or 0), 1)
                incoming_fiber = t_fiber if fiber_provided else None
                
                if t_carbs < 1 and t_fat < 1 and t_protein < 1 and t_fiber < 1: continue

                # Parse Date with Force-Now Logic
                force_now = False
                try:
                    ts_str = meal["ts"]
                    now_utc = datetime.now(timezone.utc)
                    item_ts = None
                    
                    # Multi-format date parser
                    parse_formats = [
                        "%Y-%m-%d %H:%M:%S %z",
                        "%Y-%m-%dT%H:%M:%S%z",
                        "%Y-%m-%dT%H:%M:%S.%f%z",
                        "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%dT%H:%M:%S.%fZ",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M:%S",
                    ]
                    
                    for fmt in parse_formats:
                        try:
                            clean_ts = datetime.strptime(ts_str, fmt)
                            if clean_ts.tzinfo is not None:
                                item_ts = clean_ts.astimezone(timezone.utc)
                            else:
                                from zoneinfo import ZoneInfo
                                tz_local = ZoneInfo("Europe/Madrid")
                                item_ts = clean_ts.replace(tzinfo=tz_local).astimezone(timezone.utc)
                            break
                        except ValueError:
                            continue
                    
                    # Fallback fromisoformat
                    if item_ts is None:
                        try:
                            clean_str = ts_str.replace("Z", "+00:00")
                            parsed = datetime.fromisoformat(clean_str)
                            if parsed.tzinfo is None:
                                from zoneinfo import ZoneInfo
                                parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Madrid"))
                            item_ts = parsed.astimezone(timezone.utc)
                        except Exception:
                            pass
                    
                    # Fallback NOW
                    if item_ts is None:
                        item_ts = now_utc
                        force_now = True
                        
                except Exception as e:
                    logger.warning(f"Date parse soft-fail: {ts_str} -> {e}. Using NOW.")
                    item_ts = datetime.now(timezone.utc)
                    force_now = True

                logger.info(
                    "nutrition_ingest_timestamp ingest_id=%s ts_raw=%s ts_parsed=%s force_now=%s",
                    ingest_id,
                    ts_str,
                    item_ts.isoformat(),
                    force_now,
                )

                # 0. STRICT DEDUP CHECK (History-based)
                # Check if we have already imported this specific external timestamp/ID.
                # This handles cases where we "snap to now" and thus lose the temporal correlation 
                # with the original event in the DB's created_at field.
                import_sig = f"Imported from Health: {date_key} #imported"
                stmt_strict = select(Treatment).where(Treatment.notes.contains(import_sig))
                result_strict = await session.execute(stmt_strict)
                existing_strict = result_strict.scalars().first()
                


                if existing_strict:
                     # Check for ANY meaningful change (Correction/Edit in Source)
                     changes = []
                     existing_carbs = float(existing_strict.carbs or 0)
                     existing_fat = float(existing_strict.fat or 0)
                     existing_protein = float(existing_strict.protein or 0)
                     if abs(existing_carbs - t_carbs) > 0.1:
                         existing_strict.carbs = t_carbs
                         changes.append("carbs")
                     if abs(existing_fat - t_fat) > 0.1:
                         existing_strict.fat = t_fat
                         changes.append("fat")
                     if abs(existing_protein - t_protein) > 0.1:
                         existing_strict.protein = t_protein
                         changes.append("protein")
                     
                     # Fiber Update
                     if fiber_provided and incoming_fiber is not None:
                         if should_update_fiber(existing_strict.fiber, incoming_fiber):
                             existing_strict.fiber = float(incoming_fiber)
                             changes.append("fiber")

                     if changes:
                         current_note = existing_strict.notes or ""
                         if "[Updated]" not in current_note:
                            existing_strict.notes = current_note + " [Updated]"

                         session.add(existing_strict)
                         await session.commit()
                         updated_count += 1
                         updated_ids.append(existing_strict.id)  # Track for notification
                         logger.info(
                             "nutrition_ingest_action ingest_id=%s action=update id=%s timestamp=%s changes=%s",
                             ingest_id,
                             existing_strict.id,
                             date_key,
                             changes,
                         )
                     else:
                         skipped_count += 1
                         logger.info(
                             "nutrition_ingest_action ingest_id=%s action=skip id=%s timestamp=%s",
                             ingest_id,
                             existing_strict.id,
                             date_key,
                         )
                     continue

                # Dedup check
                # Rule: Short window (3h) for the NEWEST meal (count=0) to allow repeat meals.
                # Rule: Long window (18h) for HISTORY to prevent re-importing old meals.
                
                if force_now:
                    check_window_hours = 3.0 if count == 0 else 18.0
                else:
                    check_window_hours = 0.5 

                dedup_window_end = (item_ts + timedelta(minutes=15)).replace(tzinfo=None)
                dedup_window_start = (item_ts - timedelta(hours=check_window_hours)).replace(tzinfo=None)
                
                stmt = select(Treatment).where(
                    Treatment.user_id == username,
                    Treatment.created_at >= dedup_window_start,
                    Treatment.created_at <= dedup_window_end,
                    Treatment.carbs >= (t_carbs - 1.0), # Relaxed search window (Carbs match strict)
                    Treatment.carbs <= (t_carbs + 1.0)
                )
                result = await session.execute(stmt)
                candidates = result.scalars().all()
                
                is_duplicate = False
                for c in candidates:
                    # Check if it's the same meal (Carbs very close)
                    if abs(c.carbs - t_carbs) < 0.5:
                        
                        # ENRICHMENT CHECK:
                        # If existing lacks Fat/Protein/Fiber and incoming HAS it, update it.
                        # Or if incoming matches (duplicate).
                        
                        c_fat = c.fat or 0
                        c_prot = c.protein or 0
                        c_fib = c.fiber or 0
                        
                        # 1. Exact Match (Duplicate)
                        if abs(c_fat - t_fat) < 0.5 and abs(c_prot - t_protein) < 0.5:
                             # Check Fiber Update
                             if fiber_provided and incoming_fiber is not None:
                                 if should_update_fiber(float(c_fib), incoming_fiber):
                                     c.fiber = float(incoming_fiber)
                                     session.add(c)
                                     await session.commit()
                                     updated_count += 1
                                     updated_ids.append(c.id) # Track for notification (Fiber update)
                                     logger.info(
                                         "nutrition_ingest_action ingest_id=%s action=update id=%s timestamp=%s changes=%s",
                                         ingest_id,
                                         c.id,
                                         date_key,
                                         ["fiber"],
                                     )
                             is_duplicate = True
                             skipped_count += 1
                             logger.info(
                                 "nutrition_ingest_action ingest_id=%s action=skip id=%s timestamp=%s",
                                 ingest_id,
                                 c.id,
                                 date_key,
                             )
                             break
                        
                        # 2. Enrichment (Existing is 'smaller' than incoming in terms of info)
                        # We assume if Carbs match and time is close, it IS the same meal.
                        # Especially if existing has 0 fat/prot and new has > 0.
                        
                        is_enrichment = False
                        if t_fat > (c_fat + 0.5) or t_protein > (c_prot + 0.5):
                             is_enrichment = True
                        
                        # If Enrichment, UPDATE the existing one
                        if is_enrichment:
                             c.fat = float(t_fat)
                             c.protein = float(t_protein)
                             if fiber_provided and incoming_fiber is not None:
                                 c.fiber = float(incoming_fiber)
                             
                             c.notes = (c.notes or "") + " [Enriched]"
                             session.add(c)
                             await session.commit()
                             updated_count += 1
                             updated_ids.append(c.id) # Track for notification (Macro enrichment)
                             logger.info(
                                 "nutrition_ingest_action ingest_id=%s action=update id=%s timestamp=%s changes=%s",
                                 ingest_id,
                                 c.id,
                                 date_key,
                                 ["fat", "protein", "fiber"],
                             )
                             is_duplicate = True
                             break

                        # 3. Fiber Only Enrichment
                        if fiber_provided and incoming_fiber is not None and abs((c.fiber or 0) - incoming_fiber) > 0.1:
                             c.fiber = float(incoming_fiber)
                             session.add(c)
                             await session.commit()
                             updated_count += 1
                             updated_ids.append(c.id) # Track
                             logger.info(
                                 "nutrition_ingest_action ingest_id=%s action=update id=%s timestamp=%s changes=%s",
                                 ingest_id,
                                 c.id,
                                 date_key,
                                 ["fiber"],
                             )
                             is_duplicate = True
                             break
                             
                
                if is_duplicate:
                    continue
                
                # New Treatment
                tid = str(uuid.uuid4())
                
                # Ensure created_at is UTC Naive for DB
                db_created_at = item_ts.astimezone(timezone.utc).replace(tzinfo=None)
                
                new_t = Treatment(
                    id=tid,
                    user_id=username,
                    event_type="Meal Bolus", 
                    created_at=db_created_at,
                    insulin=0.0,
                    carbs=t_carbs,
                    fat=t_fat,
                    protein=t_protein,
                    fiber=t_fiber,
                    notes=f"Imported from Health: {date_key} #imported",
                    entered_by="webhook-integration",
                    is_uploaded=False
                )
                session.add(new_t)
                created_ids.append(tid)
                count += 1
                logger.info(
                    "nutrition_ingest_action ingest_id=%s action=create id=%s timestamp=%s",
                    ingest_id,
                    tid,
                    date_key,
                )
                
            await session.commit()
            
            # Notification Phase: Trigger for BOTH created (New) and updated (Enriched/Corrected) meals
            all_ids = list(set(created_ids + updated_ids))

            if all_ids:
                logger.info(
                    "nutrition_ingest_summary ingest_id=%s created_count=%s updated_count=%s skipped_count=%s notify_candidates=%s",
                    ingest_id,
                    len(created_ids),
                    len(updated_ids),
                    skipped_count,
                    len(all_ids),
                )
                
                try:
                    from app.bot.service import on_new_meal_received
                    from app.models.treatment import Treatment
                    
                    # 1. Fetch Objects
                    treatments_to_notify = []
                    for tid in all_ids:
                        t_obj = await session.get(Treatment, tid)
                        if t_obj:
                            treatments_to_notify.append(t_obj)
                        else:
                            logger.warning(f"nutrition_notify_skip event_id={tid} reason=missing_after_commit")

                    # 2. Sort Chronologically (Oldest Meal First)
                    treatments_to_notify.sort(key=lambda x: x.created_at)

                    # 3. Notify Loop
                    for t_obj in treatments_to_notify:
                        chat_id = config.get_allowed_telegram_user_id()
                        if not chat_id:
                            logger.info(f"nutrition_notify_skip event_id={t_obj.id} reason=no_chat_id")
                            continue
                        
                        # Validate Macros (skip empty notifications)
                        if not is_valid_ingestion(t_obj.carbs, t_obj.fat, t_obj.protein, t_obj.fiber):
                            logger.info(f"nutrition_notify_skip event_id={t_obj.id} reason=invalid_macros")
                            continue
                        
                        # Determine Source label
                        is_update = t_obj.id in updated_ids
                        notify_source = "Actualizado" if is_update else "Importado"

                        logger.info(f"nutrition_notify_enqueue event_id={t_obj.id} user_id={username} chat_id={chat_id} source={notify_source}")
                        try:
                            await on_new_meal_received(
                                t_obj.carbs, 
                                t_obj.fat or 0.0, 
                                t_obj.protein or 0.0, 
                                t_obj.fiber or 0.0, 
                                f"{notify_source} ({username})", 
                                origin_id=t_obj.id
                            )
                        except Exception as inner_e:
                            logger.error(f"Failed to send individual notification for {t_obj.id}: {inner_e}")

                except Exception as e:
                    logger.error(f"Failed to trigger bot notification batch: {e}")

                res = {"success": 1, "ingested_count": len(created_ids), "updated_count": len(updated_ids), "ids": all_ids}
                log_entry["status"] = "success"
                log_entry["result"] = res
                append_log(log_entry)
                return res
            else:
                logger.info(
                    "nutrition_ingest_summary ingest_id=%s created_count=%s updated_count=%s skipped_count=%s ids_count_unique=%s",
                    ingest_id,
                    len(created_ids),
                    updated_count,
                    skipped_count,
                    len(dict.fromkeys(created_ids)),
                )
                res = {"success": 1, "message": "No new meals found (all duplicates or empty)", "ingested_count": 0, "ids": []}
                log_entry["status"] = "ignored"
                log_entry["result"] = res
                append_log(log_entry)
                return res

        return {"success": 0, "message": "Database session missing"}
        
    except HTTPException:
        # Bubble up authentication errors or explicit HTTP responses
        raise
    except Exception as e:
        logger.error(f"Nutrition Ingest Error: {e}")
        # Return 200 to not break the sender, but log error
        res = {"success": 0, "error": str(e)}
        log_entry["status"] = "error"
        log_entry["result"] = res
        append_log(log_entry)
        return res


@router.get("/nutrition/recent", summary="Get recent imported nutrition entries")
async def get_recent_imported_nutrition(
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUser = Depends(get_current_user),
):
    from app.models.treatment import Treatment

    # Pending vs consumed:
    # - Pending imported meals are stored as treatments with insulin=0, entered_by=webhook-integration
    #   and a "#imported" marker in notes.
    # - When a bolus accepts/replaces an import (replace_id flow), the original treatment is deleted.
    #   Therefore, "consumed" imports are excluded by absence plus the insulin==0 filter below.
    stmt = (
        select(Treatment)
        .where(
            Treatment.user_id == user.username,
            Treatment.insulin == 0,
            Treatment.entered_by == "webhook-integration",
            Treatment.notes.contains("#imported"),
        )
        .order_by(Treatment.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    treatments = result.scalars().all()

    return [
        {
            "id": t.id,
            "timestamp": t.created_at.isoformat(),
            "source": _resolve_import_source(t.notes),
            "carbs": float(t.carbs or 0.0),
            "protein": float(t.protein or 0.0),
            "fat": float(t.fat or 0.0),
            "fiber": float(t.fiber or 0.0),
        }
        for t in treatments
    ]

@router.get("/nutrition/logs", summary="Get recent ingestion logs")
async def get_ingest_logs(
    settings: Settings = Depends(get_settings),
    user: CurrentUser = Depends(get_current_user)
):
    from pathlib import Path
    from app.services.store import DataStore
    ds = DataStore(Path(settings.data.data_dir))
    return ds.read_json("ingest_logs.json", [])
