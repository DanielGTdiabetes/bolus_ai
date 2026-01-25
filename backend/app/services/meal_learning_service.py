import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meal_learning import MealCluster, MealExperience
from app.models.settings import UserSettings
from app.models.treatment import Treatment
from app.services.nightscout_client import NightscoutClient, NightscoutSGV


logger = logging.getLogger(__name__)

EVENT_KIND_CORRECTION = "CORRECTION_ONLY"
EVENT_KIND_CARBS_ONLY = "CARBS_ONLY"
EVENT_KIND_DUAL = "MEAL_DUAL"
EVENT_KIND_STANDARD = "MEAL_STANDARD"


@dataclass
class ClusterCurve:
    duration_min: int
    peak_min: int
    tail_min: int
    shape: str = "triangle"


def _macro_bucket(value: float, size: int) -> int:
    return int(value // size) * size


def build_tags_key(tags: Optional[Iterable[str]]) -> str:
    if not tags:
        return "none"
    return ",".join(sorted({str(t).strip().lower() for t in tags if str(t).strip()})) or "none"


def build_cluster_key(
    carb_profile: Optional[str],
    tags_key: str,
    carbs_g: float,
    protein_g: float,
    fat_g: float,
    fiber_g: float,
    user_id: Optional[str] = None,
) -> str:
    carb_bucket = _macro_bucket(carbs_g, 10)
    protein_bucket = _macro_bucket(protein_g, 10)
    fat_bucket = _macro_bucket(fat_g, 10)
    fiber_bucket = _macro_bucket(fiber_g, 5)
    profile = carb_profile or "auto"
    base_key = f"{profile}|{tags_key}|C{carb_bucket}-P{protein_bucket}-F{fat_bucket}-Fi{fiber_bucket}"
    return f"{user_id}:{base_key}" if user_id else base_key


def classify_event_kind(treatment: Treatment, bolus_payload: Optional[dict] = None) -> tuple[str, str]:
    carbs_g = float(getattr(treatment, "carbs", 0) or 0)
    insulin_u = float(getattr(treatment, "insulin", 0) or 0)

    if bolus_payload:
        carbs_g = float(bolus_payload.get("carbs_g", bolus_payload.get("carbs", carbs_g)) or carbs_g)
        insulin_u = float(bolus_payload.get("insulin_u", bolus_payload.get("insulin", insulin_u)) or insulin_u)

    if carbs_g <= 1 and insulin_u > 0:
        return EVENT_KIND_CORRECTION, "Corrección con carbs <= 1g"
    if carbs_g > 0 and insulin_u <= 0.1:
        return EVENT_KIND_CARBS_ONLY, "Carbs sin insulina (<=0.1u)"

    notes = (getattr(treatment, "notes", "") or "").lower()
    event_type = (getattr(treatment, "event_type", "") or "").lower()
    duration = float(getattr(treatment, "duration", 0) or 0)

    dual_flags = []
    if duration > 0:
        dual_flags.append("duración extendida")
    if any(k in notes for k in ("dual", "combo", "extended", "split")):
        dual_flags.append("nota dual/extended/split")
    if any(k in event_type for k in ("dual", "extended", "combo", "split")):
        dual_flags.append("event_type dual/extended/split")
    if bolus_payload:
        if bolus_payload.get("extended") or bolus_payload.get("dual") or bolus_payload.get("split"):
            dual_flags.append("payload dual/extended/split")
        if float(bolus_payload.get("extended_units", 0) or 0) > 0:
            dual_flags.append("extended_units > 0")

    if dual_flags:
        return EVENT_KIND_DUAL, f"Dual detectado: {', '.join(dual_flags)}"

    return EVENT_KIND_STANDARD, "Comida estándar"


def base_curve_for_profile(carb_profile: Optional[str]) -> ClusterCurve:
    profile = (carb_profile or "med").lower()
    if profile == "fast":
        return ClusterCurve(duration_min=120, peak_min=45, tail_min=75)
    if profile == "slow":
        return ClusterCurve(duration_min=300, peak_min=90, tail_min=210)
    return ClusterCurve(duration_min=180, peak_min=60, tail_min=120)


def clamp_curve(candidate: ClusterCurve, base: ClusterCurve) -> ClusterCurve:
    min_duration = int(base.duration_min * 0.85)
    max_duration = int(base.duration_min * 1.15)
    min_peak = int(base.peak_min * 0.85)
    max_peak = int(base.peak_min * 1.15)
    min_tail = int(base.tail_min * 0.85)
    max_tail = int(base.tail_min * 1.15)

    duration = max(min_duration, min(max_duration, candidate.duration_min))
    peak = max(min_peak, min(max_peak, candidate.peak_min))
    tail = max(min_tail, min(max_tail, candidate.tail_min))

    duration = max(90, min(360, duration))
    peak = max(30, min(180, peak))
    tail = max(30, min(240, tail))

    return ClusterCurve(duration_min=duration, peak_min=peak, tail_min=tail, shape=candidate.shape)


class MealLearningService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def evaluate_treatments(
        self,
        user_id: str,
        settings: UserSettings,
        ns_client: Optional[NightscoutClient] = None,
        now: Optional[datetime] = None,
        lookback_hours: int = 72,
        sgv_provider=None,
    ) -> int:
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=lookback_hours)

        stmt = (
            select(Treatment)
            .where(Treatment.user_id == user_id)
            .where(Treatment.created_at >= cutoff.replace(tzinfo=None))
            .order_by(Treatment.created_at.desc())
        )
        treatments = (await self.session.execute(stmt)).scalars().all()

        created_count = 0
        for treatment in treatments:
            if await self._experience_exists(treatment.user_id, treatment.id):
                continue

            event_kind, event_kind_reason = classify_event_kind(treatment)
            meal_type = self._resolve_meal_type(treatment.created_at, settings)
            tags = self._extract_tags(treatment.notes or "")
            tags_key = build_tags_key(tags)

            window_minutes = self._window_minutes_for_profile(treatment.carb_profile)
            if now < self._ensure_aware(treatment.created_at) + timedelta(minutes=window_minutes):
                continue

            sgv_points = []
            if sgv_provider:
                sgv_points = sgv_provider(treatment, window_minutes)
            elif ns_client:
                sgv_points = await ns_client.get_sgv_range(
                    self._ensure_aware(treatment.created_at),
                    self._ensure_aware(treatment.created_at) + timedelta(minutes=window_minutes),
                )

            experience = await self._build_experience(
                treatment=treatment,
                event_kind=event_kind,
                event_kind_reason=event_kind_reason,
                meal_type=meal_type,
                tags_key=tags_key,
                sgv_points=sgv_points,
                tags=tags,
                window_minutes=window_minutes,
            )
            if experience is None:
                continue

            self.session.add(experience)
            await self.session.commit()
            created_count += 1

            logger.info(
                "Meal experience created: treatment_id=%s event_kind=%s window_status=%s",
                treatment.id,
                experience.event_kind,
                experience.window_status,
            )

            await self._update_clusters_from_experience(experience, tags_key)

        return created_count

    async def _experience_exists(self, user_id: str, treatment_id: str) -> bool:
        stmt = select(MealExperience.id).where(
            MealExperience.user_id == user_id,
            MealExperience.treatment_id == treatment_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def _build_experience(
        self,
        treatment: Treatment,
        event_kind: str,
        event_kind_reason: str,
        meal_type: Optional[str],
        tags_key: str,
        sgv_points: list[NightscoutSGV],
        tags: list[str],
        window_minutes: int,
    ) -> Optional[MealExperience]:
        window_status = "ok"
        discard_reason = None
        data_quality = {"points": len(sgv_points)}

        if event_kind in {EVENT_KIND_CORRECTION, EVENT_KIND_CARBS_ONLY}:
            window_status = "excluded"
            discard_reason = "Evento excluido por tipo"

        if not sgv_points:
            window_status = "excluded"
            discard_reason = discard_reason or "Datos insuficientes"

        interference = await self._detect_interference(treatment, window_minutes)
        if interference:
            window_status = "excluded"
            discard_reason = interference

        outcomes = self._compute_outcomes(
            treatment=treatment,
            sgv_points=sgv_points,
            window_minutes=window_minutes,
        )

        required_end = self._required_end_value(treatment.carb_profile, outcomes)
        if required_end is None and window_status == "ok":
            window_status = "excluded"
            discard_reason = discard_reason or "Falta BG en ventana requerida"

        experience = MealExperience(
            treatment_id=treatment.id,
            created_at=treatment.created_at,
            user_id=treatment.user_id,
            meal_type=meal_type,
            carbs_g=float(treatment.carbs or 0),
            protein_g=float(treatment.protein or 0),
            fat_g=float(treatment.fat or 0),
            fiber_g=float(treatment.fiber or 0),
            tags_json=tags,
            carb_profile=treatment.carb_profile,
            event_kind=event_kind,
            window_status=window_status,
            discard_reason=discard_reason,
            event_kind_reason=event_kind_reason,
            data_quality_json=data_quality,
            **outcomes,
        )
        return experience

    def _required_end_value(self, carb_profile: Optional[str], outcomes: dict) -> Optional[float]:
        profile = (carb_profile or "med").lower()
        if profile == "fast":
            return outcomes.get("bg_end_2h")
        if profile == "slow":
            return outcomes.get("bg_end_5h")
        return outcomes.get("bg_end_3h")

    async def _detect_interference(self, treatment: Treatment, window_minutes: int) -> Optional[str]:
        start = treatment.created_at
        end = start + timedelta(minutes=window_minutes)
        stmt = (
            select(Treatment)
            .where(Treatment.user_id == treatment.user_id)
            .where(Treatment.created_at > start)
            .where(Treatment.created_at < end)
            .where(Treatment.id != treatment.id)
        )
        interfering = (await self.session.execute(stmt)).scalars().all()
        for entry in interfering:
            entry_kind, _ = classify_event_kind(entry)
            if entry_kind in {EVENT_KIND_CORRECTION, EVENT_KIND_CARBS_ONLY}:
                continue
            if entry.carbs and entry.carbs > 10:
                return f"Interferencia: snack +{entry.carbs}g"
            if entry.insulin and entry.insulin > 1.0:
                return f"Interferencia: corrección +{entry.insulin}u"
        return None

    def _compute_outcomes(
        self,
        treatment: Treatment,
        sgv_points: list[NightscoutSGV],
        window_minutes: int,
    ) -> dict:
        if not sgv_points:
            return {
                "bg_start": None,
                "bg_peak": None,
                "bg_min": None,
                "bg_end_2h": None,
                "bg_end_3h": None,
                "bg_end_5h": None,
                "delta_2h": None,
                "delta_3h": None,
                "delta_5h": None,
                "score": None,
            }

        start_dt = self._ensure_aware(treatment.created_at)
        points = sorted(
            [(self._epoch_ms_to_dt(p.date), p.sgv) for p in sgv_points],
            key=lambda x: x[0],
        )
        bg_start = points[0][1]
        bg_peak = max(points, key=lambda x: x[1])[1]
        bg_min = min(points, key=lambda x: x[1])[1]

        def _value_at(hours: int) -> Optional[float]:
            target = start_dt + timedelta(hours=hours)
            closest = min(points, key=lambda x: abs((x[0] - target).total_seconds()))
            if abs((closest[0] - target).total_seconds()) > 20 * 60:
                return None
            return closest[1]

        bg_end_2h = _value_at(2)
        bg_end_3h = _value_at(3)
        bg_end_5h = _value_at(5)

        delta_2h = bg_end_2h - bg_start if bg_end_2h is not None else None
        delta_3h = bg_end_3h - bg_start if bg_end_3h is not None else None
        delta_5h = bg_end_5h - bg_start if bg_end_5h is not None else None

        score = None
        score_target = self._required_end_value(treatment.carb_profile, {
            "bg_end_2h": bg_end_2h,
            "bg_end_3h": bg_end_3h,
            "bg_end_5h": bg_end_5h,
        })
        if score_target is not None:
            delta = score_target - bg_start
            score = max(0.0, 10.0 - abs(delta or 0) / 20.0)

        return {
            "bg_start": bg_start,
            "bg_peak": bg_peak,
            "bg_min": bg_min,
            "bg_end_2h": bg_end_2h,
            "bg_end_3h": bg_end_3h,
            "bg_end_5h": bg_end_5h,
            "delta_2h": delta_2h,
            "delta_3h": delta_3h,
            "delta_5h": delta_5h,
            "score": score,
        }

    async def _update_clusters_from_experience(self, experience: MealExperience, tags_key: str) -> None:
        if experience.event_kind != EVENT_KIND_STANDARD:
            return

        cluster_key = build_cluster_key(
            experience.carb_profile,
            tags_key,
            experience.carbs_g,
            experience.protein_g,
            experience.fat_g,
            experience.fiber_g,
            user_id=experience.user_id,
        )

        stmt = select(MealCluster).where(
            MealCluster.cluster_key == cluster_key,
            MealCluster.user_id == experience.user_id,
        )
        cluster = (await self.session.execute(stmt)).scalar_one_or_none()

        if experience.window_status == "discarded":
            if cluster:
                cluster.n_discarded += 1
                cluster.last_updated_at = datetime.utcnow()
                await self.session.commit()
            return

        if experience.window_status != "ok":
            return

        if not cluster:
            base_curve = base_curve_for_profile(experience.carb_profile)
            cluster = MealCluster(
                cluster_key=cluster_key,
                user_id=experience.user_id,
                carb_profile=experience.carb_profile,
                tags_key=tags_key,
                centroid_carbs=experience.carbs_g,
                centroid_protein=experience.protein_g,
                centroid_fat=experience.fat_g,
                centroid_fiber=experience.fiber_g,
                n_ok=0,
                n_discarded=0,
                confidence="low",
                absorption_duration_min=base_curve.duration_min,
                peak_min=base_curve.peak_min,
                tail_min=base_curve.tail_min,
                shape=base_curve.shape,
                last_updated_at=datetime.utcnow(),
            )
            self.session.add(cluster)

        n_ok = cluster.n_ok or 0
        cluster.centroid_carbs = (cluster.centroid_carbs * n_ok + experience.carbs_g) / (n_ok + 1)
        cluster.centroid_protein = (cluster.centroid_protein * n_ok + experience.protein_g) / (n_ok + 1)
        cluster.centroid_fat = (cluster.centroid_fat * n_ok + experience.fat_g) / (n_ok + 1)
        cluster.centroid_fiber = (cluster.centroid_fiber * n_ok + experience.fiber_g) / (n_ok + 1)
        cluster.n_ok = n_ok + 1

        observed_curve = self._curve_from_experience(experience)
        base_curve = base_curve_for_profile(experience.carb_profile)
        adjusted = clamp_curve(observed_curve, base_curve)
        cluster.absorption_duration_min = adjusted.duration_min
        cluster.peak_min = adjusted.peak_min
        cluster.tail_min = adjusted.tail_min
        cluster.shape = adjusted.shape
        cluster.confidence = self._confidence_from_n(cluster.n_ok)
        cluster.last_updated_at = datetime.utcnow()

        await self.session.commit()

        logger.info(
            "Cluster updated: cluster_key=%s n_ok=%s confidence=%s",
            cluster.cluster_key,
            cluster.n_ok,
            cluster.confidence,
        )

    def _curve_from_experience(self, experience: MealExperience) -> ClusterCurve:
        base = base_curve_for_profile(experience.carb_profile)
        duration_min = base.duration_min

        delta = experience.delta_3h
        if delta is None:
            delta = experience.delta_2h if experience.delta_2h is not None else experience.delta_5h

        if delta is not None:
            if delta > 30:
                duration_min = int(duration_min * 1.1)
            elif delta < -20:
                duration_min = int(duration_min * 0.9)

        peak_ratio = base.peak_min / base.duration_min if base.duration_min else 0.5
        peak_min = max(30, int(duration_min * peak_ratio))
        tail_min = max(30, duration_min - peak_min)
        return ClusterCurve(duration_min=duration_min, peak_min=peak_min, tail_min=tail_min, shape="triangle")

    def _confidence_from_n(self, n_ok: int) -> str:
        if n_ok >= 10:
            return "high"
        if n_ok >= 5:
            return "medium"
        return "low"

    def _window_minutes_for_profile(self, carb_profile: Optional[str]) -> int:
        profile = (carb_profile or "med").lower()
        if profile == "fast":
            return 120
        if profile == "slow":
            return 300
        return 180

    def _resolve_meal_type(self, created_at: datetime, settings: UserSettings) -> str:
        hour = created_at.hour
        if settings and settings.schedule:
            breakfast = settings.schedule.breakfast_start_hour
            lunch = settings.schedule.lunch_start_hour
            dinner = settings.schedule.dinner_start_hour
        else:
            breakfast, lunch, dinner = 6, 12, 19

        if breakfast <= hour < lunch:
            return "breakfast"
        if lunch <= hour < dinner:
            return "lunch"
        return "dinner"

    @staticmethod
    def _extract_tags(notes: str) -> list[str]:
        if not notes:
            return []
        return [t.lower() for t in re.findall(r"#([\\w-]+)", notes)]

    @staticmethod
    def _ensure_aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _epoch_ms_to_dt(ms: int) -> datetime:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


async def fetch_cluster_for_event(
    session: AsyncSession,
    carb_profile: Optional[str],
    tags: Optional[Iterable[str]],
    carbs_g: float,
    protein_g: float,
    fat_g: float,
    fiber_g: float,
    user_id: Optional[str] = None,
) -> Optional[MealCluster]:
    tags_key = build_tags_key(tags)
    cluster_key = build_cluster_key(
        carb_profile,
        tags_key,
        carbs_g,
        protein_g,
        fat_g,
        fiber_g,
        user_id=user_id,
    )
    stmt = select(MealCluster).where(
        MealCluster.cluster_key == cluster_key,
        MealCluster.user_id == user_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def should_use_learned_curve(cluster: Optional[MealCluster], min_ok: int = 5) -> bool:
    if not cluster:
        return False
    return cluster.n_ok >= min_ok and cluster.confidence in {"medium", "high"}
