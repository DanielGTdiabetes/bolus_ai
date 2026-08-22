from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all metadata
from app.bot import service
from app.bot.service import _imported_meal_review_card
from app.core.db import Base
from app.models.imported_meal import ImportedMeal
from app.services.nutrition_notification_outbox import DeliveryResult


def meal(**overrides):
    values = {
        "id": "11111111-1111-1111-1111-111111111111",
        "meal_type": "lunch",
        "last_seen_at": datetime(2026, 8, 22, 13, 32, tzinfo=timezone.utc),
        "foods": [
            {"name": "Pan proteínas", "quantity": "2", "unit": "rebanadas", "carbs_g": 4},
            {"name": "Yogur", "quantity": "1", "unit": "unidad", "carbs_g": 15},
            {"name": "Ensalada", "quantity": "250", "unit": "g", "carbs_g": 8},
        ],
        "source_carbs": 27.0,
        "calculated_carbs": 27.0,
        "validation_error": None,
        "status": "NEW",
        "pending_source_version": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def button_labels(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_review_card_lists_foods_and_does_not_calculate_before_confirmation():
    text, markup = _imported_meal_review_card(meal())

    assert "Pan proteínas" in text
    assert "Yogur" in text
    assert "TOTAL: 27 g HC" in text
    assert "U" not in text
    assert button_labels(markup) == ["✅ Confirmar", "✏️ Editar", "🔄 Actualizar MFP", "🗑 Descartar"]


def test_invalid_review_explains_source_food_mismatch_and_has_no_confirm_button():
    text, markup = _imported_meal_review_card(
        meal(source_carbs=62.0, calculated_carbs=27.0, validation_error="carb_total_mismatch", status="INVALID")
    )

    assert "MyFitnessPal indica: 62 g HC" in text
    assert "Suma de alimentos: 27 g HC" in text
    assert "Diferencia: 35 g HC" in text
    assert "No se calculará ningún bolo" in text
    assert "✅ Confirmar" not in button_labels(markup)


def test_treated_update_shows_only_change_and_prior_bolus_context():
    text, _ = _imported_meal_review_card(meal(
        calculated_carbs=38.0,
        source_carbs=38.0,
        previous_calculated_carbs=27.0,
        status="UPDATED_TREATED",
        last_bolus_units=3.0,
        last_bolus_at=datetime.now(timezone.utc),
    ))

    assert "Anterior: 27 g HC" in text
    assert "Ahora: 38 g HC" in text
    assert "Cambio: +11 g HC" in text
    assert "Bolo previo: 3 U" in text
    assert "solo se evaluará la diferencia pendiente" in text


class DummyQuery:
    def __init__(self, meal_id: str):
        self.data = f"im_confirm|{meal_id}"
        self.from_user = SimpleNamespace(id=1)
        self.message = SimpleNamespace(message_id=77, text="review")

    async def answer(self, *_args, **_kwargs):
        return None


@pytest.fixture
async def callback_meal_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        imported = ImportedMeal(
            user_id="admin",
            source="MyFitnessPal-Hermes",
            source_reference="hermes-mfp:2026-08-22:breakfast",
            meal_date=date(2026, 8, 22),
            meal_type="breakfast",
            foods=[{"name": "Pan", "carbs_g": 27}],
            source_carbs=27,
            calculated_carbs=27,
            fat=3,
            protein=8,
            fiber=2,
            fingerprint="a" * 64,
            stable_read_count=2,
            is_stable=True,
            status="NEW",
        )
        session.add(imported)
        await session.commit()
        meal_id = imported.id
    monkeypatch.setattr(service, "SessionLocal", factory)
    yield factory, meal_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_uses_imported_slot_and_only_persists_after_delivery(
    callback_meal_db, monkeypatch: pytest.MonkeyPatch
):
    factory, meal_id = callback_meal_db
    edits = []
    captured = {}

    async def fake_edit(_query, text, **kwargs):
        edits.append((text, kwargs.get("reply_markup")))

    async def fake_calculate(*_args, **kwargs):
        captured.update(kwargs)
        async with factory() as session:
            pending = await session.get(ImportedMeal, meal_id)
            assert pending.status == "NEW"
            assert pending.confirmed_at is None
        return DeliveryResult(status="sent")

    monkeypatch.setattr(service, "edit_message_text_safe", fake_edit)
    monkeypatch.setattr(service, "on_new_meal_received", fake_calculate)

    await service.handle_callback(
        SimpleNamespace(callback_query=DummyQuery(meal_id)),
        SimpleNamespace(user_data={}, bot=object()),
    )

    async with factory() as session:
        confirmed = await session.get(ImportedMeal, meal_id)
        assert confirmed.status == "CONFIRMED"
        assert confirmed.confirmed_at is not None
    assert captured["meal_slot"] == "breakfast"
    assert edits[0][0].startswith("✅ Comida confirmada")


@pytest.mark.asyncio
async def test_failed_calculation_keeps_meal_reviewable_with_retry_button(
    callback_meal_db, monkeypatch: pytest.MonkeyPatch
):
    factory, meal_id = callback_meal_db
    edits = []

    async def fake_edit(_query, text, **kwargs):
        edits.append((text, kwargs.get("reply_markup")))

    async def fake_calculate(*_args, **_kwargs):
        return DeliveryResult(status="failed", error="calculator unavailable")

    monkeypatch.setattr(service, "edit_message_text_safe", fake_edit)
    monkeypatch.setattr(service, "on_new_meal_received", fake_calculate)

    await service.handle_callback(
        SimpleNamespace(callback_query=DummyQuery(meal_id)),
        SimpleNamespace(user_data={}, bot=object()),
    )

    async with factory() as session:
        pending = await session.get(ImportedMeal, meal_id)
        assert pending.status == "NEW"
        assert pending.confirmed_at is None
    retry_text, retry_markup = edits[-1]
    assert "Puedes reintentarlo" in retry_text
    assert "✅ Confirmar" in button_labels(retry_markup)
