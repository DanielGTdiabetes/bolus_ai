
from typing import Any, List, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.security import get_current_user
from app.core.db import get_db_session
from app.models.user_data import FavoriteFood, SupplyItem
from pydantic import BaseModel

router = APIRouter()

# --- Schemas ---
class FavoriteCreate(BaseModel):
    name: str
    carbs: float
    fat: float = 0.0
    protein: float = 0.0
    fiber: float = 0.0
    notes: Optional[str] = None

class FavoriteRead(BaseModel):
    id: str
    name: str
    carbs: float
    fat: float = 0.0
    protein: float = 0.0
    fiber: float = 0.0
    notes: Optional[str] = None
    
    class Config:
        from_attributes = True

    @staticmethod
    def from_orm(obj):
        return FavoriteRead(
            id=str(obj.id), 
            name=obj.name, 
            carbs=obj.carbs,
            fat=obj.fat or 0.0,
            protein=obj.protein or 0.0,
            fiber=obj.fiber or 0.0,
            notes=obj.notes
        )

class SupplyUpdate(BaseModel):
    key: str
    quantity: int

class SupplyRead(BaseModel):
    key: str
    quantity: int

# --- Favorites Endpoints ---

@router.get("/favorites", response_model=List[FavoriteRead])
async def get_favorites(
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    stmt = select(FavoriteFood).where(FavoriteFood.user_id == current_user.username)
    result = await db.execute(stmt)
    return [FavoriteRead.from_orm(f) for f in result.scalars().all()]

@router.post("/favorites", response_model=FavoriteRead)
async def create_favorite(
    fav: FavoriteCreate,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    new_fav = FavoriteFood(
        user_id=current_user.username,
        name=fav.name,
        carbs=fav.carbs,
        fat=fav.fat,
        protein=fav.protein,
        fiber=fav.fiber,
        notes=fav.notes
    )
    db.add(new_fav)
    await db.commit()
    await db.refresh(new_fav)
    return FavoriteRead.from_orm(new_fav)

class FavoriteUpdate(BaseModel):
    name: Optional[str] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    protein: Optional[float] = None
    fiber: Optional[float] = None
    notes: Optional[str] = None

@router.put("/favorites/{fav_id}", response_model=FavoriteRead)
async def update_favorite(
    fav_id: str,
    payload: FavoriteUpdate,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"UPDATE FAVORITE REQUEST: ID={fav_id} User={current_user.username} Payload={payload}")

    stmt = select(FavoriteFood).where(FavoriteFood.id == fav_id)
    result = await db.execute(stmt)
    fav = result.scalar_one_or_none()
    
    if not fav:
        logger.error(f"Favorite {fav_id} NOT FOUND")
        raise HTTPException(status_code=404, detail="Favorite not found")
        
    if fav.user_id != current_user.username:
        logger.error(f"Favorite {fav_id} UNAUTHORIZED for {current_user.username}")
        raise HTTPException(status_code=403, detail="Not authorized")
        
    if payload.name is not None: fav.name = payload.name
    if payload.carbs is not None: fav.carbs = payload.carbs
    if payload.fat is not None: fav.fat = payload.fat
    if payload.protein is not None: fav.protein = payload.protein
    if payload.fiber is not None: fav.fiber = payload.fiber
    if payload.notes is not None: fav.notes = payload.notes
    
    await db.commit()
    await db.refresh(fav)
    logger.info(f"Favorite {fav_id} UPDATED successfully")
    return FavoriteRead.from_orm(fav)

@router.delete("/favorites/{fav_id}")
async def delete_favorite(
    fav_id: str,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    # Check ownership
    stmt = select(FavoriteFood).where(FavoriteFood.id == fav_id)
    result = await db.execute(stmt)
    fav = result.scalar_one_or_none()
    
    if not fav:
        raise HTTPException(status_code=404, detail="Favorite not found")
        
    if fav.user_id != current_user.username:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    await db.execute(delete(FavoriteFood).where(FavoriteFood.id == fav_id))
    await db.commit()
    return {"status": "success"}

# --- Supplies Endpoints ---

@router.get("/supplies", response_model=List[SupplyRead])
async def get_supplies(
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    stmt = select(SupplyItem).where(SupplyItem.user_id == current_user.username)
    result = await db.execute(stmt)
    items = result.scalars().all()
    # Normalize keys? Frontend expects 'supplies_needles' etc.
    return [SupplyRead(key=item.item_key, quantity=item.quantity) for item in items]

@router.post("/supplies")
async def update_supply(
    payload: SupplyUpdate,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    # Upsert
    stmt = pg_insert(SupplyItem).values(
        user_id=current_user.username,
        item_key=payload.key,
        quantity=payload.quantity
    ).on_conflict_do_update(
        index_elements=["user_id", "item_key"], 
        set_=dict(quantity=payload.quantity)
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "success", "key": payload.key, "quantity": payload.quantity}
