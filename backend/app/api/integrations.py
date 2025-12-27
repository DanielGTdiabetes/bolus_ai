from fastapi import APIRouter, Depends, HTTPException, Body, Response
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import logging
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, and_

from app.core.security import get_current_user_optional, CurrentUser
from app.api.bolus import save_treatment
from app.services.store import DataStore
from app.core.settings import get_settings, Settings
from app.core.db import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
logger = logging.getLogger(__name__)

def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    from pathlib import Path
    return DataStore(Path(settings.data.data_dir))

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

    food_name: Optional[str] = Field(default=None, alias="name")
    calories: Optional[float] = Field(default=0, alias="active_energy_burned") # A veces viene aquí o en dietary_energy
    
    timestamp: Optional[str] = Field(default=None, alias="date") # ISO format preferred
    
    # Generic bucket
    metrics: Optional[List[Dict[str, Any]]] = None # Health Auto Export suele mandar una lista de métricas

@router.post("/nutrition", summary="Webhook for Health Auto Export / External Nutrition")
async def ingest_nutrition(
    payload: Dict[str, Any] = Body(...), # Usamos Dict raw par analizar la estructura variable
    user: Optional[CurrentUser] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Recibe datos de nutrición externos (Health Auto Export, n8n, Shortcuts).
    Crea un tratamiento con insulin=0 (Orphan) para que el frontend lo detecte.
    Es "silencioso": si falla, no rompe nada, solo loguea error.
    """
    try:
        username = user.username if user else "admin"
        
        # 1. Normalización de Datos (Health Auto Export manda una lista "data": [...])
        # Buscamos carbs, fat, protein en el payload bruto
        
        data_points = []
        if "data" in payload and isinstance(payload["data"], list):
             # Formato Health Auto Export
             data_points = payload["data"]
        elif "metrics" in payload:
             data_points = payload["metrics"]
        else:
             # Formato simple plano
             data_points = [payload]
             
        # Agregación (por si vienen varios items en el mismo push)
        total_carbs = 0.0
        total_fat = 0.0
        total_protein = 0.0
        last_ts = datetime.now(timezone.utc)
        notes_list = []
        
        for item in data_points:
            # Detectar claves comunes
            c = item.get("dietary_carbohydrates") or item.get("carbs") or item.get("Carbohydrates") or 0
            f = item.get("dietary_fat") or item.get("fat") or item.get("Fat") or 0
            p = item.get("dietary_protein") or item.get("protein") or item.get("Protein") or 0
            
            # Unidades? A veces vienen con "g" o "qty"
            try:
                if isinstance(c, dict): c = c.get("qty", 0)
                if isinstance(f, dict): f = f.get("qty", 0)
                if isinstance(p, dict): p = p.get("qty", 0)
                
                total_carbs += float(c)
                total_fat += float(f)
                total_protein += float(p)
            except:
                continue

            # Timestamp
            ts_str = item.get("date") or item.get("timestamp")
            if ts_str:
                try:
                    last_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except:
                    pass
            
            # Nombres
            name = item.get("name") or item.get("food_name")
            if name: notes_list.append(name)

        if total_carbs == 0 and total_fat == 0 and total_protein == 0:
            return {"success": False, "message": "No macros found"}

        # 2. Guardar como Tratamiento "Huerfano"
        # Usamos insulin=0 para marcarlo como pendiente de gestión
        treatment_id = str(uuid.uuid4())
        
        notes = "External Import"
        if notes_list:
            notes += ": " + ", ".join(notes_list[:3]) # Limit length
        notes += " #imported"
        
        if session:
            from app.models.treatment import Treatment
            
            # --- DEDUPLICATION CHECK ---
            # Check if we already received identical macros in the last 15 mins
            dedup_window = datetime.now(timezone.utc) - timedelta(minutes=15)
            
            stmt = select(Treatment).where(
                Treatment.created_at >= dedup_window,
                Treatment.carbs == total_carbs,
                Treatment.fat == total_fat,
                Treatment.protein == total_protein,
                Treatment.entered_by == "webhook-integration"
            )
            result = await session.execute(stmt)
            existing = result.scalars().first()
            
            if existing:
                logger.info("Ingest Skipped: Duplicate data detected within 15 min.")
                return {"success": True, "status": "duplicate_skipped", "id": existing.id}
            
            # --- END DEDUPLICATION ---
            
            # DB Save Direct
            
            new_t = Treatment(
                id=treatment_id,
                user_id=username,
                event_type="Meal Bolus", 
                created_at=last_ts,
                insulin=0.0,      # THE KEY: 0 insulin = Orphan
                carbs=total_carbs,
                fat=total_fat,
                protein=total_protein,
                notes=notes,
                entered_by="webhook-integration",
                is_uploaded=False
            )
            session.add(new_t)
            await session.commit()
            
            logger.info(f"Ingested Nutrition: {total_carbs}g C, {total_fat}g F, {total_protein}g P")
            
        return {"success": True, "id": treatment_id, "ingested": {"c": total_carbs, "f": total_fat, "p": total_protein}}
        
    except Exception as e:
        logger.error(f"Nutrition Ingest Error: {e}")
        # Return 200 to not break the sender, but log error
        return {"success": False, "error": str(e)}
