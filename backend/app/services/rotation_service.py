
from typing import Dict, Any, List
from app.services.store import DataStore
from dataclasses import dataclass

@dataclass
class InjectionSite:
    id: str
    name: str
    emoji: str
    image_ref: str = None # Placeholder for static asset filename

SITES = [
    InjectionSite("abdomen_right", "Abdomen (Derecha)", "🟣👉", "body_abdomen.png"),
    InjectionSite("abdomen_left", "Abdomen (Izquierda)", "👈🟣", "body_abdomen.png"),
    InjectionSite("thigh_right", "Muslo (Derecha)", "🦵👉", "body_legs.png"),
    InjectionSite("thigh_left", "Muslo (Izquierda)", "👈🦵", "body_legs.png"),
    InjectionSite("arm_right", "Brazo (Derecha)", "💪👉", "body_full.png"),
    InjectionSite("arm_left", "Brazo (Izquierda)", "👈💪", "body_full.png"),
    InjectionSite("buttocks_right", "Glúteo (Derecha)", "🍑👉", "body_full.png"),
    InjectionSite("buttocks_left", "Glúteo (Izquierda)", "👈🍑", "body_full.png"),
]

class RotationService:
    def __init__(self, store: DataStore):
        self.store = store
        self.filename = "injection_rotation.json"

    def get_current_state(self, username: str) -> Dict[str, Any]:
        # file structure: { username: { "last_index": 0, "last_updated": "..." } }
        all_states = self.store.read_json(self.filename, {})
        return all_states.get(username, {"last_index": -1})

    def rotate_site(self, username: str) -> InjectionSite:
        all_states = self.store.read_json(self.filename, {})
        user_state = all_states.get(username, {"last_index": -1})
        
        current_index = user_state.get("last_index", -1)
        next_index = (current_index + 1) % len(SITES)
        
        # Update state
        user_state["last_index"] = next_index
        all_states[username] = user_state
        self.store.write_json(self.filename, all_states)
        
        return SITES[next_index]

    def get_next_site_preview(self, username: str) -> InjectionSite:
        """Peak at next site without rotating."""
        state = self.get_current_state(username)
        idx = state.get("last_index", -1)
        next_idx = (idx + 1) % len(SITES)
        return SITES[next_idx]
