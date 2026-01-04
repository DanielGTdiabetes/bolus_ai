
from typing import Dict, Any, List
from app.services.store import DataStore
from dataclasses import dataclass

@dataclass
class InjectionSite:
    id: str
    name: str
    emoji: str
    image_ref: str = None # Placeholder for static asset filename

SITES_RAPID = [
    # Abdomen Right (Der)
    InjectionSite("abd_r_top", "Abd. Der - Arriba", "🟣👉", "body_abdomen.png"),
    InjectionSite("abd_r_mid", "Abd. Der - Medio", "🟣👉", "body_abdomen.png"),
    InjectionSite("abd_r_bot", "Abd. Der - Bajo", "🟣👉", "body_abdomen.png"),
    
    # Abdomen Left (Izq)
    InjectionSite("abd_l_top", "Abd. Izq - Arriba", "👈🟣", "body_abdomen.png"),
    InjectionSite("abd_l_mid", "Abd. Izq - Medio", "👈🟣", "body_abdomen.png"),
    InjectionSite("abd_l_bot", "Abd. Izq - Bajo", "👈🟣", "body_abdomen.png"),
]

SITES_BASAL = [
    # Thighs (Muslos)
    InjectionSite("leg_right", "Muslo Der", "🦵👉", "body_legs.png"),
    InjectionSite("leg_left", "Muslo Izq", "👈🦵", "body_legs.png"),
    
    # Glutes
    InjectionSite("glute_right", "Glúteo Der", "🍑👉", "body_legs.png"),
    InjectionSite("glute_left", "Glúteo Izq", "👈🍑", "body_legs.png"),
]

class RotationService:
    def __init__(self, store: DataStore):
        self.store = store
        self.filename = "injection_rotation.json"

    def _get_list(self, plan: str) -> List[InjectionSite]:
        return SITES_BASAL if plan == "basal" else SITES_RAPID

    def get_current_state(self, username: str, plan: str = "rapid") -> Dict[str, Any]:
        # file structure: { username: { "rapid": {last_index: 0}, "basal": {last_index: 0} } }
        all_states = self.store.read_json(self.filename, {})
        user_state = all_states.get(username, {})
        # Migrating old structure if needed (simple check)
        if "last_index" in user_state:
             # Convert old flat structure to nested
             user_state = {"rapid": user_state, "basal": {"last_index": -1}}
             
        return user_state.get(plan, {"last_index": -1})

    def rotate_site(self, username: str, plan: str = "rapid") -> InjectionSite:
        all_states = self.store.read_json(self.filename, {})
        user_root = all_states.get(username, {})
        
        # Structure migration check
        if "last_index" in user_root:
            user_root = {"rapid": user_root, "basal": {"last_index": -1}}
            
        plan_state = user_root.get(plan, {"last_index": -1})
        site_list = self._get_list(plan)
        
        current_index = plan_state.get("last_index", -1)
        next_index = (current_index + 1) % len(site_list)
        
        # Update state
        plan_state["last_index"] = next_index
        user_root[plan] = plan_state
        all_states[username] = user_root
        
        self.store.write_json(self.filename, all_states)
        
        return site_list[next_index]

    def get_next_site_preview(self, username: str, plan: str = "rapid") -> InjectionSite:
        """Peak at next site without rotating."""
        state = self.get_current_state(username, plan)
        site_list = self._get_list(plan)
        
        idx = state.get("last_index", -1)
        next_idx = (idx + 1) % len(site_list)
        return site_list[next_idx]
