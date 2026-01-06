
from typing import Dict, Any, Optional
from sqlalchemy.future import select
from app.core.db import get_engine, AsyncSession
from app.models.injection import InjectionState
from app.services.injection_sites import ZONES
import logging

logger = logging.getLogger(__name__)

class AsyncInjectionManager:
    """
    Manages injection sites using the Database for persistence.
    Replaces DataStore file-based logic.
    """
    
    def __init__(self, user_id: str = "admin"):
        self.user_id = user_id
        
    async def get_state(self) -> Dict[str, Any]:
        """Loads state from DB, falls back to defaults."""
        engine = get_engine()
        state = {
            "bolus": { "last_used_id": "abd_l_top:1" },
            "basal": { "last_used_id": "glute_right:1" }
        }
        
        if not engine:
            return state
            
        async with AsyncSession(engine) as session:
            try:
                stmt = select(InjectionState).where(InjectionState.user_id == self.user_id)
                result = await session.execute(stmt)
                rows = result.scalars().all()
                for row in rows:
                    if row.plan in state:
                        state[row.plan]["last_used_id"] = row.last_used_id
            except Exception as e:
                logger.error(f"Failed to load injection state from DB: {e}")
                
        return state

    async def _save_plan_site(self, plan: str, site_id: str):
        """Saves a single plan's site to DB."""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database engine not available for AsyncInjectionManager")
            
        async with AsyncSession(engine) as session:
            # Robust Native Upsert
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            
            stmt = pg_insert(InjectionState).values(
                user_id=self.user_id,
                plan=plan,
                last_used_id=site_id,
                updated_at=datetime.utcnow()
            )
            
            # If exists, update
            stmt = stmt.on_conflict_do_update(
                index_elements=['user_id', 'plan'],
                set_=dict(
                    last_used_id=stmt.excluded.last_used_id, 
                    updated_at=stmt.excluded.updated_at
                )
            )
            
            await session.execute(stmt)
            await session.commit()
            logger.info(f"DB PERSIST (Native): {self.user_id} {plan} -> {site_id}")

    # --- Public Async Methods mirroring the old API ---

    async def get_next_site(self, kind: str = "bolus") -> Dict[str, Any]:
        state = await self.get_state()
        key = "basal" if kind.lower() == "basal" else "bolus"
        last_id = state.get(key, {}).get("last_used_id")
        
        next_id = self._calc_next(key, last_id)
        return self._get_site_from_id(key, next_id)

    async def get_last_site(self, kind: str = "bolus") -> Optional[Dict[str, Any]]:
        state = await self.get_state()
        key = "basal" if kind.lower() == "basal" else "bolus"
        last_id = state.get(key, {}).get("last_used_id")
        if not last_id: return None
        return self._get_site_from_id(key, last_id)

    async def rotate_site(self, kind: str = "bolus") -> Dict[str, Any]:
        state = await self.get_state()
        key = "basal" if kind.lower() == "basal" else "bolus"
        last_id = state.get(key, {}).get("last_used_id")
        
        next_id = self._calc_next(key, last_id)
        
        # Save Async
        await self._save_plan_site(key, next_id)
        
        return self._get_site_from_id(key, next_id)

    async def set_current_site(self, kind: str, site_id: str):
        """Manual set from Frontend."""
        key = "basal" if kind.lower() == "basal" else "bolus"
        
        if ":" not in site_id:
             site_id = f"{site_id}:1"
             
        await self._save_plan_site(key, site_id)
        
        # Verification is implied by await commit() raising if failed

    # --- Copied Helpers (Stateless) ---
    def _calc_next(self, kind: str, current_id: str) -> str:
        # Same logic as original
        if not current_id: return ZONES[kind][0]["id"] + ":1"
        try:
            zone_id, point_str = current_id.split(":")
            point = int(point_str)
            zone_id = zone_id.strip()
            zone_list = ZONES[kind]
            idx = -1
            for i, z in enumerate(zone_list):
                if z["id"] == zone_id:
                    idx = i
                    break
            if idx == -1: return ZONES[kind][0]["id"] + ":1"
            current_zone = zone_list[idx]
            if point < current_zone["count"]:
                return f"{zone_id}:{point + 1}"
            else:
                next_idx = (idx + 1) % len(zone_list)
                return f"{zone_list[next_idx]['id']}:1"
        except:
             return ZONES[kind][0]["id"] + ":1"

    def _get_site_from_id(self, kind: str, full_id: str) -> Dict[str, Any]:
        # Same logic as original
        try:
            zone_id, point_str = full_id.split(":")
            zone = next((z for z in ZONES[kind] if z["id"] == zone_id), None)
            if not zone: 
                return {"id": full_id, "name": full_id, "emoji": "📍", "image": "body_full.png"}
            label = zone["label"]
            if zone["count"] > 1:
                label = f"{label} - Punto {point_str}"
            return {
                "id": full_id,
                "name": label,
                "emoji": zone.get("emoji", "📍"),
                "image": zone.get("image", "body_full.png")
            }
        except:
            return {"id": full_id, "name": full_id, "emoji": "📍", "image": "body_full.png"}

from datetime import datetime
