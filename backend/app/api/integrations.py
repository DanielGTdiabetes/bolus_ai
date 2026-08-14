import hashlib
import hmac
import logging
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.user_settings_resolver import resolve_bot_user_settings
from app.core import config
from app.core.db import get_db_session
from app.core.security import TokenManager, get_token_manager, get_current_user, CurrentUser
from app.core.settings import Settings, get_settings
from app.models.settings import UserSettings, UserSettingsDB
from app.models.glucose_reading import GlucoseReadingDB
from app.models.basal import BasalEntry
from app.models.treatment import Treatment
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient, NightscoutError
from app.services.nightscout_secrets_service import get_ns_config
from app.services.glucose_ingest_service import (
    GlucoseIngestData,
    epoch_to_utc,
    ingest_glucose_reading,
)
from app.services.nutrition_shadow_matcher import (
    NutritionShadowEvent,
    classify_nutrition_candidate,
    extract_import_fingerprint,
    parse_nutrition_shadow_mode,
)
from app.services.nutrition_notification_outbox import (
    enqueue_meal_notification,
    notification_status_for_events,
)
from app.services.meal_coverage_service import (
    calculate_incremental_nutrition,
    nutrition_revision,
    upsert_current_meal,
)

router = APIRouter()
logger = logging.getLogger(__name__)
DEXCOM_BOLUS_EVENT_TYPES = ("Meal Bolus", "Correction Bolus", "Bolus")
DEXCOM_CARBS_DEDUPE_WINDOW_MS = 45 * 60 * 1000

def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    from pathlib import Path
    return DataStore(Path(settings.data.data_dir))


def _extract_value(payload: Dict[str, Any], keys: List[str]) -> Optional[float]:
    for key in keys:
        current = payload
        parts = key.split(".")
        try:
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    current = None
                    break
            if current is None:
                continue
            if isinstance(current, (int, float, str)):
                return float(current)
        except Exception:
            continue
    return None


def normalize_nutrition_payload(payload: Dict[str, Any]) -> Dict[str, Optional[float]]:
    carbs = _extract_value(payload, [
        "carbs", "dietary_carbohydrates", "total_carbs", "Carbohydrates",
        "carbohydrates_total_g", "nutrition.carbs", "nutrients.carbs"
    ])
    fat = _extract_value(payload, [
        "fat", "dietary_fat", "total_fat", "fat_total_g",
        "nutrition.fat", "nutrients.fat"
    ])
    protein = _extract_value(payload, [
        "protein", "dietary_protein", "total_protein", "protein_total_g",
        "nutrition.protein", "nutrients.protein"
    ])
    fiber = _extract_value(payload, [
        "fiber", "fiber_total_g", "fiber_alt", "dietary_fiber", "total_fiber",
        "fibra", "t_fiber", "nutrients.fiber", "nutrition.fiber"
    ])
    timestamp = payload.get("date") or payload.get("timestamp") or payload.get("created_at")
    return {
        "carbs": carbs,
        "fat": fat,
        "protein": protein,
        "fiber": fiber,
        "timestamp": timestamp
    }


def should_update_fiber(existing_fiber: Optional[float], new_fiber: Optional[float], tolerance: float = 0.1) -> bool:
    if new_fiber is None:
        return False
    base = existing_fiber or 0.0
    return abs(base - new_fiber) >= tolerance


def is_valid_ingestion(carbs: float, fat: float, protein: float, fiber: float) -> bool:
    total_grams = (carbs or 0.0) + (fat or 0.0) + (protein or 0.0) + (fiber or 0.0)
    return total_grams > 0.0


def _numeric_meal_type(value: Any) -> Optional[int]:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _filter_mfp_health_connect_daily_dump(parsed_meals: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if len(parsed_meals) <= 1:
        return parsed_meals

    meals = list(parsed_meals.values())
    if not all((meal.get("source") or "").lower() == "myfitnesspal" for meal in meals):
        return parsed_meals
    if not all(meal.get("fingerprint") for meal in meals):
        return parsed_meals

    meal_types = [_numeric_meal_type(meal.get("meal_type")) for meal in meals]
    if any(meal_type is None for meal_type in meal_types):
        return parsed_meals

    timestamps = {meal.get("ts") for meal in meals}
    if len(timestamps) != 1:
        return parsed_meals

    max_meal_type = max(meal_type for meal_type in meal_types if meal_type is not None)
    return {
        key: meal
        for key, meal in parsed_meals.items()
        if _numeric_meal_type(meal.get("meal_type")) == max_meal_type
    }


def _resolve_import_source(notes: Optional[str]) -> str:
    if not notes:
        return "Auto Export"
    normalized = notes.lower()
    if "myfitnesspal" in normalized:
        return "MyFitnessPal"
    if "healthkit" in normalized:
        return "HealthKit"
    if "auto export" in normalized or "autoexport" in normalized:
        return "Auto Export"
    if "health auto export" in normalized or "imported from health" in normalized:
        return "Auto Export"
    return "Auto Export"

# Modelo flexible para Health Auto Export o n8n
class NutritionPayload(BaseModel):
    # Campos comunes en exportaciones de salud
    carbs: Optional[float] = Field(default=0, alias="dietary_carbohydrates")
    fat: Optional[float] = Field(default=0, alias="dietary_fat")
    protein: Optional[float] = Field(default=0, alias="dietary_protein")
    
    # Soporte para nombres alternativos (n8n o MFP directo)
    carbs_alt: Optional[float] = Field(default=None, alias="carbohydrates_total_g")
    fat_alt: Optional[float] = Field(default=None, alias="fat_total_g")
    protein_alt: Optional[float] = Field(default=None, alias="protein_total_g")
    fiber_alt: Optional[float] = Field(default=None, alias="fiber_total_g")
    
    # Common simple names
    fiber: Optional[float] = Field(default=0, alias="dietary_fiber")

    food_name: Optional[str] = Field(default=None, alias="name")
    calories: Optional[float] = Field(default=0, alias="active_energy_burned") # A veces viene aquí o en dietary_energy
    
    timestamp: Optional[str] = Field(default=None, alias="date") # ISO format preferred
    
    # Generic bucket
    metrics: Optional[List[Dict[str, Any]]] = None # Health Auto Export suele mandar una lista de métricas

class MobileBolusSettingsResponse(BaseModel):
    schema_version: int = 1
    user_id: str
    config_hash: str
    updated_at: Optional[str] = None
    targets: Dict[str, Optional[float]]
    cr: Dict[str, float]
    cf: Dict[str, float]
    iob: Dict[str, Any]
    calculator: Dict[str, Any]
    round_step_u: float
    max_bolus_u: float
    max_correction_u: float


class MobileBolusEventResponse(BaseModel):
    id: str
    event_kind: str
    insulin_type: Optional[str] = None
    insulin_units: Optional[float] = None
    carbs_grams: Optional[int] = None
    glucose_mgdl: Optional[int] = None
    timestamp: int


class MobileGlucoseEntryRequest(BaseModel):
    glucose_mgdl: int = Field(ge=1, le=400)
    timestamp: int = Field(gt=0, description="Epoch seconds from Dexcom")
    trend_arrow: str = Field(default="NONE", max_length=64)
    sensor_type: str = Field(default="G7", max_length=32)
    source_package: str = Field(default="com.dexcom.g7", max_length=128)


class WatchGlucoseEntryV1Request(BaseModel):
    """Exact WtachSugar -> Bolus AI continuity contract."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: StrictInt = Field(alias="schemaVersion")
    reading_id: str = Field(alias="readingId", min_length=1, max_length=160)
    origin_installation_id: str = Field(
        alias="originInstallationId", min_length=1, max_length=160
    )
    outbox_sequence: StrictInt = Field(alias="outboxSequence", gt=0)
    glucose_mgdl: StrictInt = Field(alias="glucoseMgDl", ge=1, le=400)
    measured_at_epoch_millis: StrictInt = Field(alias="measuredAtEpochMillis", gt=0)
    received_at_watch_epoch_millis: StrictInt = Field(
        alias="receivedAtWatchEpochMillis", gt=0
    )
    received_at_phone_epoch_millis: StrictInt = Field(
        alias="receivedAtPhoneEpochMillis", gt=0
    )
    trend_rate_mgdl_per_minute: Optional[float] = Field(
        alias="trendRateMgDlPerMinute", ge=-20, le=20
    )
    trend_arrow: str = Field(alias="trendArrow", max_length=64)
    sensor_state: StrictInt = Field(alias="sensorState", ge=0, le=255)
    display_only: StrictBool = Field(alias="displayOnly")
    sensor_sequence: StrictInt = Field(alias="sensorSequence", ge=0, le=65535)
    session_id: str = Field(alias="sessionId", min_length=1, max_length=160)
    historical: StrictBool
    timestamp_uncertain: StrictBool = Field(alias="timestampUncertain")
    source: Literal["g7_direct_watch"]
    decision_eligible: StrictBool = Field(alias="decisionEligible")

    @field_validator("schema_version")
    @classmethod
    def require_schema_v1(cls, value: int) -> int:
        if value != 1:
            raise ValueError("schemaVersion must be exactly 1")
        return value

    @field_validator("decision_eligible")
    @classmethod
    def require_continuity_only(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("decisionEligible must be exactly false")
        return value

    @field_validator("sensor_state")
    @classmethod
    def require_usable_sensor_state(cls, value: int) -> int:
        if value != 0x06:
            raise ValueError("sensorState must be the usable G7 state 0x06")
        return value

    @field_validator("display_only")
    @classmethod
    def reject_display_only(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("displayOnly must be exactly false")
        return value


class MobileGlucoseEntryResponse(BaseModel):
    status: str
    glucose_mgdl: int
    timestamp_ms: int
    direction: str
    reading_uid: Optional[str] = None
    local_status: str = "not_stored"
    nightscout_status: str = "unknown"


class WatchGlucoseEntryV1Response(BaseModel):
    status: str
    readingId: str
    source: Literal["g7_direct_watch"]
    decisionEligible: Literal[False]
    duplicate: bool
    validationReason: Optional[str] = None


class MobileGlucoseEntryV2Request(BaseModel):
    schema_version: int = Field(default=2, ge=2, le=10)
    reading_uid: Optional[str] = Field(default=None, max_length=160)
    glucose_mgdl: int = Field(ge=1, le=400)
    timestamp: int = Field(gt=0, description="Epoch seconds or milliseconds from the sensor")
    received_at: Optional[int] = Field(default=None, gt=0)
    trend_arrow: str = Field(default="NONE", max_length=64)
    trend_rate: Optional[float] = Field(default=None, ge=-20, le=20)
    sensor_state: Optional[str] = Field(default=None, max_length=64)
    display_only: bool = False
    historical: bool = False
    timestamp_uncertain: bool = False
    sensor_session_id: Optional[str] = Field(default=None, max_length=160)
    sequence: Optional[int] = Field(default=None, ge=0)
    sensor_type: str = Field(default="G7", max_length=32)
    source_package: Optional[str] = Field(default=None, max_length=128)
    source: Literal["dexcom_android", "g7_direct_watch"]


class MobileGlucoseEntryV2Response(BaseModel):
    status: str
    reading_uid: str
    glucose_mgdl: int
    timestamp_ms: int
    source: str
    validation_reason: Optional[str] = None
    usable_for_dosing: bool
    historical: bool
    sync_status: str
    duplicate: bool = False


class MobileGlucoseBatchRequest(BaseModel):
    readings: List[MobileGlucoseEntryV2Request] = Field(min_length=1, max_length=100)


class MobileGlucoseBatchResponse(BaseModel):
    status: str
    accepted: int
    rejected: int
    duplicates: int
    readings: List[MobileGlucoseEntryV2Response]


def _utc_timestamp_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return int(value.timestamp() * 1000)


def _round_carbs_grams(value: float) -> int:
    return int(Decimal(str(max(0.0, value))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_glucose_mgdl(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    if not math.isfinite(float(value)):
        return None
    rounded = int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return rounded if 1 <= rounded <= 400 else None


def _treatment_glucose_mgdl(row: Treatment) -> Optional[int]:
    stored_glucose = _round_glucose_mgdl(getattr(row, "glucose", None))
    if stored_glucose is not None:
        return stored_glucose

    trace = getattr(row, "calculation_trace", None)
    if not isinstance(trace, dict):
        return None

    context = trace.get("context")
    snapshot = trace.get("snapshot")
    trace_glucose = context.get("bg") if isinstance(context, dict) else None
    if trace_glucose is None and isinstance(snapshot, dict):
        glucose = snapshot.get("glucose")
        if isinstance(glucose, dict):
            trace_glucose = glucose.get("mgdl")
    return _round_glucose_mgdl(trace_glucose)


def _dexcom_events_from_treatment(row: Treatment) -> List[MobileBolusEventResponse]:
    timestamp = _utc_timestamp_ms(row.created_at)
    glucose_mgdl = _treatment_glucose_mgdl(row)
    events: List[MobileBolusEventResponse] = []
    if float(row.insulin or 0.0) > 0 and row.event_type in DEXCOM_BOLUS_EVENT_TYPES:
        events.append(
            MobileBolusEventResponse(
                id=f"treatment:{row.id}:rapid",
                event_kind="INSULIN",
                insulin_type="FAST_ACTING",
                insulin_units=float(row.insulin),
                glucose_mgdl=glucose_mgdl,
                timestamp=timestamp,
            )
        )
    carbs_grams = _round_carbs_grams(float(row.carbs or 0.0))
    if carbs_grams > 0 and not _is_pending_imported_meal(row):
        events.append(
            MobileBolusEventResponse(
                id=f"treatment:{row.id}:carbs",
                event_kind="CARBS",
                carbs_grams=carbs_grams,
                glucose_mgdl=glucose_mgdl,
                timestamp=timestamp,
            )
        )
    return events


def _is_pending_imported_meal(row: Treatment) -> bool:
    notes = (getattr(row, "notes", None) or "").lower()
    entered_by = (getattr(row, "entered_by", None) or "").lower()
    return (
        float(row.insulin or 0.0) <= 0.0
        and entered_by == "webhook-integration"
        and "#imported" in notes
    )


def _dexcom_event_from_basal(row: BasalEntry) -> Optional[MobileBolusEventResponse]:
    if float(row.dose_u or 0.0) <= 0:
        return None
    return MobileBolusEventResponse(
        id=f"basal:{row.id}:long",
        event_kind="INSULIN",
        insulin_type="LONG_ACTING",
        insulin_units=float(row.dose_u),
        timestamp=_utc_timestamp_ms(row.created_at),
    )


def _authorize_ingest_key(request: Request, ingest_key_header: Optional[str]) -> None:
    provided_key = ingest_key_header or request.query_params.get("key")
    ingest_secret = os.getenv("NUTRITION_INGEST_SECRET") or os.getenv("NUTRITION_INGEST_KEY")
    if ingest_secret and provided_key == ingest_secret:
        return
    raise HTTPException(status_code=401, detail="Authentication required")


def _authorize_cgm_ingest_key(request: Request, ingest_key_header: Optional[str]) -> None:
    provided_key = ingest_key_header or request.query_params.get("key")
    cgm_secret = os.getenv("CGM_INGEST_KEY")
    cgm_secret_sha256 = os.getenv("CGM_INGEST_KEY_SHA256", "").strip().lower()
    legacy_secret = os.getenv("NUTRITION_INGEST_SECRET") or os.getenv("NUTRITION_INGEST_KEY")
    if provided_key:
        provided_key_bytes = provided_key.encode("utf-8")
        if any(
            hmac.compare_digest(provided_key_bytes, secret.encode("utf-8"))
            for secret in (cgm_secret, legacy_secret)
            if secret
        ):
            return
        if len(cgm_secret_sha256) == 64:
            provided_digest = hashlib.sha256(provided_key_bytes).hexdigest()
            if hmac.compare_digest(provided_digest, cgm_secret_sha256):
                return
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_https_cgm_ingest(request: Request) -> None:
    if os.getenv("ALLOW_INSECURE_CGM_INGEST", "").strip().lower() in {"1", "true", "yes"}:
        return
    headers = getattr(request, "headers", {})
    forwarded_proto = str(headers.get("x-forwarded-proto", "")).split(",", 1)[0].strip().lower()
    request_url = getattr(request, "url", None)
    scheme = str(getattr(request_url, "scheme", "")).lower()
    if scheme == "https" or forwarded_proto == "https":
        return
    raise HTTPException(status_code=403, detail="HTTPS required for glucose ingest")


DEXCOM_TO_NIGHTSCOUT_TREND = {
    "DOUBLEUP": "DoubleUp",
    "DOUBLE_UP": "DoubleUp",
    "SINGLEUP": "SingleUp",
    "SINGLE_UP": "SingleUp",
    "FORTYFIVEUP": "FortyFiveUp",
    "FORTY_FIVE_UP": "FortyFiveUp",
    "SLIGHTUP": "FortyFiveUp",
    "RISING_SLOWLY": "FortyFiveUp",
    "RISING": "SingleUp",
    "RISING_QUICKLY": "DoubleUp",
    "FLAT": "Flat",
    "STEADY": "Flat",
    "FORTYFIVEDOWN": "FortyFiveDown",
    "FORTY_FIVE_DOWN": "FortyFiveDown",
    "SLIGHTDOWN": "FortyFiveDown",
    "FALLING_SLOWLY": "FortyFiveDown",
    "FALLING": "SingleDown",
    "FALLING_QUICKLY": "DoubleDown",
    "SINGLEDOWN": "SingleDown",
    "SINGLE_DOWN": "SingleDown",
    "DOUBLEDOWN": "DoubleDown",
    "DOUBLE_DOWN": "DoubleDown",
    "NOTCOMPUTABLE": "NOT COMPUTABLE",
    "NOT_COMPUTABLE": "NOT COMPUTABLE",
    "RATEOUTOFRANGE": "RATE OUT OF RANGE",
    "RATE_OUT_OF_RANGE": "RATE OUT OF RANGE",
    "NONE": "NONE",
}


def _nightscout_direction(trend_arrow: str) -> str:
    normalized = (trend_arrow or "NONE").strip().upper().replace("-", "_").replace(" ", "_")
    return DEXCOM_TO_NIGHTSCOUT_TREND.get(normalized, "NONE")


async def _mobile_nightscout_client(
    session: AsyncSession,
    settings: Settings,
) -> NightscoutClient:
    user_settings, user_id, _ = await _load_mobile_bolus_settings(session)
    stored = await get_ns_config(session, user_id)
    if stored and stored.enabled and stored.url and stored.api_secret:
        return NightscoutClient(
            stored.url,
            stored.api_secret,
            timeout_seconds=settings.nightscout.timeout_seconds,
        )

    if user_settings.nightscout.enabled and user_settings.nightscout.url and user_settings.nightscout.token:
        return NightscoutClient(
            user_settings.nightscout.url,
            user_settings.nightscout.token,
            timeout_seconds=settings.nightscout.timeout_seconds,
        )

    if settings.nightscout.base_url and (settings.nightscout.api_secret or settings.nightscout.token):
        return NightscoutClient(
            str(settings.nightscout.base_url),
            settings.nightscout.token,
            api_secret=settings.nightscout.api_secret,
            timeout_seconds=settings.nightscout.timeout_seconds,
        )

    raise HTTPException(status_code=503, detail="Nightscout is not configured")


async def _load_mobile_bolus_settings(session: AsyncSession) -> tuple[UserSettings, str, Optional[datetime]]:
    preferred = [config.get_bot_default_username() or "admin", "admin"]
    seen = set()

    for user_id in preferred:
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        row = (await session.execute(select(UserSettingsDB).where(UserSettingsDB.user_id == user_id))).scalars().first()
        if row and row.settings:
            return UserSettings.migrate(dict(row.settings)), row.user_id, row.updated_at

    rows = (await session.execute(select(UserSettingsDB))).scalars().all()
    rows = sorted(rows, key=lambda row: (row.updated_at.timestamp() if row.updated_at else 0), reverse=True)
    for row in rows:
        if row.settings:
            return UserSettings.migrate(dict(row.settings)), row.user_id, row.updated_at

    return UserSettings.default(), "default", None


def _mobile_bolus_settings_response(
    settings_obj: UserSettings,
    user_id: str,
    updated_at: Optional[datetime],
) -> MobileBolusSettingsResponse:
    return MobileBolusSettingsResponse(
        user_id=user_id,
        config_hash=settings_obj.config_hash,
        updated_at=updated_at.isoformat() if updated_at else None,
        targets=settings_obj.targets.model_dump(),
        cr=settings_obj.cr.model_dump(),
        cf=settings_obj.cf.model_dump(),
        iob=settings_obj.iob.model_dump(),
        calculator=settings_obj.calculator.model_dump(),
        round_step_u=settings_obj.round_step_u,
        max_bolus_u=settings_obj.max_bolus_u,
        max_correction_u=settings_obj.max_correction_u,
    )


@router.get("/mobile/bolus-settings", response_model=MobileBolusSettingsResponse)
async def mobile_bolus_settings(
    request: Request,
    ingest_key_header: Optional[str] = Header(None, alias="X-Ingest-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    _authorize_ingest_key(request, ingest_key_header)
    settings_obj, user_id, updated_at = await _load_mobile_bolus_settings(session)
    return _mobile_bolus_settings_response(settings_obj, user_id, updated_at)


@router.get("/mobile/bolus-events", response_model=List[MobileBolusEventResponse])
async def mobile_bolus_events(
    request: Request,
    after_id: Optional[str] = Query(None),
    after_timestamp: Optional[int] = Query(None, ge=0),
    latest_only: bool = Query(False),
    ingest_key_header: Optional[str] = Header(None, alias="X-Ingest-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Return rapid insulin, long-acting insulin and carbohydrate events for Android."""
    _authorize_ingest_key(request, ingest_key_header)
    _, user_id, _ = await _load_mobile_bolus_settings(session)

    after_created_at: Optional[datetime] = None
    cursor_id = after_id
    if after_id:
        parts = after_id.split(":")
        source = parts[0] if len(parts) >= 2 else "treatment"
        source_id = parts[1] if len(parts) >= 2 else after_id
        if len(parts) < 2:
            cursor_id = f"treatment:{after_id}:rapid"
        if source == "basal":
            try:
                source_id = uuid.UUID(source_id)
            except (TypeError, ValueError):
                source_id = None
            previous = None if source_id is None else (
                await session.execute(
                    select(BasalEntry).where(BasalEntry.id == source_id, BasalEntry.user_id == user_id)
                )
            ).scalars().first()
        else:
            previous = (
                await session.execute(
                    select(Treatment).where(Treatment.id == source_id, Treatment.user_id == user_id)
                )
            ).scalars().first()
        if previous:
            after_created_at = previous.created_at

    if after_id and after_created_at is None and not after_timestamp:
        return []

    treatment_stmt = select(Treatment).where(
        Treatment.user_id == user_id,
        (
            ((Treatment.insulin > 0) & Treatment.event_type.in_(DEXCOM_BOLUS_EVENT_TYPES))
            | (Treatment.carbs > 0)
        ),
    )
    basal_stmt = select(BasalEntry).where(
        BasalEntry.user_id == user_id,
        BasalEntry.dose_u > 0,
    )

    if after_created_at is None and after_timestamp:
        after_created_at = (
            datetime.fromtimestamp(after_timestamp / 1000, tz=timezone.utc)
            .replace(tzinfo=None)
            + timedelta(milliseconds=1)
        )

    if after_created_at is None:
        threshold = datetime.utcnow() - timedelta(minutes=2)
        treatment_stmt = treatment_stmt.where(Treatment.created_at >= threshold)
        basal_stmt = basal_stmt.where(BasalEntry.created_at >= threshold)
    else:
        treatment_stmt = treatment_stmt.where(Treatment.created_at >= after_created_at)
        basal_stmt = basal_stmt.where(BasalEntry.created_at >= after_created_at)

    treatment_rows = (
        await session.execute(treatment_stmt.order_by(Treatment.created_at.asc(), Treatment.id.asc()).limit(50))
    ).scalars().all()
    basal_rows = (
        await session.execute(basal_stmt.order_by(BasalEntry.created_at.asc(), BasalEntry.id.asc()).limit(50))
    ).scalars().all()

    events = [
        event
        for row in treatment_rows
        for event in _dexcom_events_from_treatment(row)
    ]
    events.extend(
        event
        for row in basal_rows
        if (event := _dexcom_event_from_basal(row)) is not None
    )
    events.sort(key=lambda event: (event.timestamp, event.id))
    events = _dedupe_dexcom_carbs_events(events)
    if after_created_at is not None and cursor_id:
        cursor_timestamp = _utc_timestamp_ms(after_created_at)
        events = [
            event for event in events
            if event.timestamp > cursor_timestamp
            or (event.timestamp == cursor_timestamp and event.id > cursor_id)
        ]
    if latest_only:
        return events[-1:] if events else []
    return events[:50]


def _dedupe_dexcom_carbs_events(events: List[MobileBolusEventResponse]) -> List[MobileBolusEventResponse]:
    deduped: List[MobileBolusEventResponse] = []
    recent_carbs: List[MobileBolusEventResponse] = []
    for event in events:
        if event.event_kind != "CARBS" or not event.carbs_grams:
            deduped.append(event)
            continue

        is_duplicate = any(
            previous.carbs_grams == event.carbs_grams
            and abs(event.timestamp - previous.timestamp) <= DEXCOM_CARBS_DEDUPE_WINDOW_MS
            for previous in recent_carbs
        )
        if is_duplicate:
            continue

        recent_carbs.append(event)
        recent_carbs = [
            previous
            for previous in recent_carbs
            if event.timestamp - previous.timestamp <= DEXCOM_CARBS_DEDUPE_WINDOW_MS
        ]
        deduped.append(event)
    return deduped


@router.post(
    "/mobile/glucose-entry",
    response_model=Union[MobileGlucoseEntryResponse, WatchGlucoseEntryV1Response],
)
async def mobile_glucose_entry(
    payload: Union[MobileGlucoseEntryRequest, WatchGlucoseEntryV1Request],
    request: Request,
    ingest_key_header: Optional[str] = Header(None, alias="X-Ingest-Key"),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    """Receive a protected Dexcom G7 broadcast forwarded by the Android app."""
    _authorize_cgm_ingest_key(request, ingest_key_header)
    if isinstance(payload, WatchGlucoseEntryV1Request):
        _require_https_cgm_ingest(request)
        _, user_id, _ = await _load_mobile_bolus_settings(session)
        try:
            result = await ingest_glucose_reading(
                session,
                user_id,
                GlucoseIngestData(
                    schema_version=payload.schema_version,
                    reading_uid=payload.reading_id,
                    glucose_mgdl=payload.glucose_mgdl,
                    measured_at=epoch_to_utc(payload.measured_at_epoch_millis),
                    received_at=datetime.now(timezone.utc),
                    received_at_watch=epoch_to_utc(payload.received_at_watch_epoch_millis),
                    received_at_phone=epoch_to_utc(payload.received_at_phone_epoch_millis),
                    source=payload.source,
                    trend_arrow=_nightscout_direction(payload.trend_arrow),
                    trend_rate=payload.trend_rate_mgdl_per_minute,
                    sensor_state=f"0x{payload.sensor_state:02X}",
                    display_only=payload.display_only,
                    historical=payload.historical,
                    timestamp_uncertain=payload.timestamp_uncertain,
                    sensor_session_id=payload.session_id,
                    sequence=payload.sensor_sequence,
                    outbox_sequence=payload.outbox_sequence,
                    sensor_type="G7",
                    source_package="org.wtachtsugar",
                    origin_installation_id=payload.origin_installation_id,
                    decision_eligible=False,
                ),
                # Continuity-only watch readings must not re-enter the primary
                # path indirectly through Nightscout.
                sync_to_nightscout=False,
            )
            await session.commit()
        except IntegrityError:
            # A concurrent retry can pass the pre-insert lookup. The database
            # constraints remain authoritative and the loser becomes a 409.
            await session.rollback()
            existing = (
                await session.execute(
                    select(GlucoseReadingDB).where(
                        GlucoseReadingDB.user_id == user_id,
                        GlucoseReadingDB.source == payload.source,
                        (
                            (GlucoseReadingDB.reading_uid == payload.reading_id)
                            | (
                                (GlucoseReadingDB.origin_installation_id == payload.origin_installation_id)
                                & (GlucoseReadingDB.sensor_session_id == payload.session_id)
                                & (GlucoseReadingDB.sequence == payload.sensor_sequence)
                            )
                        ),
                    )
                )
            ).scalars().first()
            if existing is None:
                raise
            return JSONResponse(
                status_code=409,
                content={
                    "status": "duplicate",
                    "readingId": existing.reading_uid,
                    "source": existing.source,
                    "decisionEligible": False,
                    "duplicate": True,
                    "validationReason": existing.validation_reason,
                },
            )
        response_body = {
            "status": result.status,
            "readingId": result.reading.reading_uid,
            "source": result.reading.source,
            "decisionEligible": False,
            "duplicate": result.duplicate,
            "validationReason": result.reading.validation_reason,
        }
        if result.duplicate:
            return JSONResponse(status_code=409, content=response_body)
        if result.status == "rejected":
            return JSONResponse(status_code=422, content=response_body)
        return JSONResponse(status_code=201, content=response_body)

    if payload.source_package != "com.dexcom.g7" or payload.sensor_type.upper() != "G7":
        raise HTTPException(status_code=422, detail="Unsupported glucose source")

    now_seconds = int(datetime.now(timezone.utc).timestamp())
    if payload.timestamp > now_seconds + 5 * 60:
        raise HTTPException(status_code=422, detail="Glucose timestamp is in the future")
    if payload.timestamp < now_seconds - 7 * 24 * 60 * 60:
        raise HTTPException(status_code=422, detail="Glucose timestamp is older than 7 days")

    timestamp_ms = payload.timestamp * 1000
    direction = _nightscout_direction(payload.trend_arrow)
    stored = None
    if hasattr(session, "execute"):
        _, user_id, _ = await _load_mobile_bolus_settings(session)
        stored = await ingest_glucose_reading(
            session,
            user_id,
            GlucoseIngestData(
                glucose_mgdl=payload.glucose_mgdl,
                measured_at=epoch_to_utc(payload.timestamp),
                source="dexcom_android",
                trend_arrow=direction,
                sensor_type=payload.sensor_type,
                source_package=payload.source_package,
            ),
        )
        await session.commit()

    nightscout_status = "pending"
    client = None
    try:
        client = await _mobile_nightscout_client(session, settings)
        result = await client.upload_sgv(
            glucose_mgdl=payload.glucose_mgdl,
            timestamp_ms=timestamp_ms,
            direction=direction,
        )
        nightscout_status = str(result.get("status") or "uploaded")
    except NightscoutError as exc:
        logger.warning("Dexcom glucose upload to Nightscout failed: %s", exc)
        nightscout_status = "pending"
    except HTTPException as exc:
        # The local copy is authoritative for continuity. Missing Nightscout
        # configuration must not make the mobile sender discard the reading.
        logger.warning("Dexcom glucose stored locally; Nightscout unavailable: %s", exc.detail)
        nightscout_status = "pending"
    except Exception as exc:
        # Persistence already succeeded. A transient or unexpected remote error
        # must never make the companion discard its local queue item.
        logger.warning(
            "Dexcom glucose stored locally; Nightscout upload failed: %s",
            type(exc).__name__,
        )
        nightscout_status = "pending"
    finally:
        if client:
            await client.aclose()

    if stored and stored.reading:
        if nightscout_status in {"uploaded", "duplicate"}:
            stored.reading.sync_status = "duplicate" if nightscout_status == "duplicate" else "synced"
            stored.reading.synced_at = datetime.now(timezone.utc)
            stored.reading.sync_error = None
        else:
            stored.reading.sync_status = "pending"
        await session.commit()

    return MobileGlucoseEntryResponse(
        status=nightscout_status if nightscout_status != "pending" else "stored",
        glucose_mgdl=payload.glucose_mgdl,
        timestamp_ms=timestamp_ms,
        direction=direction,
        reading_uid=stored.reading.reading_uid if stored else None,
        local_status=stored.status if stored else "legacy_forwarded",
        nightscout_status=nightscout_status,
    )


def _v2_response(result) -> MobileGlucoseEntryV2Response:
    row = result.reading
    measured_at = row.measured_at
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone.utc)
    return MobileGlucoseEntryV2Response(
        status=result.status,
        reading_uid=row.reading_uid,
        glucose_mgdl=row.glucose_mgdl,
        timestamp_ms=int(measured_at.timestamp() * 1000),
        source=row.source,
        validation_reason=row.validation_reason,
        usable_for_dosing=row.usable_for_dosing,
        historical=row.historical,
        sync_status=row.sync_status,
        duplicate=result.duplicate,
    )


async def _ingest_v2_payload(
    payload: MobileGlucoseEntryV2Request,
    session: AsyncSession,
    user_id: str,
    *,
    flush: bool = True,
    sync_to_nightscout: bool = True,
):
    if payload.source == "dexcom_android" and payload.source_package not in {None, "com.dexcom.g7"}:
        raise HTTPException(status_code=422, detail="Unsupported Android glucose source")
    if payload.sensor_type.upper() != "G7":
        raise HTTPException(status_code=422, detail="Unsupported glucose sensor")

    is_watch_continuity = payload.source == "g7_direct_watch"
    return await ingest_glucose_reading(
        session,
        user_id,
        GlucoseIngestData(
            schema_version=payload.schema_version,
            reading_uid=payload.reading_uid,
            glucose_mgdl=payload.glucose_mgdl,
            measured_at=epoch_to_utc(payload.timestamp),
            received_at=epoch_to_utc(payload.received_at) if payload.received_at else None,
            source=payload.source,
            trend_arrow=_nightscout_direction(payload.trend_arrow),
            trend_rate=payload.trend_rate,
            sensor_state=payload.sensor_state,
            display_only=payload.display_only,
            historical=payload.historical,
            timestamp_uncertain=payload.timestamp_uncertain,
            sensor_session_id=payload.sensor_session_id,
            sequence=payload.sequence,
            sensor_type=payload.sensor_type,
            source_package=payload.source_package,
            decision_eligible=not is_watch_continuity,
        ),
        sync_to_nightscout=sync_to_nightscout and not is_watch_continuity,
        flush=flush,
    )


@router.post("/mobile/glucose-entry/v2", response_model=MobileGlucoseEntryV2Response)
async def mobile_glucose_entry_v2(
    payload: MobileGlucoseEntryV2Request,
    request: Request,
    ingest_key_header: Optional[str] = Header(None, alias="X-Ingest-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Store a versioned Android or direct-watch reading before external sync."""
    _authorize_cgm_ingest_key(request, ingest_key_header)
    user_settings, user_id, _ = await _load_mobile_bolus_settings(session)
    result = await _ingest_v2_payload(
        payload,
        session,
        user_id,
        sync_to_nightscout=user_settings.glucose_sources.sync_direct_to_nightscout,
    )
    await session.commit()
    return _v2_response(result)


@router.post("/mobile/glucose-entries/batch", response_model=MobileGlucoseBatchResponse)
async def mobile_glucose_entries_batch(
    payload: MobileGlucoseBatchRequest,
    request: Request,
    ingest_key_header: Optional[str] = Header(None, alias="X-Ingest-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Persist ordered mobile/watch backfill without creating retrospective actions."""
    _authorize_cgm_ingest_key(request, ingest_key_header)
    user_settings, user_id, _ = await _load_mobile_bolus_settings(session)
    results = []
    for item in sorted(payload.readings, key=lambda reading: reading.timestamp):
        # Batch delivery is always historical unless the newest item is still
        # genuinely fresh; validation in the ingest service remains decisive.
        results.append(
            await _ingest_v2_payload(
                item,
                session,
                user_id,
                sync_to_nightscout=user_settings.glucose_sources.sync_direct_to_nightscout,
            )
        )
    await session.commit()

    responses = [_v2_response(result) for result in results]
    return MobileGlucoseBatchResponse(
        status="stored",
        accepted=sum(1 for result in results if result.status == "accepted"),
        rejected=sum(1 for result in results if result.status == "rejected"),
        duplicates=sum(1 for result in results if result.duplicate),
        readings=responses,
    )


@router.post("/nutrition", summary="Webhook for Health Auto Export / External Nutrition")
async def ingest_nutrition(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    ingest_key_header: Optional[str] = Header(None, alias="X-Ingest-Key"),
    sync_id_header: Annotated[Optional[str], Header(alias="X-Sync-Id")] = None,
    session: AsyncSession = Depends(get_db_session),
    token_manager: TokenManager = Depends(get_token_manager),
    settings: Settings = Depends(get_settings),
):
    """
    Recibe datos de nutrición externos (Health Auto Export, n8n, Shortcuts).
    Crea un tratamiento con insulin=0 (Orphan) para que el frontend lo detecte.
    Es "silencioso": si falla, no rompe nada, solo loguea error.
    """
    # Payload Safety Check (2MB Limit) - Added for Audit Remediation
    body_bytes = await request.body()
    if len(body_bytes) > 2 * 1024 * 1024:
        logger.warning(f"Payload too large: {len(body_bytes)} bytes")
        raise HTTPException(status_code=413, detail="Payload too large (>2MB)")

    # Initialize DataStore locally or via dependency if preferred, here we use settings for path
    
    # 0. EMERGENCY MODE CHECK
    if settings.emergency_mode:
        logger.warning("⛔ Nutrition Ingest REJECTED due to Emergency Mode.")
        return {"success": 0, "message": "Ignored: System in Emergency Mode"}

    from pathlib import Path
    from app.services.store import DataStore
    ds = DataStore(Path(settings.data.data_dir))
    
    # 0. DEBUG LOGGING
    supplied_sync_id = payload.get("sync_id") if isinstance(payload, dict) else None
    sync_id = str(sync_id_header or supplied_sync_id or uuid.uuid4())
    ingest_id = sync_id
    log_entry = {
        "id": ingest_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "headers": {
            "user_agent": request.headers.get("user-agent"),
            "content_type": request.headers.get("content-type"),
            "x_ingest_key": "REDACTED" if ingest_key_header else None
        },
        "status": "pending",
        "result": None
    }
    
    # Helper to append log safely
    def append_log(entry):
        try:
            logs = ds.read_json("ingest_logs.json", [])
            # Keep last 50
            logs.insert(0, entry)
            if len(logs) > 50:
                logs = logs[:50]
            ds.write_json("ingest_logs.json", logs)
        except Exception as e:
            logger.error(f"Failed to write ingest log: {e}")

    try:

        auth_error = HTTPException(
            status_code=401,
            detail={"success": 0, "error": "Authentication required for nutrition ingest"},
        )

        username: Optional[str] = None
        bearer_value = authorization or ""
        bearer_token = None

        if bearer_value.lower().startswith("bearer "):
            bearer_token = bearer_value.split(" ", 1)[1].strip()

        if bearer_token:
            try:
                payload_token = token_manager.decode_token(bearer_token, expected_type="access")
                subject = payload_token.get("sub")
                username = str(subject) if subject is not None else None
            except HTTPException:
                raise auth_error
        else:
            query_params = request.query_params
            provided_key = ingest_key_header or (query_params.get("key") if hasattr(query_params, "get") else None)
            ingest_secret = os.getenv("NUTRITION_INGEST_SECRET") or os.getenv("NUTRITION_INGEST_KEY")

            if ingest_secret and provided_key == ingest_secret:
                source = "header" if ingest_key_header else "query"
                logger.info("nutrition_ingest authorized via key (%s)", source)
            else:
                reason = "missing secret" if not ingest_secret else "invalid key"
                logger.warning("Nutrition ingest rejected via key (%s)", reason)
                log_entry["status"] = "error"
                log_entry["result"] = {"error": "Authentication failed", "reason": reason}
                append_log(log_entry)
                raise auth_error

        if not username:
            # Align webhook user with bot/default user resolution so the app sees the meal
            username = config.get_bot_default_username() or None

        if not username:
            try:
                # Reuse the bot resolver to pick the active user (prefers non-default settings)
                _, resolved_user = await resolve_bot_user_settings()
                username = resolved_user
            except Exception as resolver_exc:
                logger.warning(f"Nutrition ingest: failed to resolve user, falling back to admin: {resolver_exc}")
                username = None

        if not username:
            username = "admin"

        raw_payload = payload
        is_wrapper_payload = isinstance(payload, dict) and isinstance(payload.get("payload"), dict)
        real_payload = (
            payload.get("payload")
            if is_wrapper_payload
            else payload
        )
        source_payload = real_payload if isinstance(real_payload, dict) else raw_payload
        source = source_payload.get("source") or source_payload.get("provider") or source_payload.get("app") or source_payload.get("origin") or "unknown"
        norm_log = normalize_nutrition_payload(source_payload)
        logger.info(
            "nutrition_ingest_start ingest_id=%s user_id=%s source=%s carbs=%s fat=%s protein=%s fiber=%s timestamp=%s",
            ingest_id,
            username,
            source,
            norm_log.get("carbs"),
            norm_log.get("fat"),
            norm_log.get("protein"),
            norm_log.get("fiber"),
            norm_log.get("timestamp"),
        )
        logger.info(
            "nutrition_ingest_payload ingest_id=%s wrapper=%s",
            ingest_id,
            "wrapper" if is_wrapper_payload else "direct",
        )

        # 1. Normalización de Datos (Health Auto Export manda una lista "data": [...])
        # Buscamos carbs, fat, protein en el payload bruto
        
        # 1. Complex Parser for Health Auto Export (Aggregated Metrics)
        # Structure: { "data": { "metrics": [ { "name": "total_fat", "data": [ {date, qty}, ... ] }, ... ] } }
        
        parsed_meals = {} # Key: timestamp string -> {c: 0, f: 0, p: 0, dt: datetime}
        
        metrics_list = []
        # Locate the metrics array deeply nested or flat
        if "data" in real_payload and isinstance(real_payload["data"], dict) and "metrics" in real_payload["data"]:
             metrics_list = real_payload["data"]["metrics"]
        elif "data" in real_payload and isinstance(real_payload["data"], list):
             # Sometimes it's a list of export objects?
             if len(real_payload["data"]) > 0 and "metrics" in real_payload["data"][0]:
                 metrics_list = real_payload["data"][0].get("metrics", [])
                 # Or weird structure in user example: [ { data: { metrics: [...] } } ]
                 if not metrics_list and "data" in real_payload["data"][0]:
                      metrics_list = real_payload["data"][0]["data"].get("metrics", [])
        elif "metrics" in real_payload:
             metrics_list = real_payload["metrics"]

        
        if metrics_list:
            logger.info("nutrition_ingest_metrics ingest_id=%s metric_groups=%s", ingest_id, len(metrics_list))
            for metric in metrics_list:
                # Normalize name: lower case AND replace spaces with underscores (e.g. "Dietary Fiber" -> "dietary_fiber")
                m_name = metric.get("name", "").lower().replace(" ", "_")
                m_data = metric.get("data", [])
                
                metric_type = None
                if m_name in ["carbohydrates", "dietary_carbohydrates", "total_carbs", "hkquantitytypeidentifierdietarycarbohydrates"]: metric_type = "c"
                elif m_name in ["total_fat", "dietary_fat", "fat", "hkquantitytypeidentifierdietaryfattotal"]: metric_type = "f"
                elif m_name in ["protein", "dietary_protein", "total_protein", "hkquantitytypeidentifierdietaryprotein"]: metric_type = "p"
                elif m_name in ["fiber", "dietary_fiber", "total_fiber", "hkquantitytypeidentifierdietaryfiber", "fibra", "fibra_dietetica", "fibra_total"]: metric_type = "fib"
                
                if metric_type and isinstance(m_data, list):
                    for entry in m_data:
                        # entry: {date: "2025-...", qty: "..."}
                        raw_date = entry.get("date")
                        entry_source = entry.get("source")
                        entry_fingerprint = entry.get("meal_fingerprint") or entry.get("fingerprint") or entry.get("origin_id")
                        entry_meal_type = entry.get("meal_type")
                        
                        # Fix Qty logic:
                        # Sometimes qty is string "36.6", sometimes number 36.6
                        raw_qty_val = entry.get("qty", 0)
                        try:
                            raw_qty = float(raw_qty_val)
                        except:
                            raw_qty = 0.0
                        
                        # Normalize date key (strip seconds/timezone to group near-simultaneous entries?)
                        # HealthKit data for same meal usually shares EXACT timestamp down to second
                        if raw_date:
                            meal_key = entry_fingerprint or f"{raw_date}|{entry_meal_type or ''}"
                            if meal_key not in parsed_meals:
                                parsed_meals[meal_key] = {
                                    "c": 0.0,
                                    "f": 0.0,
                                    "p": 0.0,
                                    "fib": 0.0,
                                    "ts": raw_date,
                                    "source": entry_source,
                                    "fingerprint": entry_fingerprint,
                                    "meal_type": entry_meal_type,
                                    "fiber_provided": False,
                                }
                            elif entry_source and not parsed_meals[meal_key].get("source"):
                                parsed_meals[meal_key]["source"] = entry_source
                            elif entry_fingerprint and not parsed_meals[meal_key].get("fingerprint"):
                                parsed_meals[meal_key]["fingerprint"] = entry_fingerprint
                            elif entry_meal_type and not parsed_meals[meal_key].get("meal_type"):
                                parsed_meals[meal_key]["meal_type"] = entry_meal_type
                            
                            # Add to existing (in case multiple entries for same type/time? unlikely but safe)
                            # Actually, usually unique per type per time.
                            parsed_meals[meal_key][metric_type] += raw_qty
                            if metric_type == "fib":
                                parsed_meals[meal_key]["fiber_provided"] = True
        
        else:
             # Support for "Type", "Value" flat format (Shortcuts/Raw Export)
             if "Type" in real_payload and "Value" in real_payload:
                 p_type = real_payload.get("Type", "")
                 p_val = real_payload.get("Value", 0)
                 p_date = real_payload.get("Date") or real_payload.get("StartDate")
                 
                 # Map Type
                 metric_type = None
                 if p_type in ["DietaryFiber", "Fiber", "DietaryFiber"]: metric_type = "fib"
                 elif p_type in ["DietaryCarbohydrates", "Carbohydrates", "Carbs"]: metric_type = "c"
                 elif p_type in ["DietaryFatTotal", "Fat", "DietaryFat"]: metric_type = "f"
                 elif p_type in ["DietaryProtein", "Protein"]: metric_type = "p"
                 
                 if metric_type:
                     try:
                         val = float(p_val)
                         # Use Date or Now
                         ts_key = p_date or datetime.now(timezone.utc).isoformat()
                         
                         if ts_key not in parsed_meals:
                             parsed_meals[ts_key] = {"c":0.0, "f":0.0, "p":0.0, "fib":0.0, "ts": ts_key, "fiber_provided": False}
                         
                         parsed_meals[ts_key][metric_type] += val
                         if metric_type == "fib":
                             parsed_meals[ts_key]["fiber_provided"] = True
                         logger.info(f"Parsed Flat Payload: {metric_type}={val} from {p_type}")
                         
                     except ValueError:
                         pass
            
             else:
                 # FALLBACK: Try Direct Flat Keys (Simple JSON / n8n / Shortcuts)
                 norm = normalize_nutrition_payload(real_payload)
                 c_raw = norm.get("carbs")
                 f_raw = norm.get("fat")
                 p_raw = norm.get("protein")
                 fib_raw = norm.get("fiber")

                 c = float(c_raw) if c_raw is not None else 0.0
                 f = float(f_raw) if f_raw is not None else 0.0
                 p = float(p_raw) if p_raw is not None else 0.0
                 fib = float(fib_raw) if fib_raw is not None else None
                 fiber_provided = fib_raw is not None
                 
                 if c > 0 or f > 0 or p > 0 or (fib is not None and fib > 0):
                     ts_key = norm.get("timestamp") or real_payload.get("timestamp") or real_payload.get("created_at") or datetime.now(timezone.utc).isoformat()
                     parsed_meals[ts_key] = {
                         "c": c,
                         "f": f,
                         "p": p,
                         "fib": fib if fib is not None else 0.0,
                         "ts": ts_key,
                         "fiber_provided": fiber_provided,
                         "source": real_payload.get("source") or source,
                         "fingerprint": (
                             real_payload.get("meal_id")
                             or real_payload.get("meal_fingerprint")
                             or real_payload.get("fingerprint")
                             or real_payload.get("origin_id")
                         ),
                         "source_revision": real_payload.get("meal_revision") or real_payload.get("revision"),
                     }
                     logger.info(f"Parsed Direct Payload: C={c} F={f} P={p} Fib={fib}")

        if not parsed_meals:
             res = {"success": 0, "message": "No parseable metrics found in payload"}
             log_entry["status"] = "rejected"
             log_entry["result"] = res
             append_log(log_entry)
             return res

        before_daily_dump_filter = len(parsed_meals)
        parsed_meals = _filter_mfp_health_connect_daily_dump(parsed_meals)
        is_mfp_daily_dump = len(parsed_meals) != before_daily_dump_filter
        if is_mfp_daily_dump:
            logger.info(
                "nutrition_ingest_mfp_daily_dump_filtered ingest_id=%s before=%s after=%s",
                ingest_id,
                before_daily_dump_filter,
                len(parsed_meals),
            )

        # 2. Process distinct meals found
        # Sort by date descending (newest first)
        sorted_keys = sorted(parsed_meals.keys(), key=lambda key: parsed_meals[key].get("ts") or key, reverse=True)
        logger.info("nutrition_ingest_timestamps ingest_id=%s unique_timestamps=%s", ingest_id, len(sorted_keys))

        for date_key in sorted_keys:
            meal = parsed_meals[date_key]
            logger.info(
                "nutrition_ingest_meal ingest_id=%s timestamp=%s carbs=%s fat=%s protein=%s fiber=%s source=%s",
                ingest_id,
                date_key,
                meal.get("c"),
                meal.get("f"),
                meal.get("p"),
                meal.get("fib"),
                meal.get("source"),
            )

        created_ids = []
        updated_ids = []
        updated_count = 0
        skipped_count = 0
        
        if session:
            from app.models.treatment import Treatment
            
            # Use top 500 recent meals (extended history)
            count = 0 
            for date_key in sorted_keys:
                if count >= 500: break
                
                meal = parsed_meals[date_key]
                t_carbs = round(meal["c"], 1)
                t_fat = round(meal["f"], 1)
                t_protein = round(meal["p"], 1)
                fiber_provided = meal.get("fiber_provided", False)
                t_fiber_raw = meal.get("fib", 0)
                t_fiber = round(float(t_fiber_raw or 0), 1)
                incoming_fiber = t_fiber if fiber_provided else None
                
                if t_carbs < 1 and t_fat < 1 and t_protein < 1 and t_fiber < 1: continue

                # Parse Date with Force-Now Logic
                force_now = False
                try:
                    ts_str = meal["ts"]
                    now_utc = datetime.now(timezone.utc)
                    item_ts = None
                    
                    # Multi-format date parser
                    parse_formats = [
                        "%Y-%m-%d %H:%M:%S %z",
                        "%Y-%m-%dT%H:%M:%S%z",
                        "%Y-%m-%dT%H:%M:%S.%f%z",
                        "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%dT%H:%M:%S.%fZ",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M:%S",
                    ]
                    
                    for fmt in parse_formats:
                        try:
                            clean_ts = datetime.strptime(ts_str, fmt)
                            if clean_ts.tzinfo is not None:
                                item_ts = clean_ts.astimezone(timezone.utc)
                            else:
                                from app.utils.timezone import get_user_timezone
                                tz_local = get_user_timezone()
                                item_ts = clean_ts.replace(tzinfo=tz_local).astimezone(timezone.utc)
                            break
                        except ValueError:
                            continue
                    
                    # Fallback fromisoformat
                    if item_ts is None:
                        try:
                            clean_str = ts_str.replace("Z", "+00:00")
                            parsed = datetime.fromisoformat(clean_str)
                            if parsed.tzinfo is None:
                                from app.utils.timezone import get_user_timezone
                                parsed = parsed.replace(tzinfo=get_user_timezone())
                            item_ts = parsed.astimezone(timezone.utc)
                        except Exception:
                            pass
                    
                    # Fallback NOW
                    if item_ts is None:
                        item_ts = now_utc
                        force_now = True
                        
                except Exception as e:
                    logger.warning(f"Date parse soft-fail: {ts_str} -> {e}. Using NOW.")
                    item_ts = datetime.now(timezone.utc)
                    force_now = True

                logger.info(
                    "nutrition_ingest_timestamp ingest_id=%s ts_raw=%s ts_parsed=%s force_now=%s",
                    ingest_id,
                    ts_str,
                    item_ts.isoformat(),
                    force_now,
                )

                # 0. STRICT DEDUP CHECK (History-based)
                # Check if we have already imported this specific external timestamp/ID.
                # This handles cases where we "snap to now" and thus lose the temporal correlation 
                # with the original event in the DB's created_at field.
                import_key = meal.get("fingerprint") or date_key
                meal_source = str(meal.get("source") or source or "unknown")
                external_meal_id = f"{meal_source.strip().lower()}|{import_key}"
                nutrition_total = {
                    "carbs": t_carbs,
                    "fat": t_fat,
                    "protein": t_protein,
                    "fiber": t_fiber,
                }
                meal_revision = nutrition_revision(
                    nutrition_total, meal.get("source_revision")
                )
                coverage_upsert = await upsert_current_meal(
                    session,
                    user_id=username,
                    external_meal_id=external_meal_id,
                    source=meal_source,
                    revision=meal_revision,
                    nutrition=nutrition_total,
                )
                coverage_state = coverage_upsert.state

                # Transition safety for a meal bolused immediately before this
                # schema existed.  Backfill only from one unambiguous, actually
                # registered Telegram treatment in the same short meal window;
                # recommendations and insulin=0 imports are never evidence.
                if coverage_upsert.created:
                    legacy_window_start = (
                        item_ts - timedelta(minutes=15)
                    ).replace(tzinfo=None)
                    legacy_window_end = (
                        item_ts + timedelta(minutes=90)
                    ).replace(tzinfo=None)
                    legacy_stmt = select(Treatment).where(
                        Treatment.user_id == username,
                        Treatment.insulin > 0,
                        Treatment.entered_by == "TelegramBot",
                        Treatment.notes.contains("Importado"),
                        Treatment.created_at >= legacy_window_start,
                        Treatment.created_at <= legacy_window_end,
                    )
                    legacy_rows = list(
                        (await session.execute(legacy_stmt)).scalars().all()
                    )
                    compatible_legacy_rows = [
                        row
                        for row in legacy_rows
                        if float(row.carbs or 0) > 0
                        and float(row.carbs or 0) <= t_carbs + 0.1
                        and float(row.fat or 0) <= t_fat + 0.1
                        and float(row.protein or 0) <= t_protein + 0.1
                        and float(row.fiber or 0) <= t_fiber + 0.1
                    ]
                    if len(compatible_legacy_rows) == 1:
                        legacy = compatible_legacy_rows[0]
                        coverage_state.covered_nutrition = {
                            "carbs": float(legacy.carbs or 0),
                            "fat": float(legacy.fat or 0),
                            "protein": float(legacy.protein or 0),
                            "fiber": float(legacy.fiber or 0),
                        }
                        coverage_state.last_confirmed_bolus = float(
                            legacy.insulin or 0
                        )
                        coverage_state.confirmed_at = legacy.created_at
                        coverage_state.last_calculation_id = f"legacy:{legacy.id}"
                        coverage_state.last_treatment_id = legacy.id
                        session.add(coverage_state)
                        await session.flush()
                        logger.warning(
                            "meal_coverage_legacy_backfill meal_key=%s treatment_id=%s covered=%s",
                            coverage_state.meal_key,
                            legacy.id,
                            coverage_state.covered_nutrition,
                        )
                import_trace = {
                    "meal_import": {
                        "schema_version": 1,
                        "meal_id": external_meal_id,
                        "meal_key": coverage_state.meal_key,
                        "revision": meal_revision,
                        "revision_number": coverage_state.revision_number,
                        "nutrition_total": nutrition_total,
                        "sync_id": sync_id,
                    }
                }
                import_sig = f"Imported from Health: {import_key} #imported"
                stmt_strict = select(Treatment).where(
                    Treatment.user_id == username,
                    Treatment.notes.contains(import_sig),
                )
                result_strict = await session.execute(stmt_strict)
                existing_strict = result_strict.scalars().first()
                


                if existing_strict:
                     # Check for ANY meaningful change (Correction/Edit in Source)
                     changes = []
                     existing_carbs = float(existing_strict.carbs or 0)
                     existing_fat = float(existing_strict.fat or 0)
                     existing_protein = float(existing_strict.protein or 0)
                     if abs(existing_carbs - t_carbs) > 0.1:
                         existing_strict.carbs = t_carbs
                         changes.append("carbs")
                     if abs(existing_fat - t_fat) > 0.1:
                         existing_strict.fat = t_fat
                         changes.append("fat")
                     if abs(existing_protein - t_protein) > 0.1:
                         existing_strict.protein = t_protein
                         changes.append("protein")
                     
                     # Fiber Update
                     if fiber_provided and incoming_fiber is not None:
                         if should_update_fiber(existing_strict.fiber, incoming_fiber):
                             existing_strict.fiber = float(incoming_fiber)
                             changes.append("fiber")

                     if changes:
                         current_note = existing_strict.notes or ""
                         if "[Updated]" not in current_note:
                            existing_strict.notes = current_note + " [Updated]"

                         session.add(existing_strict)
                         existing_strict.calculation_trace = import_trace
                         await session.flush()
                         updated_count += 1
                         updated_ids.append(existing_strict.id)  # Track for notification
                         logger.info(
                             "nutrition_ingest_action ingest_id=%s action=update id=%s timestamp=%s changes=%s",
                             ingest_id,
                             existing_strict.id,
                             date_key,
                             changes,
                         )
                     else:
                         skipped_count += 1
                         logger.info(
                             "nutrition_ingest_action ingest_id=%s action=skip id=%s timestamp=%s",
                             ingest_id,
                             existing_strict.id,
                             date_key,
                         )
                     continue

                # The imported draft is intentionally deleted after a
                # confirmation. A later identical sync must not recreate it
                # and emit another recommendation for an already processed
                # revision.
                remaining_nutrition = calculate_incremental_nutrition(
                    coverage_state.current_nutrition,
                    coverage_state.covered_nutrition,
                )
                if (
                    not coverage_upsert.revision_changed
                    and not remaining_nutrition.has_new_nutrition
                ):
                    skipped_count += 1
                    logger.info(
                        "nutrition_ingest_action ingest_id=%s action=skip_same_revision meal_key=%s revision=%s",
                        ingest_id,
                        coverage_state.meal_key,
                        meal_revision,
                    )
                    continue

                # Dedup check
                # Rule: Short window (3h) for the NEWEST meal (count=0) to allow repeat meals.
                # Rule: Long window (18h) for HISTORY to prevent re-importing old meals.
                
                if force_now:
                    check_window_hours = 3.0 if count == 0 else 18.0
                else:
                    check_window_hours = 0.5 

                dedup_window_end = (item_ts + timedelta(minutes=15)).replace(tzinfo=None)
                dedup_window_start = (item_ts - timedelta(hours=check_window_hours)).replace(tzinfo=None)
                
                stmt = select(Treatment).where(
                    Treatment.user_id == username,
                    Treatment.created_at >= dedup_window_start,
                    Treatment.created_at <= dedup_window_end,
                    Treatment.carbs >= (t_carbs - 1.0), # Relaxed search window (Carbs match strict)
                    Treatment.carbs <= (t_carbs + 1.0)
                )
                result = await session.execute(stmt)
                candidates = list(result.scalars().all())

                # Health Connect can export every MFP meal with one synthetic/old
                # timestamp. After reducing that daily dump to its latest meal,
                # compare it with recent Hermes imports by macros as well. This
                # prevents the same meal entering twice through both channels.
                if is_mfp_daily_dump:
                    recent_window_start = (
                        datetime.now(timezone.utc) - timedelta(hours=3)
                    ).replace(tzinfo=None)
                    recent_stmt = select(Treatment).where(
                        Treatment.user_id == username,
                        Treatment.created_at >= recent_window_start,
                        Treatment.carbs >= (t_carbs - 1.0),
                        Treatment.carbs <= (t_carbs + 1.0),
                    )
                    recent_result = await session.execute(recent_stmt)
                    candidates_by_id = {candidate.id: candidate for candidate in candidates}
                    candidates_by_id.update(
                        {candidate.id: candidate for candidate in recent_result.scalars().all()}
                    )
                    candidates = list(candidates_by_id.values())

                if parse_nutrition_shadow_mode(os.getenv("NUTRITION_DEDUPE_MODE")) == "shadow":
                    incoming_event = NutritionShadowEvent(
                        user_id=username,
                        occurred_at=item_ts,
                        carbs=t_carbs,
                        source=meal.get("source") or source,
                        fingerprint=meal.get("fingerprint"),
                    )
                    for candidate in candidates:
                        candidate_event = NutritionShadowEvent(
                            user_id=candidate.user_id,
                            occurred_at=candidate.created_at,
                            carbs=candidate.carbs,
                            source=(
                                "hermes"
                                if "hermes" in (candidate.notes or "").lower()
                                else candidate.entered_by
                            ),
                            fingerprint=extract_import_fingerprint(candidate.notes),
                        )
                        classification = classify_nutrition_candidate(incoming_event, candidate_event)
                        logger.info(
                            "nutrition_dedup_shadow ingest_id=%s mode=shadow classification=%s "
                            "incoming_source=%s candidate_source=%s candidate_id=%s",
                            ingest_id,
                            classification,
                            incoming_event.source,
                            candidate_event.source,
                            candidate.id,
                        )
                
                is_duplicate = False
                for c in candidates:
                    # Check if it's the same meal (Carbs very close)
                    carbs_tolerance = 1.0 if is_mfp_daily_dump else 0.5
                    if abs(c.carbs - t_carbs) <= carbs_tolerance:
                        
                        # ENRICHMENT CHECK:
                        # If existing lacks Fat/Protein/Fiber and incoming HAS it, update it.
                        # Or if incoming matches (duplicate).
                        
                        c_fat = c.fat or 0
                        c_prot = c.protein or 0
                        c_fib = c.fiber or 0
                        
                        # 1. Exact Match (Duplicate)
                        if abs(c_fat - t_fat) < 0.5 and abs(c_prot - t_protein) < 0.5:
                             # Check Fiber Update
                             if fiber_provided and incoming_fiber is not None:
                                 if should_update_fiber(float(c_fib), incoming_fiber):
                                     c.fiber = float(incoming_fiber)
                                     c.calculation_trace = {
                                         **(c.calculation_trace or {}),
                                         **import_trace,
                                     }
                                     session.add(c)
                                     await session.flush()
                                     updated_count += 1
                                     updated_ids.append(c.id) # Track for notification (Fiber update)
                                     logger.info(
                                         "nutrition_ingest_action ingest_id=%s action=update id=%s timestamp=%s changes=%s",
                                         ingest_id,
                                         c.id,
                                         date_key,
                                         ["fiber"],
                                     )
                             is_duplicate = True
                             skipped_count += 1
                             logger.info(
                                 "nutrition_ingest_action ingest_id=%s action=skip id=%s timestamp=%s",
                                 ingest_id,
                                 c.id,
                                 date_key,
                             )
                             break
                        
                        # 2. Enrichment (Existing is 'smaller' than incoming in terms of info)
                        # We assume if Carbs match and time is close, it IS the same meal.
                        # Especially if existing has 0 fat/prot and new has > 0.
                        
                        is_enrichment = False
                        if t_fat > (c_fat + 0.5) or t_protein > (c_prot + 0.5):
                             is_enrichment = True
                        
                        # If Enrichment, UPDATE the existing one
                        if is_enrichment:
                             c.fat = float(t_fat)
                             c.protein = float(t_protein)
                             if fiber_provided and incoming_fiber is not None:
                                 c.fiber = float(incoming_fiber)
                             
                             c.notes = (c.notes or "") + " [Enriched]"
                             c.calculation_trace = {
                                 **(c.calculation_trace or {}),
                                 **import_trace,
                             }
                             session.add(c)
                             await session.flush()
                             updated_count += 1
                             updated_ids.append(c.id) # Track for notification (Macro enrichment)
                             logger.info(
                                 "nutrition_ingest_action ingest_id=%s action=update id=%s timestamp=%s changes=%s",
                                 ingest_id,
                                 c.id,
                                 date_key,
                                 ["fat", "protein", "fiber"],
                             )
                             is_duplicate = True
                             break

                        # 3. Fiber Only Enrichment
                        if fiber_provided and incoming_fiber is not None and abs((c.fiber or 0) - incoming_fiber) > 0.1:
                             c.fiber = float(incoming_fiber)
                             c.calculation_trace = {
                                 **(c.calculation_trace or {}),
                                 **import_trace,
                             }
                             session.add(c)
                             await session.flush()
                             updated_count += 1
                             updated_ids.append(c.id) # Track
                             logger.info(
                                 "nutrition_ingest_action ingest_id=%s action=update id=%s timestamp=%s changes=%s",
                                 ingest_id,
                                 c.id,
                                 date_key,
                                 ["fiber"],
                             )
                             is_duplicate = True
                             break
                             
                
                if is_duplicate:
                    continue
                
                # New Treatment
                tid = str(uuid.uuid4())
                
                # Ensure created_at is UTC Naive for DB
                db_created_at = item_ts.astimezone(timezone.utc).replace(tzinfo=None)
                
                new_t = Treatment(
                    id=tid,
                    user_id=username,
                    event_type="Meal Bolus", 
                    created_at=db_created_at,
                    insulin=0.0,
                    carbs=t_carbs,
                    fat=t_fat,
                    protein=t_protein,
                    fiber=t_fiber,
                    notes=f"Imported from Health: {import_key} #imported",
                    entered_by="webhook-integration",
                    calculation_trace=import_trace,
                    is_uploaded=False
                )
                session.add(new_t)
                created_ids.append(tid)
                count += 1
                logger.info(
                    "nutrition_ingest_action ingest_id=%s action=create id=%s timestamp=%s",
                    ingest_id,
                    tid,
                    date_key,
                )
                
            # Transactional outbox: the treatment and its notification intent are
            # committed together. Telegram delivery happens only after this request.
            all_ids = list(dict.fromkeys(created_ids + updated_ids))

            if all_ids:
                await session.flush()
                logger.info(
                    "nutrition_ingest_summary ingest_id=%s created_count=%s updated_count=%s skipped_count=%s notify_candidates=%s",
                    ingest_id,
                    len(created_ids),
                    len(updated_ids),
                    skipped_count,
                    len(all_ids),
                )
                
                treatments_to_notify = []
                for tid in all_ids:
                    t_obj = await session.get(Treatment, tid)
                    if t_obj and is_valid_ingestion(t_obj.carbs, t_obj.fat, t_obj.protein, t_obj.fiber):
                        treatments_to_notify.append(t_obj)
                treatments_to_notify.sort(key=lambda item: item.created_at)
                for t_obj in treatments_to_notify:
                    is_update = t_obj.id in updated_ids
                    notify_source = "Actualizado" if is_update else "Importado"
                    meal_import = (
                        (t_obj.calculation_trace or {}).get("meal_import", {})
                        if isinstance(t_obj.calculation_trace, dict)
                        else {}
                    )
                    await enqueue_meal_notification(
                        session,
                        event_id=t_obj.id,
                        notification_kind="meal_updated" if is_update else "meal_created",
                        user_id=username,
                        sync_id=sync_id,
                        payload={
                            "carbs": t_obj.carbs,
                            "fat": t_obj.fat or 0.0,
                            "protein": t_obj.protein or 0.0,
                            "fiber": t_obj.fiber or 0.0,
                            "source": f"{notify_source} ({username})",
                            "origin_id": t_obj.id,
                            "user_id": username,
                            "meal_id": meal_import.get("meal_id"),
                            "meal_revision": meal_import.get("revision"),
                        },
                    )
                    logger.info(
                        "nutrition_notify_outbox event_id=%s sync_id=%s kind=%s",
                        t_obj.id,
                        sync_id,
                        "meal_updated" if is_update else "meal_created",
                    )
                await session.commit()
                notification_status = await notification_status_for_events(session, all_ids)
                res = {
                    "success": 1,
                    "sync_id": sync_id,
                    "ingest_status": "success",
                    "notification_status": notification_status,
                    "message": "Meal synchronized; notification pending" if notification_status in {"queued", "retry_scheduled"} else "Meal synchronized",
                    "ingested_count": len(created_ids),
                    "updated_count": len(updated_ids),
                    "ids": all_ids,
                }
                log_entry["status"] = "success"
                log_entry["result"] = res
                append_log(log_entry)
                return res
            else:
                logger.info(
                    "nutrition_ingest_summary ingest_id=%s created_count=%s updated_count=%s skipped_count=%s ids_count_unique=%s",
                    ingest_id,
                    len(created_ids),
                    updated_count,
                    skipped_count,
                    len(dict.fromkeys(created_ids)),
                )
                await session.commit()
                res = {
                    "success": 1,
                    "sync_id": sync_id,
                    "ingest_status": "no_changes",
                    "notification_status": "not_required",
                    "message": "No new meals found (all duplicates or empty)",
                    "ingested_count": 0,
                    "ids": [],
                }
                log_entry["status"] = "ignored"
                log_entry["result"] = res
                append_log(log_entry)
                return res

        return {"success": 0, "message": "Database session missing"}
        
    except HTTPException:
        # Bubble up authentication errors or explicit HTTP responses
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Nutrition Ingest Error: {e}")
        # Return 200 to not break the sender, but log error
        res = {
            "success": 0,
            "sync_id": sync_id,
            "ingest_status": "failed",
            "notification_status": "not_required",
            "error": str(e),
        }
        log_entry["status"] = "error"
        log_entry["result"] = res
        append_log(log_entry)
        return res


@router.get("/nutrition/recent", summary="Get recent imported nutrition entries")
async def get_recent_imported_nutrition(
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
    user: CurrentUser = Depends(get_current_user),
):
    from app.models.treatment import Treatment

    # Pending vs consumed:
    # - Pending imported meals are stored as treatments with insulin=0, entered_by=webhook-integration
    #   and a "#imported" marker in notes.
    # - When a bolus accepts/replaces an import (replace_id flow), the original treatment is deleted.
    #   Therefore, "consumed" imports are excluded by absence plus the insulin==0 filter below.
    stmt = (
        select(Treatment)
        .where(
            Treatment.user_id == user.username,
            Treatment.insulin == 0,
            Treatment.entered_by == "webhook-integration",
            Treatment.notes.contains("#imported"),
        )
        .order_by(Treatment.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    treatments = result.scalars().all()

    return [
        {
            "id": t.id,
            "timestamp": t.created_at.isoformat(),
            "source": _resolve_import_source(t.notes),
            "carbs": float(t.carbs or 0.0),
            "protein": float(t.protein or 0.0),
            "fat": float(t.fat or 0.0),
            "fiber": float(t.fiber or 0.0),
        }
        for t in treatments
    ]

@router.get("/nutrition/logs", summary="Get recent ingestion logs")
async def get_ingest_logs(
    settings: Settings = Depends(get_settings),
    user: CurrentUser = Depends(get_current_user)
):
    from pathlib import Path
    from app.services.store import DataStore
    ds = DataStore(Path(settings.data.data_dir))
    return ds.read_json("ingest_logs.json", [])
