import os
import pytest
import asyncio
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.models.draft import NutritionDraft
from app.services.nutrition_draft_service import NutritionDraftService
from app.models.draft_db import NutritionDraftDB

# Using in-memory sqlite for testing DB logic
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture
async def async_session():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    
    await engine.dispose()

@pytest.mark.asyncio
async def test_draft_lifecycle_db(async_session):
    user = "test_user_db"
    
    # 1. Create
    draft, action = await NutritionDraftService.update_draft(user, 10.0, 5.0, 2.0, 1.0, async_session)
    assert action == "created"
    assert draft.carbs == 10.0
    assert draft.fiber == 1.0
    
    # Check DB directly
    from sqlalchemy import select
    stmt = select(NutritionDraftDB).where(NutritionDraftDB.user_id == user)
    row = (await async_session.execute(stmt)).scalars().first()
    assert row is not None
    assert row.carbs == 10.0
    
    # 2. Add Small (Dessert) -> 5g Carbs
    draft, action = await NutritionDraftService.update_draft(user, 5.0, 0, 0, 0, async_session)
    assert action == "updated_add"
    assert draft.carbs == 15.0 # 10+5
    
    # RE-FETCH to ensure persistence
    draft_fetched = await NutritionDraftService.get_draft(user, async_session)
    assert draft_fetched.carbs == 15.0

    # 3. Cumulative Update (Correction of Total) -> 16g
    # 16 is close to 15 (epsilon 2.0). 
    draft, action = await NutritionDraftService.update_draft(user, 16.0, 5.0, 2.0, 1.0, async_session)
    assert action == "updated_replace"
    assert draft.carbs == 16.0
    
    # 4. Big Update (New Meal part?) -> 40g
    # 40 > 20 (small threshold) -> Replace
    draft, action = await NutritionDraftService.update_draft(user, 40.0, 10.0, 10.0, 5.0, async_session)
    assert action == "updated_replace"
    assert draft.carbs == 40.0
    assert draft.fiber == 5.0

    # 5. Close
    t = await NutritionDraftService.close_draft_to_treatment(user, async_session)
    assert t is not None
    assert t.carbs == 40.0
    assert t.fiber == 5.0
    assert t.notes == "Draft confirmed #draft"
    
    # 6. Ensure cleared (status closed)
    d_closed = await NutritionDraftService.get_draft(user, async_session)
    assert d_closed is None # get_draft filters by active

@pytest.mark.asyncio
async def test_draft_expiry_db(async_session):
    user = "u2_db"
    with patch.dict(os.environ, {"NUTRITION_DRAFT_WINDOW_MIN": "1"}):
        draft, _ = await NutritionDraftService.update_draft(user, 10, 0, 0, 0, async_session)
        assert draft is not None
        
        # Manually age it in DB
        from sqlalchemy import update
        stmt = update(NutritionDraftDB).where(NutritionDraftDB.user_id == user).values(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        await async_session.execute(stmt)
        await async_session.commit()
        
        # Fetch should return None
        d2 = await NutritionDraftService.get_draft(user, async_session)
        assert d2 is None

@pytest.mark.asyncio
async def test_discard_db(async_session):
    user = "u3_db"
    await NutritionDraftService.update_draft(user, 10, 0, 0, 0, async_session)
    assert (await NutritionDraftService.get_draft(user, async_session)) is not None
    
    await NutritionDraftService.discard_draft(user, async_session)
    assert (await NutritionDraftService.get_draft(user, async_session)) is None
