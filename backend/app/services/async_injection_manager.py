
from typing import Dict, Any, Optional, List
from pathlib import Path
from sqlalchemy.future import select
from app.core.db import get_engine, AsyncSession
from app.models.injection import InjectionState
from app.services.injection_sites import ZONES
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class AsyncInjectionManager:
    """
    Manages injection sites using the Database for persistence.
    Replaces DataStore file-based logic.
    """
    
    def __init__(self, user_id: str = "admin"):
        self.user_id = user_id
        self._fallback_mgr = None

    def _get_fallback_mgr(self):
        if self._fallback_mgr:
            return self._fallback_mgr
        try:
            from app.core.settings import get_settings
            from app.services.store import DataStore
            from app.services.injection_sites import InjectionManager
            data_dir = get_settings().data.data_dir
            self._fallback_mgr = InjectionManager(DataStore(Path(data_dir)))
        except Exception as e:
            logger.error(f"Failed to initialize fallback injection manager: {e}")
            self._fallback_mgr = None
        return self._fallback_mgr
        
    def _normalize_kind(self, kind: str) -> str:
        key = (kind or "").lower()
        if key in ("rapid", "bolus"):
            return "rapid"
        if key == "basal":
            return "basal"
        raise ValueError(f"Invalid insulin type: {kind}")

    def _empty_state(self) -> Dict[str, Any]:
        return {
            "rapid": { "last_used_id": "abd_l_top:1", "source": "default", "updated_at": None },
            "basal": { "last_used_id": "glute_right:1", "source": "default", "updated_at": None }
        }

    def _canonicalize_state(self, raw_state: Dict[str, Any]) -> Dict[str, Any]:
        base = self._empty_state()
        for raw_key, payload in (raw_state or {}).items():
            try:
                key = self._normalize_kind(raw_key)
            except ValueError:
                continue
            base[key].update({
                "last_used_id": payload.get("last_used_id", base[key]["last_used_id"]),
                "source": payload.get("source", base[key]["source"]),
                "updated_at": payload.get("updated_at", base[key]["updated_at"]),
            })
        return base

    async def get_state(self) -> Dict[str, Any]:
        """Loads state from DB, falls back to defaults."""
        engine = get_engine()
        state = self._empty_state()
        
        if not engine:
            fallback = self._get_fallback_mgr()
            if fallback:
                return self._canonicalize_state(fallback._load_state())
            return state
            
        async with AsyncSession(engine) as session:
            try:
                stmt = select(InjectionState).where(InjectionState.user_id == self.user_id)
                result = await session.execute(stmt)
                rows = result.scalars().all()
                for row in rows:
                    try:
                        key = self._normalize_kind(row.plan)
                    except ValueError:
                        continue
                    state[key]["last_used_id"] = row.last_used_id
                    state[key]["source"] = (row.source or "auto")
                    state[key]["updated_at"] = row.updated_at.isoformat() if row.updated_at else None
            except Exception as e:
                logger.error(f"Failed to load injection state from DB: {e}")
                
        return state

    def _validate_site_id(self, kind: str, site_id: str) -> str:
        """Validate/normalize against known zones. Supports numeric indices."""
        key = self._normalize_kind(kind)
        zones = ZONES[key]
        raw = str(site_id).strip()
        if not raw:
            raise ValueError("point_id is required")

        # Numeric index support (1-based across flattened points)
        if raw.isdigit():
            idx = int(raw)
            flat: List[str] = []
            for z in zones:
                for i in range(1, z["count"] + 1):
                    flat.append(f"{z['id']}:{i}")
            if idx < 1 or idx > len(flat):
                raise ValueError(f"point index {idx} fuera de rango")
            return flat[idx - 1]

        # Explicit zone:point
        if ":" in raw:
            zone_id, point_str = raw.split(":", 1)
            zone = next((z for z in zones if z["id"] == zone_id), None)
            if not zone:
                raise ValueError(f"Zona inválida: {zone_id}")
            try:
                point = int(point_str)
            except ValueError as e:
                raise ValueError("Punto debe ser numérico") from e
            if point < 1 or point > zone["count"]:
                raise ValueError(f"Punto {point} fuera de rango para {zone_id}")
            return f"{zone_id}:{point}"

        # Zone without point -> assume :1
        zone = next((z for z in zones if z["id"] == raw), None)
        if not zone:
            raise ValueError(f"Zona inválida: {raw}")
        return f"{raw}:1"

    async def _save_plan_site(self, plan: str, site_id: str, source: str):
        """Saves a single plan's site to DB or fallback store."""
        plan_key = self._normalize_kind(plan)
        engine = get_engine()
        if not engine:
            fallback = self._get_fallback_mgr()
            if not fallback:
                raise RuntimeError("Database engine not available for AsyncInjectionManager")
            fallback.set_current_site(plan_key, site_id, source=source)
            return
            
        async with AsyncSession(engine) as session:
            # Robust Native Upsert (dialect aware)
            dialect = engine.dialect.name if engine else "unknown"
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as dialect_insert
            elif dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert as dialect_insert
            else:
                from sqlalchemy import insert as dialect_insert

            if plan_key == "rapid":
                await session.execute(
                    "DELETE FROM injection_states WHERE user_id=:user_id AND plan=:plan",
                    {"user_id": self.user_id, "plan": "bolus"},
                )

            stmt = dialect_insert(InjectionState).values(
                user_id=self.user_id,
                plan=plan_key,
                last_used_id=site_id,
                source=source,
                updated_at=datetime.now(timezone.utc)
            )
            
            # If exists, update
            if hasattr(stmt, "on_conflict_do_update"):
                stmt = stmt.on_conflict_do_update(
                    index_elements=['user_id', 'plan'],
                    set_=dict(
                        last_used_id=stmt.excluded.last_used_id, 
                        source=stmt.excluded.source,
                        updated_at=stmt.excluded.updated_at
                    )
                )
            else:
                # Fallback: manual merge
                await session.execute(
                    f"DELETE FROM injection_states WHERE user_id=:user_id AND plan=:plan",
                    {"user_id": self.user_id, "plan": plan}
                )
            
            await session.execute(stmt)
            await session.commit()
            logger.info(f"DB PERSIST (Native): {self.user_id} {plan} -> {site_id} ({source})")

    # --- Public Async Methods mirroring the old API ---

    async def get_next_site(self, kind: str = "bolus") -> Dict[str, Any]:
        engine = get_engine()
        key = self._normalize_kind(kind)
        if not engine:
            fallback = self._get_fallback_mgr()
            if fallback:
                return fallback.get_next_site(key)
        state = await self.get_state()
        last_id = state.get(key, {}).get("last_used_id")
        next_id = self._calc_next(key, last_id)
        return self._get_site_from_id(key, next_id)

    async def get_last_site(self, kind: str = "bolus") -> Optional[Dict[str, Any]]:
        engine = get_engine()
        key = self._normalize_kind(kind)
        if not engine:
            fallback = self._get_fallback_mgr()
            if fallback:
                return fallback.get_last_site(key)
        state = await self.get_state()
        last_id = state.get(key, {}).get("last_used_id")
        if not last_id: return None
        return self._get_site_from_id(key, last_id)

    async def rotate_site(self, kind: str = "bolus") -> Dict[str, Any]:
        engine = get_engine()
        key = self._normalize_kind(kind)
        if not engine:
            fallback = self._get_fallback_mgr()
            if fallback:
                return fallback.rotate_site(key)
        state = await self.get_state()
        last_id = state.get(key, {}).get("last_used_id")
        
        next_id = self._calc_next(key, last_id)
        
        # Save Async
        await self._save_plan_site(key, next_id, source="auto")
        
        return self._get_site_from_id(key, next_id)

    async def set_current_site(self, kind: str, site_id: str, source: str = "manual"):
        """Manual set from Frontend."""
        key = self._normalize_kind(kind)
        normalized = self._validate_site_id(key, site_id)
        engine = get_engine()
        if not engine:
            fallback = self._get_fallback_mgr()
            if fallback:
                fallback.set_current_site(key, normalized, source=source)
                return normalized
        await self._save_plan_site(key, normalized, source=source)
        
        # Verification is implied by await commit() raising if failed
        return normalized

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
