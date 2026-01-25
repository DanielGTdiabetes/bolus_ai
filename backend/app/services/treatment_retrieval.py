
from datetime import datetime, timedelta, timezone
import logging
from typing import List, Optional, Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_engine
from app.models.treatment import Treatment as TreatmentSQL
from app.models.schemas import Treatment as TreatmentSchema

logger = logging.getLogger(__name__)

def _extract_field(source: Any, key: str) -> Optional[str]:
    if source is None:
        return None
    if isinstance(source, dict):
        value = source.get(key)
    else:
        value = getattr(source, key, None)
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def get_visible_treatment_name(treatment: Any) -> Optional[str]:
    for key in ("name", "food_name", "description", "title"):
        value = _extract_field(treatment, key)
        if value:
            return value
    return None


async def get_recent_treatments_db(
    hours: int = 24,
    username: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[TreatmentSchema]:
    """
    Fetches recent treatments directly from the local PostgreSQL database.
    Returns them as Pydantic schemas compatible with existing logic.
    """
    engine = get_engine()
    if not engine:
        logger.warning("DB Engine not available for treatment retrieval")
        return []

    async with AsyncSession(engine) as session:
        try:
            now_utc = datetime.now(timezone.utc)
            # created_at in DB is naive, usually stored as UTC but timezone-unaware.
            # We assume DB stores UTC as naive.
            cutoff = now_utc - timedelta(hours=hours)
            cutoff_naive = cutoff.replace(tzinfo=None)

            stmt = select(TreatmentSQL).where(TreatmentSQL.created_at >= cutoff_naive)
            if username:
                stmt = stmt.where(
                    or_(TreatmentSQL.user_id == username, TreatmentSQL.user_id.is_(None))
                )
            stmt = stmt.order_by(TreatmentSQL.created_at.desc())
            if limit:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()

            schemas = []
            for row in rows:
                # Convert Naive DB time back to Aware for logic
                aware_dt = row.created_at.replace(tzinfo=timezone.utc)
                
                schemas.append(TreatmentSchema(
                    _id=row.id,
                    eventType=row.event_type,
                    created_at=aware_dt,
                    enteredBy=row.entered_by,
                    insulin=row.insulin,
                    carbs=row.carbs,
                    fat=row.fat,
                    protein=row.protein,
                    fiber=row.fiber,
                    carb_profile=row.carb_profile,
                    notes=row.notes
                ))
            
            logger.info(f"Retrieved {len(schemas)} treatments from DB (last {hours}h)")
            return schemas

        except Exception as e:
            logger.error(f"Failed to fetch treatments from DB: {e}", exc_info=True)
            return []
