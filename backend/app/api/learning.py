from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.security import get_current_user
from app.models.meal_learning import MealCluster, MealExperience

router = APIRouter()


@router.get("/summary")
async def learning_summary(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    stmt = (
        select(
            MealExperience.window_status,
            func.count(MealExperience.id),
        )
        .where(MealExperience.user_id == current_user.username)
        .group_by(MealExperience.window_status)
    )
    rows = (await db.execute(stmt)).all()
    status_counts = {row[0]: row[1] for row in rows}
    total_events = sum(status_counts.values())

    clusters_active_stmt = select(func.count(MealCluster.id)).where(
        MealCluster.user_id == current_user.username,
        MealCluster.n_ok >= 5,
    )
    clusters_active = (await db.execute(clusters_active_stmt)).scalar_one()

    return {
        "total_events": total_events,
        "ok_events": status_counts.get("ok", 0),
        "discarded_events": status_counts.get("discarded", 0),
        "excluded_events": status_counts.get("excluded", 0),
        "clusters_active": clusters_active,
    }


@router.get("/clusters")
async def learning_clusters(
    min_ok: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    stmt = (
        select(MealCluster)
        .where(MealCluster.user_id == current_user.username)
        .where(MealCluster.n_ok >= min_ok)
        .order_by(MealCluster.last_updated_at.desc())
    )
    clusters = (await db.execute(stmt)).scalars().all()
    return [
        {
            "cluster_key": c.cluster_key,
            "carb_profile": c.carb_profile,
            "tags_key": c.tags_key,
            "centroid": {
                "carbs_g": c.centroid_carbs,
                "protein_g": c.centroid_protein,
                "fat_g": c.centroid_fat,
                "fiber_g": c.centroid_fiber,
            },
            "n_ok": c.n_ok,
            "n_discarded": c.n_discarded,
            "confidence": c.confidence,
            "curve": {
                "duration_min": c.absorption_duration_min,
                "peak_min": c.peak_min,
                "tail_min": c.tail_min,
                "shape": c.shape,
            },
            "last_updated_at": c.last_updated_at,
        }
        for c in clusters
    ]


@router.get("/clusters/{cluster_key}")
async def learning_cluster_detail(
    cluster_key: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    stmt = select(MealCluster).where(
        MealCluster.cluster_key == cluster_key,
        MealCluster.user_id == current_user.username,
    )
    cluster = (await db.execute(stmt)).scalar_one_or_none()
    if not cluster:
        return {"detail": "Cluster not found", "cluster": None}

    return {
        "cluster_key": cluster.cluster_key,
        "carb_profile": cluster.carb_profile,
        "tags_key": cluster.tags_key,
        "centroid": {
            "carbs_g": cluster.centroid_carbs,
            "protein_g": cluster.centroid_protein,
            "fat_g": cluster.centroid_fat,
            "fiber_g": cluster.centroid_fiber,
        },
        "n_ok": cluster.n_ok,
        "n_discarded": cluster.n_discarded,
        "confidence": cluster.confidence,
        "curve": {
            "duration_min": cluster.absorption_duration_min,
            "peak_min": cluster.peak_min,
            "tail_min": cluster.tail_min,
            "shape": cluster.shape,
        },
        "last_updated_at": cluster.last_updated_at,
    }


@router.get("/events")
async def learning_events(
    event_kind: str | None = None,
    window_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    stmt = select(MealExperience).where(MealExperience.user_id == current_user.username)
    if event_kind:
        stmt = stmt.where(MealExperience.event_kind == event_kind)
    if window_status:
        stmt = stmt.where(MealExperience.window_status == window_status)
    stmt = stmt.order_by(MealExperience.created_at.desc()).limit(limit)
    experiences = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": e.id,
            "treatment_id": e.treatment_id,
            "created_at": e.created_at,
            "meal_type": e.meal_type,
            "carbs_g": e.carbs_g,
            "protein_g": e.protein_g,
            "fat_g": e.fat_g,
            "fiber_g": e.fiber_g,
            "carb_profile": e.carb_profile,
            "event_kind": e.event_kind,
            "window_status": e.window_status,
            "discard_reason": e.discard_reason,
            "bg_start": e.bg_start,
            "bg_peak": e.bg_peak,
            "bg_min": e.bg_min,
            "bg_end_2h": e.bg_end_2h,
            "bg_end_3h": e.bg_end_3h,
            "bg_end_5h": e.bg_end_5h,
            "delta_2h": e.delta_2h,
            "delta_3h": e.delta_3h,
            "delta_5h": e.delta_5h,
            "score": e.score,
        }
        for e in experiences
    ]
