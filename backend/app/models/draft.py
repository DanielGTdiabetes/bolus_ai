from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field

class NutritionDraft(BaseModel):
    id: str
    user_id: str
    carbs: float = 0.0
    fat: float = 0.0
    protein: float = 0.0
    fiber: float = 0.0
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    
    status: str = "active" # active, closed, discarded
    last_hash: Optional[str] = None
    
    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def total_macros(self):
        return f"C:{self.carbs:.1f} F:{self.fat:.1f} P:{self.protein:.1f} Fib:{self.fiber:.1f}"
