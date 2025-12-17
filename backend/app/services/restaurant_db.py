
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.restaurant_session import RestaurantSessionV2
from app.core.db import get_engine, get_db_session_context

class RestaurantDBService:
    @staticmethod
    async def create_session(
        user_id: str,
        expected_carbs: float,
        expected_fat: float,
        expected_protein: float,
        items: List[Dict[str, Any]],
        notes: str = ""
    ) -> RestaurantSessionV2:
        async with get_db_session_context() as session:
            if not session:
                # In-memory fallback or no-op if no DB
                return None
                
            new_session = RestaurantSessionV2(
                user_id=user_id,
                expected_carbs=expected_carbs,
                expected_fat=expected_fat,
                expected_protein=expected_protein,
                items_json={"items": items, "notes": notes},
                plates_json=[],
                started_at=datetime.utcnow()
            )
            session.add(new_session)
            await session.commit()
            await session.refresh(new_session)
            return new_session

    @staticmethod
    async def add_plate(
        session_id: str,
        plate_data: Dict[str, Any]
    ) -> Optional[RestaurantSessionV2]:
        async with get_db_session_context() as session:
            if not session: return None
            
            # Retrieve
            stmt = select(RestaurantSessionV2).where(RestaurantSessionV2.id == session_id)
            result = await session.execute(stmt)
            r_session = result.scalar_one_or_none()
            
            if not r_session:
                return None
                
            # Update plates list
            # We need to copy to trigger change detection for JSONB usually, or use append
            current_plates = list(r_session.plates_json)
            current_plates.append(plate_data)
            
            # Recalculate totals
            total_carbs = sum(p.get("carbs", 0) for p in current_plates)
            total_fat = sum(p.get("fat", 0) for p in current_plates)
            total_protein = sum(p.get("protein", 0) for p in current_plates)
            
            r_session.plates_json = current_plates
            r_session.actual_carbs = total_carbs
            r_session.actual_fat = total_fat
            r_session.actual_protein = total_protein
            
            # Calculate delta
            if r_session.expected_carbs is not None:
                r_session.delta_carbs = total_carbs - r_session.expected_carbs
            
            await session.commit()
            await session.refresh(r_session)
            return r_session

    @staticmethod
    async def finalize_session(
        session_id: str,
        outcome_score: Optional[int] = None
    ) -> Optional[RestaurantSessionV2]:
        async with get_db_session_context() as session:
            if not session: return None
            
            stmt = select(RestaurantSessionV2).where(RestaurantSessionV2.id == session_id)
            result = await session.execute(stmt)
            r_session = result.scalar_one_or_none()
            
            if not r_session: return None
            
            r_session.finalized_at = datetime.utcnow()
            if outcome_score is not None:
                r_session.outcome_score = outcome_score
                
            await session.commit()
            await session.refresh(r_session)
            return r_session
            
    @staticmethod
    async def get_recent_sessions(user_id: str, limit: int = 5) -> List[RestaurantSessionV2]:
        async with get_db_session_context() as session:
            if not session: return []
            
            stmt = select(RestaurantSessionV2).where(
                RestaurantSessionV2.user_id == user_id
            ).order_by(RestaurantSessionV2.started_at.desc()).limit(limit)
            
            result = await session.execute(stmt)
            return result.scalars().all()
