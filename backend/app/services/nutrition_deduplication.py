from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nutrition_event_identity import NutritionEventIdentity
from app.models.treatment import Treatment

logger = logging.getLogger(__name__)

LEGACY_WINDOW = timedelta(minutes=15)
CROSS_SOURCE_WINDOW = timedelta(minutes=20)
HERMES_RECENT_WINDOW = timedelta(hours=3)
CARB_TOLERANCE_G = 1.0
MACRO_TOLERANCE_G = 1.0

def normalize_source(value: Optional[str]) -> str:
    normalized = _normalize_text(value or "unknown")
    if "hermes" in normalized:
        return "hermes"
    if normalized in {"myfitnesspal", "health connect", "healthconnect", "healthkit"}:
        return "health_connect"
    if "auto export" in normalized or "webhook" in normalized:
        return "health_connect"
    return normalized.replace(" ", "_")[:32] or "unknown"


def source_from_treatment(row: Treatment) -> str:
    notes = row.notes or ""
    if "hermes-mfp:" in notes.lower() or "hermes" in notes.lower():
        return "hermes"
    return normalize_source(row.entered_by or notes)


def external_identity_key(user_id: str, source: str, external_id: str) -> str:
    canonical = f"nutrition-id-v1|{user_id}|{normalize_source(source)}|{external_id.strip()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def masked_key(value: Optional[str]) -> str:
    if not value:
        return "none"
    return f"{value[:10]}..."


def normalize_foods(values: Optional[Iterable[str]]) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(sorted({_normalize_text(value) for value in values if _normalize_text(value)}))


def food_fingerprint(foods: tuple[str, ...]) -> Optional[str]:
    if not foods:
        return None
    return hashlib.sha256("|".join(foods).encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()


def _known(value: Optional[float]) -> bool:
    return value is not None and float(value) > 0


def macros_equivalent(
    row: Treatment,
    *,
    carbs: float,
    fat: Optional[float],
    protein: Optional[float],
    fiber: Optional[float],
) -> bool:
    if abs(float(row.carbs or 0) - carbs) > CARB_TOLERANCE_G:
        return False
    for current, incoming in ((row.fat, fat), (row.protein, protein), (row.fiber, fiber)):
        if _known(current) and _known(incoming) and abs(float(current) - float(incoming)) > MACRO_TOLERANCE_G:
            return False
    return True


def _dialect_name(session: AsyncSession) -> str:
    sync_session = getattr(session, "_sync", None)
    bind = getattr(sync_session, "bind", None) or getattr(session, "bind", None)
    dialect = getattr(bind, "dialect", None)
    return getattr(dialect, "name", "unknown")


def _in_transaction(session: AsyncSession) -> bool:
    sync_session = getattr(session, "_sync", None)
    target = sync_session or session
    checker = getattr(target, "in_transaction", None)
    return bool(checker()) if checker else False


async def acquire_nutrition_transaction_lock(session: AsyncSession, user_id: str) -> None:
    """Serialize fuzzy check + insert until the current transaction commits."""

    dialect = _dialect_name(session)
    if dialect == "postgresql":
        lock_value = int.from_bytes(hashlib.sha256(f"nutrition|{user_id}".encode()).digest()[:8], "big", signed=True)
        await session.execute(text(f"SELECT pg_advisory_xact_lock({lock_value})"))
    elif dialect == "sqlite" and not _in_transaction(session):
        await session.execute(text("BEGIN IMMEDIATE"))


async def treatment_for_external_identity(
    session: AsyncSession,
    *,
    user_id: str,
    source: str,
    external_id: Optional[str],
) -> tuple[Optional[Treatment], Optional[str]]:
    if not external_id:
        return None, None
    identity_key = external_identity_key(user_id, source, external_id)
    identity = await session.get(NutritionEventIdentity, identity_key)
    if identity is None:
        return None, identity_key
    return await session.get(Treatment, identity.treatment_id), identity_key


async def has_nutrition_identity(session: AsyncSession, treatment_id: str) -> bool:
    identity = (
        await session.execute(
            select(NutritionEventIdentity.identity_key)
            .where(NutritionEventIdentity.treatment_id == treatment_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return identity is not None


async def claim_external_identity(
    session: AsyncSession,
    *,
    treatment_id: str,
    user_id: str,
    source: str,
    external_id: Optional[str],
    strategy: str,
    foods: tuple[str, ...] = (),
) -> Optional[str]:
    if not external_id:
        return None
    identity_key = external_identity_key(user_id, source, external_id)
    existing = await session.get(NutritionEventIdentity, identity_key)
    if existing is None:
        session.add(
            NutritionEventIdentity(
                identity_key=identity_key,
                treatment_id=treatment_id,
                user_id=user_id,
                source=normalize_source(source),
                external_id_hash=hashlib.sha256(external_id.strip().encode()).hexdigest(),
                food_fingerprint=food_fingerprint(foods),
                match_strategy=strategy,
            )
        )
    return identity_key


async def find_semantic_duplicate(
    session: AsyncSession,
    *,
    user_id: str,
    source: str,
    event_at: datetime,
    received_at: datetime,
    carbs: float,
    fat: Optional[float],
    protein: Optional[float],
    fiber: Optional[float],
    foods: tuple[str, ...] = (),
) -> tuple[Optional[Treatment], Optional[str]]:
    incoming_source = normalize_source(source)
    incoming_food_fingerprint = food_fingerprint(foods)
    windows = [(event_at - CROSS_SOURCE_WINDOW, event_at + CROSS_SOURCE_WINDOW, "semantic_time_macros")]
    if incoming_source == "health_connect":
        windows.append((received_at - HERMES_RECENT_WINDOW, received_at + timedelta(minutes=5), "hermes_recent_macros"))

    for start, end, strategy in windows:
        rows = (
            await session.execute(
                select(Treatment).where(
                    Treatment.user_id == user_id,
                    Treatment.created_at >= start.replace(tzinfo=None),
                    Treatment.created_at <= end.replace(tzinfo=None),
                    Treatment.carbs >= carbs - CARB_TOLERANCE_G,
                    Treatment.carbs <= carbs + CARB_TOLERANCE_G,
                )
            )
        ).scalars().all()
        logger.info(
            "nutrition_dedup_candidates strategy=%s source=%s count=%s",
            strategy,
            incoming_source,
            len(rows),
        )
        for row in rows:
            existing_source = source_from_treatment(row)
            if incoming_source == existing_source and incoming_source != "unknown":
                continue
            if strategy == "hermes_recent_macros" and existing_source != "hermes":
                continue
            if row.entered_by != "webhook-integration" and existing_source != "hermes":
                continue
            if incoming_food_fingerprint:
                stored_food_fingerprints = set(
                    (
                        await session.execute(
                            select(NutritionEventIdentity.food_fingerprint).where(
                                NutritionEventIdentity.treatment_id == row.id,
                                NutritionEventIdentity.food_fingerprint.is_not(None),
                            )
                        )
                    ).scalars().all()
                )
                if stored_food_fingerprints and incoming_food_fingerprint not in stored_food_fingerprints:
                    continue
            if macros_equivalent(row, carbs=carbs, fat=fat, protein=protein, fiber=fiber):
                return row, strategy
    return None, None
