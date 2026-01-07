import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
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
):
    """
    Recibe datos de nutrición externos (Health Auto Export, n8n, Shortcuts).
    Crea un tratamiento con insulin=0 (Orphan) para que el frontend lo detecte.
    Es "silencioso": si falla, no rompe nada, solo loguea error.
    """
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

        # 1. Normalización de Datos (Health Auto Export manda una lista "data": [...])
        # Buscamos carbs, fat, protein en el payload bruto
        
        # 1. Complex Parser for Health Auto Export (Aggregated Metrics)
        # Structure: { "data": { "metrics": [ { "name": "total_fat", "data": [ {date, qty}, ... ] }, ... ] } }
        
        parsed_meals = {} # Key: timestamp string -> {c: 0, f: 0, p: 0, dt: datetime}
        
        metrics_list = []
        # Locate the metrics array deeply nested or flat
        if "data" in payload and isinstance(payload["data"], dict) and "metrics" in payload["data"]:
             metrics_list = payload["data"]["metrics"]
        elif "data" in payload and isinstance(payload["data"], list):
             # Sometimes it's a list of export objects?
             if len(payload["data"]) > 0 and "metrics" in payload["data"][0]:
                 metrics_list = payload["data"][0].get("metrics", [])
                 # Or weird structure in user example: [ { data: { metrics: [...] } } ]
                 if not metrics_list and "data" in payload["data"][0]:
                      metrics_list = payload["data"][0]["data"].get("metrics", [])
        elif "metrics" in payload:
             metrics_list = payload["metrics"]

        
        if metrics_list:
            logger.info(f"DEBUG: Found {len(metrics_list)} metric groups")
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
                                parsed_meals[raw_date] = {"c":0.0, "f":0.0, "p":0.0, "fib":0.0, "ts": raw_date, "fiber_provided": False}
                            
                            # Add to existing (in case multiple entries for same type/time? unlikely but safe)
                            # Actually, usually unique per type per time.
                            parsed_meals[raw_date][metric_type] += raw_qty
                            if metric_type == "fib":
                                parsed_meals[raw_date]["fiber_provided"] = True
        
        else:
             # Support for "Type", "Value" flat format (Shortcuts/Raw Export)
             if "Type" in payload and "Value" in payload:
                 p_type = payload.get("Type", "")
                 p_val = payload.get("Value", 0)
                 p_date = payload.get("Date") or payload.get("StartDate")
                 
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
                 norm = normalize_nutrition_payload(payload)
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
                     ts_key = norm.get("timestamp") or payload.get("timestamp") or payload.get("created_at") or datetime.now(timezone.utc).isoformat()
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
             return {"success": 0, "message": "No parseable metrics found in payload"}

        # 2. Process distinct meals found
        # Sort by date descending (newest first)
        sorted_keys = sorted(parsed_meals.keys(), reverse=True)
        
        # We only want to process RECENT meals (last 2 hours?) to avoid re-importing history
        # But we have dedup logic.
        
        processed_ids = []
        
        # Only take the top 5 most recent to avoid massive DB writes on full export
        for date_key in sorted_keys[:5]:
            meal = parsed_meals[date_key]
            total_carbs = meal["c"]
            total_fat = meal["f"]
            total_protein = meal["p"]
            total_fiber = meal.get("fib", 0)
            
            # Skip empty meals
            if total_carbs < 1 and total_fat < 1 and total_protein < 1 and total_fiber < 1:
                continue
                
            # Parse Date
            try:
                # "2025-12-26 13:01:00 +0100" -> ISO
                # replace space before timezone?
                # python format: "%Y-%m-%d %H:%M:%S %z"
                ts_str = meal["ts"]
                clean_ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S %z")
                # Convert to UTC
                last_ts = clean_ts.astimezone(timezone.utc)
            except:
                # Fallback
                last_ts = datetime.now(timezone.utc)
                
            # --- DEDUPLICATION LOGIC JOINED HERE ---
            # ...


            # --- MEAL SAVING LOOP ---
            
            # DB Save Direct
            if session:
                from app.models.treatment import Treatment

                # Loop through the processed meals (from the loop on line 125)
                # But wait, line 125 started a loop but didn't finish the save logic inside.
                # I need to MOVE the save logic INSIDE the loop.
                pass 
                
        # Re-implementing the loop properly here to replace the broken block
        saved_ids = []
        
        if session:
            from app.models.treatment import Treatment
            
            # Use top 5 recent meals
            count = 0 
            for date_key in sorted_keys:
                if count >= 5: break
                
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

                    # Check divergence
                    diff = (now_utc - item_ts).total_seconds()

                    # SNAP POLICY
                    # 1. If date is > 24 hours away (past or future) -> IGNORE (History dump / stale export).
                    # 2. If date is > 30 mins old but < 24h -> SNAP TO NOW (Timezone fix/Delay).
                    # 3. If date is "future" (> 5 mins ahead) -> SNAP TO NOW.

                    force_now = False

                    if abs(diff) > 86400: # Older than 24 hours (in past) OR too far in the future
                        logger.info(f"Skipping meal from {ts_str} (Diff: {abs(diff)/3600:.1f}h). Outside 24h window.")
                        continue

                    if diff < -300:
                        logger.info(f"Snapping future import time {ts_str} to NOW.")
                        item_ts = now_utc
                        force_now = True
                        
                except Exception as e:
                    logger.warning(f"Date parse soft-fail: {ts_str} -> {e}. Using NOW.")
                    item_ts = datetime.now(timezone.utc)
                    force_now = True

                # 0. STRICT DEDUP CHECK (History-based)
                # Check if we have already imported this specific external timestamp/ID.
                # This handles cases where we "snap to now" and thus lose the temporal correlation 
                # with the original event in the DB's created_at field.
                import_sig = f"Imported from Health: {date_key}"
                stmt_strict = select(Treatment).where(Treatment.notes.contains(import_sig))
                result_strict = await session.execute(stmt_strict)
                existing_strict = result_strict.scalars().first()
                
                # DRAFT LOGIC START
                # Criteria: Recent (< 45 min) or Future/ForcedNow
                is_recent_draft_candidate = False
                if force_now:
                    is_recent_draft_candidate = True
                else:
                    age_seconds = (now_utc - item_ts).total_seconds()
                    if 0 <= age_seconds < 2700: # 45 min
                        is_recent_draft_candidate = True

                if is_recent_draft_candidate:
                    logger.info(f"Routing meal to Draft (Carbs={t_carbs}, Recency={force_now or age_seconds})")
                    from app.services.nutrition_draft_service import NutritionDraftService
                    # Pass session now
                    draft, action = await NutritionDraftService.update_draft(
                        username, t_carbs, t_fat, t_protein, t_fiber, session
                    )
                    
                    # Notify Bot
                    try:
                        from app.bot.service import on_draft_updated
                        await on_draft_updated(username, draft, action)
                    except ImportError:
                        pass # Bot svc might not be fully ready or cyclic import
                    except Exception as e:
                        logger.error(f"Bot draft notify failed: {e}")
                        
                    # Explicit Early Return - Draft Handled
                    return {
                        "success": 1, 
                        "message": f"Draft {action}", 
                        "draft_status": draft.status,
                        "ids": [f"draft_{username}"]
                    }
                # DRAFT LOGIC END

                if existing_strict:
                     if should_update_fiber(existing_strict.fiber, incoming_fiber):
                         existing_strict.fiber = float(incoming_fiber)  # type: ignore[arg-type]
                         session.add(existing_strict)
                         await session.commit()
                         saved_ids.append(existing_strict.id)
                         logger.info("Updated fiber on strict-duplicate nutrition entry %s", existing_strict.id)
                     else:
                         logger.info(f"Skipping import {date_key} - found exact match in history (ID: {existing_strict.id})")
                     continue

                # Dedup check
                # Rule: Short window (3h) for the NEWEST meal (count=0) to allow repeat meals.
                # Rule: Long window (18h) for HISTORY to prevent re-importing old meals.
                
                if force_now:
                    check_window_hours = 3.0 if count == 0 else 18.0
                else:
                    check_window_hours = 0.2

                dedup_window_end = (item_ts + timedelta(minutes=10)).replace(tzinfo=None)
                dedup_window_start = (item_ts - timedelta(hours=check_window_hours)).replace(tzinfo=None)
                
                stmt = select(Treatment).where(
                    Treatment.user_id == username,
                    Treatment.created_at >= dedup_window_start,
                    Treatment.created_at <= dedup_window_end,
                    Treatment.carbs >= (t_carbs - 0.1),
                    Treatment.carbs <= (t_carbs + 0.1)
                )
                result = await session.execute(stmt)
                candidates = result.scalars().all()
                
                is_duplicate = False
                for c in candidates:
                    diff_fat = abs(c.fat - t_fat)
                    diff_prot = abs(c.protein - t_protein)
                    if diff_fat < 0.1 and diff_prot < 0.1:
                        if fiber_provided and incoming_fiber is not None:
                            diff_fiber = abs((c.fiber or 0.0) - incoming_fiber)
                            if diff_fiber >= 0.1:
                                c.fiber = float(incoming_fiber)  # type: ignore[arg-type]
                                session.add(c)
                                await session.commit()
                                saved_ids.append(c.id)
                                logger.info(
                                    "Updated fiber on existing nutrition entry %s (delta=%.2f)",
                                    c.id,
                                    diff_fiber,
                                )
                                is_duplicate = True
                                break

                        if should_update_fiber(c.fiber, incoming_fiber):
                            c.fiber = float(incoming_fiber)  # type: ignore[arg-type]
                            session.add(c)
                            await session.commit()
                            saved_ids.append(c.id)
                            logger.info("Updated fiber on existing nutrition entry %s", c.id)
                        is_duplicate = True
                        break
                
                if is_duplicate:
                    logger.info(f"Skipping duplicate meal {t_carbs}g from {ts_str} (ForceNow={force_now}, Win={check_window_hours}h)")
                    continue
                
                # New Treatment
                tid = str(uuid.uuid4())
                new_t = Treatment(
                    id=tid,
                    user_id=username,
                    event_type="Meal Bolus", 
                    created_at=item_ts.replace(tzinfo=None), # Ensure naive for consistency
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
                saved_ids.append(tid)
                count += 1
                
            await session.commit()
            
            if saved_ids:
                logger.info(f"Ingested {len(saved_ids)} new meals from export.")
                
                # Trigger Bot Notification for the NEWEST meal (first one we saved)
                # We iterate sorted_keys (newest first), so the first saved_id corresponds to the first successful iteration.
                # However, we didn't track which carbs corresponded to which saved ID easily in the list above without a map.
                # Simplified: Just grab the carbs from the FIRST iteration that worked.
                # Actually, let's just use the loop values.
                
                # We need to re-find the carb amount for the newest saved meal. 
                # Since we want to be fast and this is a async hook:
                try:
                    from app.bot.service import on_new_meal_received
                    # Finding the carb amount of the "primary" meal we just saved
                    # We saved distinct meals. Let's notify the largest/newest? 
                    # Let's just notify the very first one we saved (newest).
                    
                    # Re-loop to find what we saved? No, that's inefficient.
                    # Better: Capture it inside the loop.
                    # But since I can't edit the loop easily without a huge block...
                    # I will assume the payload was singular or we just query the DB for the ID we just saved.
                    
                    # Or simpler:
                    first_id = saved_ids[0]
                    # Fetch from session since it's in identity map
                    t_obj = await session.get(Treatment, first_id)
                    if t_obj and t_obj.carbs > 0:
                        # Fire and forget (task)? or await? 
                        # Await is fine, it shouldn't take too long.
                        await on_new_meal_received(t_obj.carbs, t_obj.fat or 0.0, t_obj.protein or 0.0, t_obj.fiber or 0.0, f"Importado ({username})", origin_id=first_id)
                        
                except Exception as e:
                    logger.error(f"Failed to trigger bot notification: {e}")

                return {"success": 1, "ingested_count": len(saved_ids), "ids": saved_ids}
            else:
                return {"success": 1, "message": "No new meals found (all duplicates or empty)"}

        return {"success": 0, "message": "Database session missing"}
        
    except HTTPException:
        # Bubble up authentication errors or explicit HTTP responses
        raise
    except Exception as e:
        logger.error(f"Nutrition Ingest Error: {e}")
        # Return 200 to not break the sender, but log error
        return {"success": 0, "error": str(e)}

# --- DRAFT ENDPOINTS ---

@router.get("/nutrition/draft", summary="Get active nutrition draft")
async def get_nutrition_draft(
    user: CurrentUser = Depends(get_current_user), # Require Auth
    session: AsyncSession = Depends(get_db_session)
):
    from app.services.nutrition_draft_service import NutritionDraftService
    draft = await NutritionDraftService.get_draft(user.username, session) # user.username might be user_id
    if not draft:
        return {"active": False}
    
    # Calculate remaining time
    now = datetime.now(timezone.utc)
    remaining_sec = (draft.expires_at - now).total_seconds()
    
    return {
        "active": True,
        "draft": draft.dict(),
        "remaining_seconds": max(0, remaining_sec),
        "formatted_macros": draft.total_macros()
    }

@router.post("/nutrition/draft/close", summary="Confirm and close draft")
async def close_nutrition_draft(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    from app.services.nutrition_draft_service import NutritionDraftService
    
    # 1. Close draft -> Treatment
    treatment, created, draft_closed = await NutritionDraftService.close_draft_to_treatment(
        user.username,
        session,
    )
    if not treatment:
        raise HTTPException(404, "No active draft")
    
    # 2. Save Treatment to DB
    # close_draft_to_treatment added draft update to session but didn't commit for atomicity with treatment save.
    # Treatment is not added to session yet.
    try:
        if created:
            session.add(treatment)
        if created or draft_closed:
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to save closed draft: {e}")
        raise HTTPException(500, "Database save failed")
        
    # 3. Trigger Bot (New Meal)
    carbs = treatment.carbs
    fat = treatment.fat
    protein = treatment.protein
    fiber = treatment.fiber
    notes = treatment.notes
    treatment_id = treatment.id
    try:
        if created:
            from app.bot.service import on_new_meal_received
            await on_new_meal_received(
                carbs, fat, protein, fiber,
                notes, origin_id=treatment_id
            )
    except Exception as e:
        logger.warning(f"Bot trigger failed: {e}")
        
    return {"success": True, "treatment_id": treatment_id}

@router.post("/nutrition/draft/discard", summary="Discard draft")
async def discard_nutrition_draft(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    from app.services.nutrition_draft_service import NutritionDraftService
    await NutritionDraftService.discard_draft(user.username, session)
    return {"success": True}
