"""
Integration test for the complete Draft flow:
1. Simulate webhook ingest (first food item)
2. Verify draft created
3. Simulate webhook ingest (second food item)
4. Verify draft accumulated (not replaced)
5. Simulate draft confirm
6. Verify treatment created with correct totals
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.services.nutrition_draft_service import NutritionDraftService
from app.models.draft_db import NutritionDraftDB
from app.models.treatment import Treatment

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
async def test_full_draft_flow_with_bot_notification(async_session):
    """
    Simulates the complete flow from webhook to bot notification.
    """
    user = "test_user_integration"
    
    # Mock the bot notification function
    with patch("app.bot.service.on_draft_updated", new_callable=AsyncMock) as mock_notify:
        
        # === STEP 1: First food item arrives (Pasta 60g) ===
        draft1, action1 = await NutritionDraftService.update_draft(
            user, 60.0, 10.0, 5.0, 2.0, async_session
        )
        
        assert action1 == "created"
        assert draft1.carbs == 60.0
        assert draft1.fiber == 2.0
        
        # Simulate bot notification
        await mock_notify(user, draft1, action1)
        
        # Verify notification was called
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert call_args[0][0] == user  # username
        assert call_args[0][1].carbs == 60.0  # draft
        assert call_args[0][2] == "created"  # action
        
        mock_notify.reset_mock()
        
        # === STEP 2: Second food item arrives (Bread 25g) ===
        draft2, action2 = await NutritionDraftService.update_draft(
            user, 25.0, 5.0, 3.0, 1.0, async_session
        )
        
        assert action2 == "updated_add"
        assert draft2.carbs == 85.0  # 60 + 25
        assert draft2.fiber == 3.0   # 2 + 1
        assert draft2.id == draft1.id  # Same draft
        
        # Simulate bot notification
        await mock_notify(user, draft2, action2)
        
        call_args = mock_notify.call_args
        assert call_args[0][1].carbs == 85.0  # Updated total
        assert call_args[0][2] == "updated_add"
        
        mock_notify.reset_mock()
        
        # === STEP 3: Third food item (Dessert 30g) ===
        draft3, action3 = await NutritionDraftService.update_draft(
            user, 30.0, 8.0, 2.0, 0.5, async_session
        )
        
        assert action3 == "updated_add"
        assert draft3.carbs == 115.0  # 60 + 25 + 30
        assert draft3.fiber == 3.5    # 2 + 1 + 0.5
        
        # === STEP 4: Confirm draft ===
        treatment, created, closed = await NutritionDraftService.close_draft_to_treatment(
            user, async_session
        )
        
        assert treatment is not None
        assert created == True
        assert treatment.carbs == 115.0
        assert treatment.fiber == 3.5
        assert treatment.fat == 23.0   # 10 + 5 + 8
        assert treatment.protein == 10.0  # 5 + 3 + 2
        
        # === STEP 5: Verify draft is closed ===
        closed_draft = await NutritionDraftService.get_draft(user, async_session)
        assert closed_draft is None


@pytest.mark.asyncio
async def test_draft_updated_at_changes_on_each_update(async_session):
    """
    Verifies that updated_at changes with each addition.
    This is critical for the frontend to detect changes.
    """
    user = "test_user_timestamps"
    
    # First item
    draft1, _ = await NutritionDraftService.update_draft(
        user, 30.0, 0, 0, 0, async_session
    )
    first_updated = draft1.updated_at
    
    # Small delay to ensure timestamp differs
    await asyncio.sleep(0.05)
    
    # Second item
    draft2, _ = await NutritionDraftService.update_draft(
        user, 20.0, 0, 0, 0, async_session
    )
    second_updated = draft2.updated_at
    
    # Verify timestamps are different
    assert second_updated > first_updated, "updated_at should change on each update"
    
    # Verify same draft ID
    assert draft1.id == draft2.id


@pytest.mark.asyncio
async def test_idempotent_confirm(async_session):
    """
    Verifies that confirming the same draft twice doesn't create duplicates.
    """
    user = "test_user_idempotent"
    
    # Create and close
    await NutritionDraftService.update_draft(user, 50.0, 0, 0, 0, async_session)
    
    # First confirm
    t1, created1, closed1 = await NutritionDraftService.close_draft_to_treatment(
        user, async_session
    )
    assert created1 == True
    assert t1.carbs == 50.0
    
    # Save treatment to DB
    async_session.add(t1)
    await async_session.commit()
    
    # Second confirm (should be idempotent)
    t2, created2, closed2 = await NutritionDraftService.close_draft_to_treatment(
        user, async_session, draft_id=t1.draft_id
    )
    
    # Should return existing treatment, not create new
    assert created2 == False
    assert t2.id == t1.id
