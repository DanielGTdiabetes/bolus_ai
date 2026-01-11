from pathlib import Path
from typing import List, Dict, Any, Optional
from app.services.store import DataStore
from datetime import datetime, timezone

# --- ZONES CONFIG (Matches Frontend) ---
# Added: emoji, image for Bot support
_RAPID_ZONES = [
    {"id": "abd_l_top", "label": "Abdomen Izquierdo (Arriba)", "count": 3, "emoji": "👈🟣", "image": "body_abdomen.png"},
    {"id": "abd_l_mid", "label": "Abdomen Izquierdo (Medio)", "count": 3, "emoji": "👈🟣", "image": "body_abdomen.png"},
    {"id": "abd_l_bot", "label": "Abdomen Izquierdo (Bajo)", "count": 3, "emoji": "👈🟣", "image": "body_abdomen.png"},
    {"id": "abd_r_top", "label": "Abdomen Derecho (Arriba)", "count": 3, "emoji": "🟣👉", "image": "body_abdomen.png"},
    {"id": "abd_r_mid", "label": "Abdomen Derecho (Medio)", "count": 3, "emoji": "🟣👉", "image": "body_abdomen.png"},
    {"id": "abd_r_bot", "label": "Abdomen Derecho (Bajo)", "count": 3, "emoji": "🟣👉", "image": "body_abdomen.png"},
]

ZONES = {
    "rapid": _RAPID_ZONES,
    "basal": [
        {"id": "leg_left", "label": "Muslo Izquierdo", "count": 1, "emoji": "👈🦵", "image": "body_legs.png"},
        {"id": "leg_right", "label": "Muslo Derecho", "count": 1, "emoji": "🦵👉", "image": "body_legs.png"},
        {"id": "glute_left", "label": "Glúteo Izquierdo", "count": 1, "emoji": "👈🍑", "image": "body_legs.png"},
        {"id": "glute_right", "label": "Glúteo Derecho", "count": 1, "emoji": "🍑👉", "image": "body_legs.png"}
    ]
}

# Legacy alias kept for compatibility with old disk state files or callers
ZONES["bolus"] = ZONES["rapid"]


class InjectionManager:
    def __init__(self, store: DataStore):
        self.store = store
        self.filename = "injection_state.json"
    
    def _normalize_kind(self, kind: str) -> str:
        k = (kind or "").lower()
        if k in ("rapid", "bolus"):
            return "rapid"
        if k == "basal":
            return "basal"
        raise ValueError(f"Tipo de insulina inválido: {kind}")
        
    def _load_state(self) -> Dict[str, Any]:
        default_state = {
            "rapid": { "last_used_id": "abd_l_top:1", "source": "default", "updated_at": None },
            "basal": { "last_used_id": "glute_right:1", "source": "default", "updated_at": None }
        }
        # LOGGING PROOF: Log the exact path being read
        import logging
        try:
            full_path = self.store._path(self.filename)
            logging.getLogger(__name__).info(f"InjectionManager loading state from: {full_path}")
        except:
            pass
            
        data = self.store.read_json(self.filename, default_state)
        if "bolus" in data and "rapid" not in data:
            data["rapid"] = data.pop("bolus")
        # Backfill missing metadata for backwards compatibility
        for key, defaults in default_state.items():
            data.setdefault(key, {})
            data[key].setdefault("last_used_id", defaults["last_used_id"])
            data[key].setdefault("source", defaults["source"])
            data[key].setdefault("updated_at", defaults["updated_at"])
        return data

    def _save_state(self, state: Dict[str, Any]):
        self.store.write_json(self.filename, state)

    def get_next_site(self, kind: str = "bolus") -> Dict[str, Any]:
        """Returns NEXT site object."""
        state = self._load_state()
        key = self._normalize_kind(kind)
        last_id = state.get(key, {}).get("last_used_id")
        
        # Calculate Next
        next_id = self._calc_next(key, last_id)
        return self._get_site_from_id(key, next_id)

    def get_last_site(self, kind: str = "bolus") -> Optional[Dict[str, Any]]:
        """Returns LAST site object."""
        state = self._load_state()
        key = self._normalize_kind(kind)
        last_id = state.get(key, {}).get("last_used_id")
        if not last_id: return None
        return self._get_site_from_id(key, last_id)
        
    def rotate_site(self, kind: str = "bolus") -> Dict[str, Any]:
        """Advances rotation and returns new site object."""
        state = self._load_state()
        key = self._normalize_kind(kind)
        last_id = state.get(key, {}).get("last_used_id")
        
        next_id = self._calc_next(key, last_id)
        
        # Save
        if key not in state: state[key] = {}
        state[key]["last_used_id"] = next_id
        state[key]["source"] = "auto"
        state[key]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_state(state)
        
        return self._get_site_from_id(key, next_id)


    def set_current_site(self, kind: str, site_id: str, source: str = "manual"):
        """Manual set from Frontend. Ensures Format zone_id:point."""
        import logging
        logger = logging.getLogger(__name__)
        
        state = self._load_state()
        key = self._normalize_kind(kind)
        
        # Validation: If site_id comes without point (e.g. "abd_l_top"), append :1
        if ":" not in site_id:
             site_id = f"{site_id}:1"
        
        # Enforce Limits (Sanity Check)
        try:
            z_id, p_str = site_id.split(":")
            p_val = int(p_str)
            # Find Zone config
            valid_zones = ZONES.get(key, [])
            tgt_zone = next((z for z in valid_zones if z["id"] == z_id), None)
            
            if tgt_zone:
                max_p = tgt_zone["count"]
                if p_val > max_p:
                    logger.warning(f"[InjectionManager] Point {p_val} exceeds max {max_p} for {z_id}. Clamping.")
                    site_id = f"{z_id}:{max_p}"
                elif p_val < 1:
                    site_id = f"{z_id}:1"
        except Exception as e:
            logger.error(f"Error validating site limits: {e}")
        
        old_id = state.get(key, {}).get("last_used_id", "unknown")
        
        if key not in state: state[key] = {}
        state[key]["last_used_id"] = site_id
        state[key]["source"] = source
        state[key]["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        # SAVE
        self._save_state(state)
        
        # VERIFY IMMEDIATE READBACK
        verification = self.store.read_json(self.filename, {})
        saved_val = verification.get(key, {}).get("last_used_id")
        
        if saved_val != site_id:
            logger.error(f"[InjectionManager] CRITICAL: Write failed! Expected {site_id}, got {saved_val}. Disk issue?")
        else:
            logger.info(f"[InjectionManager] VERIFIED WRITE: {key} updated {old_id} -> {site_id}")

    # --- Helpers ---

    def _calc_next(self, kind: str, current_id: str) -> str:
        if not current_id:
            return ZONES[kind][0]["id"] + ":1"
            
        try:
            zone_id, point_str = current_id.split(":")
            point = int(point_str)
            
            zone_id = zone_id.strip()
            
            zone_list = ZONES[kind]
            # Find current zone index
            idx = -1
            for i, z in enumerate(zone_list):
                if z["id"] == zone_id:
                    idx = i
                    break
            
            if idx == -1: return ZONES[kind][0]["id"] + ":1" # Fallback
            
            current_zone = zone_list[idx]
            
            # Logic: If point < count, increment point. Else next zone.
            # Logic: If point < count, increment point. Else next zone.
            # CRITICAL FIX for Basal: If count is 1 (Basal), we never increment point, just zone.
            # Even if incoming point is somehow < 1 (impossible in valid state), we treat as full.
            if point < current_zone["count"]:
                return f"{zone_id}:{point + 1}"
            else:
                next_idx = (idx + 1) % len(zone_list)
                return f"{zone_list[next_idx]['id']}:1"
                
        except:
            return ZONES[kind][0]["id"] + ":1"

    def _get_site_from_id(self, kind: str, full_id: str) -> Dict[str, Any]:
        """Maps full ID (zone:point) to metadata object."""
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
