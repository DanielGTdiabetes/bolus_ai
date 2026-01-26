
import logging
from datetime import datetime
from typing import List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.suggestion import ParameterSuggestion
from app.services.pattern_analysis import get_summary_service

logger = logging.getLogger(__name__)

from app.models.settings import UserSettings
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config
from app.services.isf_analysis_service import IsfAnalysisService

async def generate_isf_suggestions(
    user_id: str,
    days: int,
    db: AsyncSession,
    settings: UserSettings
) -> dict:
    """
    Analyzes ISF using IsfAnalysisService and creates suggestions if needed.
    """
    created_count = 0
    skipped_count = 0
    
    # 1. Setup Client
    ns_cfg = await get_ns_config(db, user_id)
    if not ns_cfg or not ns_cfg.url:
        return {"created": 0, "skipped": 0, "status": "no_ns_config"}
        
    client = NightscoutClient(ns_cfg.url, ns_cfg.api_secret, timeout_seconds=30)
    
    try:
        # 2. Setup Analysis
        # Profile construction from UserSettings
        current_cf = {
            "breakfast": getattr(settings.cf, "breakfast", 30.0),
            "lunch": getattr(settings.cf, "lunch", 30.0),
            "dinner": getattr(settings.cf, "dinner", 30.0)
        }
        profile_settings = {
            "dia_hours": getattr(settings.iob, "dia_hours", 4.0),
            "curve": getattr(settings.iob, "curve", "bilinear"),
            "peak_minutes": getattr(settings.iob, "peak_minutes", 75)
        }
        
        service = IsfAnalysisService(client, current_cf, profile_settings, db_session=db)
        
        # 3. Run Analysis
        # Use days provided, default to 14 if too small? ISF needs data.
        # analysis_days = max(days, 7) 
        result = await service.run_analysis(user_id, days=days)
        
        # 4. Process Results
        actionable = [b for b in result.buckets if b.status in ["strong_drop", "weak_drop"] and b.confidence == "high"]
        
        for item in actionable:
            direction = "decrease" if item.suggestion_type == "decrease" else "increase"
            
            # Check trivial change
            if abs(item.current_isf - item.suggested_isf) < 1.0:
                skipped_count += 1
                continue

            # Check existing
            stmt = select(ParameterSuggestion).where(
                ParameterSuggestion.user_id == user_id,
                ParameterSuggestion.meal_slot == item.bucket_name,
                ParameterSuggestion.parameter == "isf",
                ParameterSuggestion.status == "pending"
            )
            existing = await db.execute(stmt)
            if existing.scalars().first():
                skipped_count += 1
                continue
                
            # Create
            reason_text = f"Análisis ISF ({item.label}): Detectado cambio significativo. "
            if direction == "increase":
                reason_text += "La insulina está cayendo MÁS de lo esperado (Sensible). Se sugiere subir factor."
            else:
                reason_text += "La insulina está cayendo MENOS de lo esperado (Resistente). Se sugiere bajar factor."
            
            new_sug = ParameterSuggestion(
                user_id=user_id,
                meal_slot=item.bucket_name,
                parameter="isf",
                direction=direction,
                reason=reason_text,
                evidence={
                    "source": "isf_analysis_service",
                    "change_ratio": item.change_ratio,
                    "confidence": item.confidence,
                    "old_isf": item.current_isf,
                    "new_isf": item.suggested_isf,
                    "median_observed": item.median_isf,
                    "days_analyzed": days
                },
                status="pending",
                created_at=datetime.utcnow()
            )
            db.add(new_sug)
            created_count += 1
            
    except Exception as e:
        logger.error(f"ISF Generation failed for {user_id}: {e}")
        return {"created": created_count, "skipped": skipped_count, "error": str(e)}
    finally:
        await client.aclose()
        
    return {"created": created_count, "skipped": skipped_count}

async def generate_suggestions_service(
    user_id: str,
    days: int,
    db: AsyncSession,
    settings: UserSettings = None
) -> dict:
    
    summary = await get_summary_service(user_id, days, db, settings=settings)
    by_meal = summary.get("by_meal", {})
    
    created_count = 0
    skipped_count = 0
    
    # 2. Iterate and Evaluate
    for meal_slot, windows in by_meal.items():
        for window_key, counts in windows.items():
            # counts: {short, ok, over, missing, unavailable_iob}
            
            total_valid = counts["short"] + counts["ok"] + counts["over"]
            total_total = total_valid + counts["unavailable_iob"]
            
            # Min Sample
            if total_valid < 5:
                continue
                
            # Quality Check <= 30% unavailable
            if total_total > 0:
                bad_ratio = counts["unavailable_iob"] / total_total
                if bad_ratio > 0.30:
                    continue
            
            short_ratio = counts["short"] / total_valid
            over_ratio = counts["over"] / total_valid
            
            suggestion_type = None
            direction = None
            reason_text = ""
            
            # Logic Mapping
            if short_ratio >= 0.60:
                # Short = High BG
                if window_key in ["2h", "3h"]:
                    suggestion_type = "icr"
                    direction = "review" # or increase insulin -> decrease ratio
                    reason_text = f"En {translate_slot(meal_slot)}, a las {window_key}, tiendes a quedarte corto (glucemia alta) en el {int(short_ratio*100)}% de los casos."
                elif window_key == "5h":
                    suggestion_type = "target" # or basal/strategy
                    direction = "review"
                    reason_text = f"En {translate_slot(meal_slot)}, a las 5h, persistes alto en el {int(short_ratio*100)}% de los casos. Podría ser basal o objetivo."
            
            elif over_ratio >= 0.60:
                # Over = Low BG (User provided definition: delta < -30)
                # Usually "over" bolus means logic resulted in Hypo?
                # Let's check pattern analysis: delta = bg - target. 
                # if delta < -30 (e.g. 70 - 110 = -40), yes it's Low.
                # So "Over" means "Over-dosed" (too much insulin).
                suggestion_type = "icr"
                direction = "review"
                reason_text = f"En {translate_slot(meal_slot)}, a las {window_key}, tiendes a pasarte (bajadas excesivas) en el {int(over_ratio*100)}% de los casos."
            
            if suggestion_type:
                # Prepare evidence
                evidence = {
                    "window": window_key,
                    "counts": counts,
                    "ratio": round(max(short_ratio, over_ratio), 2),
                    "days": days,
                    "quality_ok": True
                }

                # Calculate Proposed Value (if settings available)
                if settings and suggestion_type == "icr":
                    current_val = getattr(settings.cr, meal_slot, None)
                    if current_val:
                        evidence["current_value"] = float(current_val)
                        # High BG (Short) -> Stronger Ratio (Lower CR)
                        if short_ratio >= 0.60:
                            # Decrease by 10%
                            proposed = round(current_val * 0.9, 1)
                            if proposed >= current_val: proposed = current_val - 0.5 # Force diff
                            evidence["suggested_value"] = max(2.0, proposed)
                        
                        # Low BG (Over) -> Weaker Ratio (Higher CR)
                        elif over_ratio >= 0.60:
                             # Increase by 10%
                            proposed = round(current_val * 1.1, 1)
                            if proposed <= current_val: proposed = current_val + 0.5
                            evidence["suggested_value"] = proposed

                        # Filter trivial
                        if abs(evidence.get("suggested_value", 0) - evidence.get("current_value", 0)) < 0.1:
                            continue
                
                
                # Check for existing pending
                # We only allow one pending suggestion per slot+param
                stmt = select(ParameterSuggestion).where(
                    ParameterSuggestion.user_id == user_id,
                    ParameterSuggestion.meal_slot == meal_slot,
                    ParameterSuggestion.parameter == suggestion_type,
                    ParameterSuggestion.status == "pending"
                )
                existing = await db.execute(stmt)
                if existing.scalars().first():
                    skipped_count += 1
                    continue
                
                # Create
                new_sug = ParameterSuggestion(
                    user_id=user_id,
                    meal_slot=meal_slot,
                    parameter=suggestion_type,
                    direction=direction,
                    reason=reason_text,
                    evidence=evidence,
                    status="pending",
                    created_at=datetime.utcnow()
                )
                db.add(new_sug)
                created_count += 1
    
    # 3. ISF Analysis Integration
    # Only run if settings available (needed for profile/targets)
    if settings:
        try:
            isf_res = await generate_isf_suggestions(user_id, days, db, settings)
            created_count += isf_res.get("created", 0)
            skipped_count += isf_res.get("skipped", 0)
        except Exception as e:
            logger.error(f"Failed to generate ISF suggestions: {e}")
                
    await db.commit()
    return {"created": created_count, "skipped": skipped_count, "days": days}

async def get_suggestions_service(user_id: str, status: str, db: AsyncSession):
    stmt = select(ParameterSuggestion).where(
        ParameterSuggestion.user_id == user_id
    )
    if status:
        stmt = stmt.where(ParameterSuggestion.status == status)
        
    stmt = stmt.order_by(ParameterSuggestion.created_at.desc())
    
    result = await db.execute(stmt)
    return result.scalars().all()

async def resolve_suggestion_service(
    id: str, 
    user_id: str, 
    action: str, # accept/reject
    note: str, 
    db: AsyncSession,
    proposed_change: dict = None
):
    stmt = select(ParameterSuggestion).where(
        ParameterSuggestion.id == id,
        ParameterSuggestion.user_id == user_id
    )
    result = await db.execute(stmt)
    sug = result.scalars().first()
    
    if not sug:
        return None
        
    if action == "reject":
        sug.status = "rejected"
    elif action == "accept":
        sug.status = "accepted"
        # Since we don't automatically apply settings in backend (user rule), 
        # we just track the intent. The frontend updates localStorage.
        # Ideally we store what was accepted in resolution_note or extend the model later.
        if proposed_change:
            note = f"{note} (Proposal: {proposed_change})"
            
    sug.resolved_at = datetime.utcnow()
    sug.resolution_note = note
    
    await db.commit()
    return sug

def translate_slot(s):
    m = {"breakfast": "Desayuno", "lunch": "Comida", "dinner": "Cena", "snack": "Snack"}
    return m.get(s, s)
