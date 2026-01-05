from pathlib import Path
from typing import List, Dict, Any, Optional
from app.services.store import DataStore

# --- ZONES CONFIG (Matches Frontend) ---
# Added: emoji, image for Bot support
ZONES = {
    "bolus": [
        {"id": "abd_l_top", "label": "Abd. Izq - Arriba", "count": 3, "emoji": "👈🟣", "image": "body_abdomen.png"},
        {"id": "abd_l_mid", "label": "Abd. Izq - Medio", "count": 3, "emoji": "👈🟣", "image": "body_abdomen.png"},
        {"id": "abd_l_bot", "label": "Abd. Izq - Bajo", "count": 3, "emoji": "👈🟣", "image": "body_abdomen.png"},
        {"id": "abd_r_top", "label": "Abd. Der - Arriba", "count": 3, "emoji": "🟣👉", "image": "body_abdomen.png"},
        {"id": "abd_r_mid", "label": "Abd. Der - Medio", "count": 3, "emoji": "🟣👉", "image": "body_abdomen.png"},
        {"id": "abd_r_bot", "label": "Abd. Der - Bajo", "count": 3, "emoji": "🟣👉", "image": "body_abdomen.png"},
    ],
    "basal": [
        {"id": "leg_left", "label": "Muslo Izq", "count": 1, "emoji": "👈🦵", "image": "body_legs.png"},
        {"id": "leg_right", "label": "Muslo Der", "count": 1, "emoji": "🦵👉", "image": "body_legs.png"},
        {"id": "glute_left", "label": "Glúteo Izq", "count": 1, "emoji": "👈🍑", "image": "body_legs.png"},
        {"id": "glute_right", "label": "Glúteo Der", "count": 1, "emoji": "🍑👉", "image": "body_legs.png"}
    ]
}


class InjectionManager:
    def __init__(self, store: DataStore):
        self.store = store
        self.filename = "injection_state.json"
        
    def _load_state(self) -> Dict[str, Any]:
        default_state = {
            "bolus": { "last_used_id": "abd_l_top:1" },
            "basal": { "last_used_id": "glute_right:1" }
        }
        # LOGGING PROOF: Log the exact path being read
        import logging
        try:
            full_path = self.store._path(self.filename)
            logging.getLogger(__name__).info(f"InjectionManager loading state from: {full_path}")
        except:
            pass
            
        return self.store.read_json(self.filename, default_state)

    def _save_state(self, state: Dict[str, Any]):
        self.store.write_json(self.filename, state)

    def get_next_site(self, kind: str = "bolus") -> Dict[str, Any]:
        """Returns NEXT site object."""
        state = self._load_state()
        key = "basal" if kind.lower() == "basal" else "bolus"
        last_id = state.get(key, {}).get("last_used_id")
        
        # Calculate Next
        next_id = self._calc_next(key, last_id)
        return self._get_site_from_id(key, next_id)

    def get_last_site(self, kind: str = "bolus") -> Optional[Dict[str, Any]]:
        """Returns LAST site object."""
        state = self._load_state()
        key = "basal" if kind.lower() == "basal" else "bolus"
        last_id = state.get(key, {}).get("last_used_id")
        if not last_id: return None
        return self._get_site_from_id(key, last_id)
        
    def rotate_site(self, kind: str = "bolus") -> Dict[str, Any]:
        """Advances rotation and returns new site object."""
        state = self._load_state()
        key = "basal" if kind.lower() == "basal" else "bolus"
        last_id = state.get(key, {}).get("last_used_id")
        
        next_id = self._calc_next(key, last_id)
        
        # Save
        if key not in state: state[key] = {}
        state[key]["last_used_id"] = next_id
        self._save_state(state)
        
        return self._get_site_from_id(key, next_id)


    def set_current_site(self, kind: str, site_id: str):
        """Manual set from Frontend. Ensures Format zone_id:point."""
        state = self._load_state()
        key = "basal" if kind.lower() == "basal" else "bolus"
        
        # Validation: If site_id comes without point (e.g. "abd_l_top"), append :1
        if ":" not in site_id:
             site_id = f"{site_id}:1"
             
        if key not in state: state[key] = {}
        state[key]["last_used_id"] = site_id
        self._save_state(state)

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
                label = f"{label} (Punto {point_str})"
                
            return {
                "id": full_id,
                "name": label,
                "emoji": zone.get("emoji", "📍"),
                "image": zone.get("image", "body_full.png")
            }
        except:
            return {"id": full_id, "name": full_id, "emoji": "📍", "image": "body_full.png"}

