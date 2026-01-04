
from typing import Dict, Any, List, Optional
from app.services.store import DataStore
from dataclasses import dataclass
from app.services.injection_sites import InjectionManager

@dataclass
class InjectionSite:
    id: str
    name: str
    emoji: str
    image_ref: str = None

class RotationService:
    """
    Wrapper around InjectionManager to provide Bot-specific structures 
    while maintaining synchronization with the Web App.
    """
    def __init__(self, store: DataStore):
        self.mgr = InjectionManager(store)

    def rotate_site(self, username: str, plan: str = "rapid") -> InjectionSite:
        # Note: We ignore username for now as InjectionManager is global-repo based
        # but the synchronization is achieved by using the same file.
        kind = "basal" if plan == "basal" else "bolus"
        site_dict = self.mgr.rotate_site(kind)
        return self._to_injection_site(site_dict)

    def get_next_site_preview(self, username: str, plan: str = "rapid") -> InjectionSite:
        kind = "basal" if plan == "basal" else "bolus"
        site_dict = self.mgr.get_next_site(kind)
        return self._to_injection_site(site_dict)

    def get_last_site_preview(self, username: str, plan: str = "rapid") -> Optional[InjectionSite]:
        kind = "basal" if plan == "basal" else "bolus"
        site_dict = self.mgr.get_last_site(kind)
        if not site_dict: return None
        return self._to_injection_site(site_dict)

    def _to_injection_site(self, d: Dict[str, Any]) -> InjectionSite:
        return InjectionSite(
            id=d["id"],
            name=d["name"],
            emoji=d["emoji"],
            image_ref=d["image"]
        )
