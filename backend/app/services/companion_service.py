from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.companion import CompanionEpisode, CompanionPreference
from app.models.settings import UserSettings
from app.models.treatment import Treatment
from app.services.iob import InsulinActionProfile, compute_iob
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config
from app.services.settings_service import get_user_settings_service
from app.utils.timezone import get_user_timezone

ACTIVE_STATUSES = ("open", "notified", "snoozed", "monitoring")
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def serialize_episode(row: CompanionEpisode) -> dict[str, Any]:
    context = row.context or {}
    return {
        "id": str(row.id),
        "kind": row.kind,
        "status": row.status,
        "severity": row.severity,
        "title": row.title,
        "message": row.message,
        "route": row.route,
        "context": context,
        "action_label": context.get("action_label") or "Revisar",
        "opened_at": _aware(row.opened_at),
        "updated_at": _aware(row.updated_at),
        "last_notified_at": _aware(row.last_notified_at),
        "acknowledged_at": _aware(row.acknowledged_at),
        "snoozed_until": _aware(row.snoozed_until),
    }


def _sustained_high_guidance(iob_u: float) -> tuple[str, str, dict[str, str]]:
    """Keep the high-glucose action consistent with the active-insulin advice."""
    if iob_u >= 0.5:
        return (
            f"Llevas varias lecturas altas y aún quedan aproximadamente {iob_u:.1f} U activas. "
            "No añadas ahora otra dosis de corrección: abre la tendencia y espera a comprobar "
            "el efecto para evitar solapamientos.",
            "#/forecast",
            {"action_label": "Ver tendencia", "correction_status": "wait_active_insulin"},
        )
    return (
        "La glucosa sigue alta y hay poca insulina activa. Revisa primero la tendencia, los "
        "hidratos pendientes y otras causas posibles; si quieres, valora una corrección en la "
        "calculadora, que aplicará tus parámetros e IOB.",
        "#/bolus",
        {"action_label": "Valorar corrección", "correction_status": "review_possible"},
    )


async def get_or_create_preferences(user_id: str, db: AsyncSession) -> CompanionPreference:
    pref = await db.get(CompanionPreference, user_id)
    if pref is None:
        pref = CompanionPreference(user_id=user_id)
        db.add(pref)
        await db.flush()
    return pref


def serialize_preferences(pref: CompanionPreference) -> dict[str, Any]:
    return {
        "enabled": pref.enabled,
        "mode": pref.mode,
        "quiet_hours_start": pref.quiet_hours_start,
        "quiet_hours_end": pref.quiet_hours_end,
        "repeat_critical_minutes": pref.repeat_critical_minutes,
        "repeat_high_minutes": pref.repeat_high_minutes,
    }


async def update_preferences(user_id: str, changes: dict[str, Any], db: AsyncSession) -> CompanionPreference:
    pref = await get_or_create_preferences(user_id, db)
    allowed = {
        "enabled", "mode", "quiet_hours_start", "quiet_hours_end",
        "repeat_critical_minutes", "repeat_high_minutes",
    }
    for key, value in changes.items():
        if key in allowed and value is not None:
            setattr(pref, key, value)
    pref.updated_at = _utcnow()
    await db.commit()
    await db.refresh(pref)
    return pref


async def list_active_episodes(user_id: str, db: AsyncSession) -> list[CompanionEpisode]:
    now = _utcnow()
    rows = (await db.execute(
        select(CompanionEpisode)
        .where(
            CompanionEpisode.user_id == user_id,
            CompanionEpisode.status.in_(ACTIVE_STATUSES),
        )
        .order_by(CompanionEpisode.updated_at.desc())
    )).scalars().all()
    visible: list[CompanionEpisode] = []
    changed = False
    for row in rows:
        expires_at = _aware(row.expires_at)
        if expires_at and expires_at <= now:
            row.status = "expired"
            row.resolved_at = now
            row.updated_at = now
            changed = True
            continue
        snoozed_until = _aware(row.snoozed_until)
        if row.status == "snoozed" and snoozed_until and snoozed_until <= now:
            row.status = "open"
            row.snoozed_until = None
            row.updated_at = now
            changed = True
        visible.append(row)
    if changed:
        await db.commit()
    visible.sort(key=lambda row: (SEVERITY_ORDER.get(row.severity, 9), -_aware(row.updated_at).timestamp()))
    return visible


async def get_episode_by_fingerprint(
    user_id: str,
    fingerprint: str,
    db: AsyncSession,
) -> Optional[CompanionEpisode]:
    return (await db.execute(
        select(CompanionEpisode).where(
            CompanionEpisode.user_id == user_id,
            CompanionEpisode.fingerprint == fingerprint,
        )
    )).scalar_one_or_none()


async def resolve_episode_by_fingerprint(
    user_id: str,
    fingerprint: str,
    db: AsyncSession,
) -> bool:
    row = await get_episode_by_fingerprint(user_id, fingerprint, db)
    if row is None:
        return False
    now = _utcnow()
    row.status = "resolved"
    row.resolved_at = now
    row.updated_at = now
    row.snoozed_until = None
    await db.commit()
    return True


async def resolve_superseded_meal_episodes(
    user_id: str,
    origin_id: str,
    current_episode_origin_id: str,
    db: AsyncSession,
) -> int:
    """Resolve older revisions while leaving the delivered revision active."""
    base_fingerprint = f"meal_detected:{origin_id}"
    current_fingerprint = f"meal_detected:{current_episode_origin_id}"
    rows = (await db.execute(
        select(CompanionEpisode).where(
            CompanionEpisode.user_id == user_id,
            CompanionEpisode.kind == "meal_detected",
            CompanionEpisode.status.in_(ACTIVE_STATUSES),
            CompanionEpisode.fingerprint != current_fingerprint,
            or_(
                CompanionEpisode.fingerprint == base_fingerprint,
                CompanionEpisode.fingerprint.startswith(
                    f"{base_fingerprint}:", autoescape=True
                ),
            ),
        )
    )).scalars().all()
    now = _utcnow()
    for row in rows:
        row.status = "resolved"
        row.resolved_at = now
        row.updated_at = now
        row.snoozed_until = None
    await db.flush()
    return len(rows)


async def _upsert_episode(
    user_id: str,
    fingerprint: str,
    kind: str,
    severity: str,
    title: str,
    message: str,
    route: str,
    context: dict[str, Any],
    db: AsyncSession,
    *,
    expires_at: Optional[datetime] = None,
) -> CompanionEpisode:
    now = _utcnow()
    row = (await db.execute(
        select(CompanionEpisode).where(
            CompanionEpisode.user_id == user_id,
            CompanionEpisode.fingerprint == fingerprint,
        )
    )).scalar_one_or_none()
    if row is None:
        row = CompanionEpisode(
            user_id=user_id, fingerprint=fingerprint, kind=kind, status="open",
            severity=severity, title=title, message=message, route=route,
            context=context, opened_at=now, updated_at=now, expires_at=expires_at,
        )
        db.add(row)
        return row

    row.title = title
    row.message = message
    row.severity = severity
    row.route = route
    row.context = context
    row.updated_at = now
    row.expires_at = expires_at
    if row.status in ("resolved", "expired"):
        row.status = "open"
        row.opened_at = now
        row.resolved_at = None
        row.acknowledged_at = None
        row.snoozed_until = None
        row.last_notified_at = None
    return row


async def record_meal_episode(
    user_id: str,
    origin_id: str,
    message: str,
    context: dict[str, Any],
    db: AsyncSession,
) -> CompanionEpisode:
    now = _utcnow()
    row = await _upsert_episode(
        user_id,
        f"meal_detected:{origin_id}",
        "meal_detected",
        "medium",
        "Comida pendiente de confirmar",
        message,
        "#/bolus",
        context,
        db,
        expires_at=now + timedelta(hours=6),
    )
    row.status = "monitoring"
    row.acknowledged_at = now
    row.last_notified_at = now
    row.updated_at = now
    await db.commit()
    return row


async def _resolve_absent(user_id: str, observed: set[str], db: AsyncSession) -> None:
    now = _utcnow()
    rows = (await db.execute(
        select(CompanionEpisode).where(
            CompanionEpisode.user_id == user_id,
            CompanionEpisode.status.in_((*ACTIVE_STATUSES, "dismissed")),
        )
    )).scalars().all()
    for row in rows:
        if row.fingerprint not in observed and row.kind in {
            "hypo_risk", "sustained_high", "rapid_rise", "rapid_drop",
            "postmeal_high", "data_quality",
        }:
            row.status = "resolved"
            row.resolved_at = now
            row.updated_at = now


def _estimated_cob(rows: Iterable[Treatment], now: datetime) -> float:
    total = 0.0
    for row in rows:
        carbs = float(getattr(row, "carbs", 0) or 0)
        if carbs <= 0:
            continue
        created = _aware(getattr(row, "created_at", None))
        if created is None:
            continue
        age_min = max(0.0, (now - created).total_seconds() / 60)
        duration = float(getattr(row, "duration", 0) or 0) or 180.0
        total += carbs * max(0.0, 1.0 - age_min / max(duration, 60.0))
    return round(total, 1)


async def evaluate_companion_state(user_id: str, db: AsyncSession) -> dict[str, Any]:
    now = _utcnow()
    pref = await get_or_create_preferences(user_id, db)
    observed: set[str] = set()
    snapshot: dict[str, Any] = {
        "generated_at": now,
        "state": "unavailable",
        "current_bg": None,
        "trend": None,
        "slope_mgdl_min": None,
        "predicted_20m": None,
        "iob_u": None,
        "cob_g": None,
        "data_age_min": None,
        "source": "nightscout",
    }
    if not pref.enabled:
        await _resolve_absent(user_id, observed, db)
        await db.commit()
        return {"snapshot": snapshot, "episodes": [], "preferences": serialize_preferences(pref)}

    ns_config = await get_ns_config(db, user_id)
    if not ns_config or not ns_config.enabled or not ns_config.url:
        fingerprint = "data_quality:nightscout_unavailable"
        observed.add(fingerprint)
        await _upsert_episode(
            user_id, fingerprint, "data_quality", "info", "Compañero sin datos de glucosa",
            "No puedo vigilar tendencias hasta recuperar la conexión con Nightscout.",
            "#/nightscout-settings", {"reason": "not_configured"}, db,
        )
    else:
        entries = []
        ns_treatments: list[Any] = []
        client = NightscoutClient(ns_config.url, ns_config.api_secret, timeout_seconds=6)
        try:
            entries = await client.get_sgv_range(now - timedelta(minutes=60), now, count=30)
            try:
                ns_treatments = await client.get_recent_treatments(hours=6, limit=500)
            except Exception:
                # Glucose monitoring remains useful, but insulin context will be
                # labelled from the local mirror only.
                ns_treatments = []
        except Exception as exc:
            fingerprint = "data_quality:nightscout_unavailable"
            observed.add(fingerprint)
            await _upsert_episode(
                user_id, fingerprint, "data_quality", "info", "Datos de glucosa temporalmente no disponibles",
                "Mantengo el seguimiento en pausa hasta que Nightscout vuelva a responder.",
                "#/status", {"reason": type(exc).__name__}, db,
            )
        finally:
            await client.aclose()

        if entries:
            entries = sorted(entries, key=lambda item: item.date)
            latest = entries[-1]
            latest_at = datetime.fromtimestamp(latest.date / 1000, timezone.utc)
            age_min = max(0.0, (now - latest_at).total_seconds() / 60)
            current_bg = int(latest.sgv)
            usable = [item for item in entries if latest.date - item.date <= 30 * 60 * 1000]
            slope = 0.0
            if len(usable) >= 2:
                elapsed = (usable[-1].date - usable[0].date) / 60000.0
                if elapsed >= 5:
                    slope = (usable[-1].sgv - usable[0].sgv) / elapsed
            predicted = round(current_bg + slope * 20)
            snapshot.update({
                "state": "stable", "current_bg": current_bg,
                "trend": latest.direction, "slope_mgdl_min": round(slope, 2),
                "predicted_20m": predicted, "data_age_min": round(age_min, 1),
            })

            settings_row = await get_user_settings_service(user_id, db)
            raw_settings = (settings_row or {}).get("settings") or {}
            user_settings = UserSettings.migrate(raw_settings)
            cutoff = now - timedelta(hours=max(6.0, user_settings.iob.dia_hours + 1))
            treatments = (await db.execute(
                select(Treatment).where(
                    Treatment.user_id == user_id,
                    Treatment.created_at >= cutoff.replace(tzinfo=None),
                ).order_by(Treatment.created_at.desc())
            )).scalars().all()
            raw_boluses = []
            for row in [*treatments, *ns_treatments]:
                units = float(getattr(row, "insulin", 0) or 0)
                created = _aware(getattr(row, "created_at", None))
                if units > 0 and created:
                    raw_boluses.append((created, units))
            # The NAS mirror and Nightscout commonly contain the same bolus.
            deduped_boluses = {
                (round(created.timestamp() / 300), round(units, 1)): (created, units)
                for created, units in raw_boluses
            }
            boluses = [
                {"ts": created.isoformat(), "units": units}
                for created, units in deduped_boluses.values()
            ]
            profile = InsulinActionProfile(
                dia_hours=user_settings.iob.dia_hours,
                curve=user_settings.iob.curve,
                peak_minutes=user_settings.iob.peak_minutes,
            )
            iob = round(compute_iob(now, boluses, profile), 2)
            all_treatments = [*treatments, *ns_treatments]
            cob = _estimated_cob(all_treatments, now)
            snapshot.update({
                "iob_u": iob,
                "cob_g": cob,
                "insulin_context_source": "nightscout+local" if ns_treatments else "local_only",
            })
            prior_hypo = (await db.execute(
                select(CompanionEpisode).where(
                    CompanionEpisode.user_id == user_id,
                    CompanionEpisode.kind == "hypo_risk",
                    CompanionEpisode.status.in_((*ACTIVE_STATUSES, "dismissed")),
                )
            )).scalars().first()

            if age_min > 15:
                fingerprint = "data_quality:stale_cgm"
                observed.add(fingerprint)
                await _upsert_episode(
                    user_id, fingerprint, "data_quality", "info", "Lectura de glucosa retrasada",
                    f"La última lectura tiene {round(age_min)} minutos; no sacaré conclusiones ni sugeriré correcciones.",
                    "#/status", {"age_min": round(age_min, 1)}, db,
                )
            else:
                low_risk = current_bg <= 75 or predicted < 70
                sustained_high = (
                    current_bg >= 180 and len(usable) >= 3
                    and sum(1 for item in usable[-4:] if item.sgv >= 180) >= 3
                )
                if low_risk:
                    fingerprint = "hypo_risk:active"
                    observed.add(fingerprint)
                    snapshot["state"] = "needs_attention"
                    await _upsert_episode(
                        user_id, fingerprint, "hypo_risk", "critical", "Riesgo de hipoglucemia",
                        "Comprueba la lectura y sigue tu pauta de rescate con hidratos de acción rápida. Te pediré revisar de nuevo la recuperación.",
                        "#/forecast", {"bg": current_bg, "predicted_20m": predicted, "iob_u": iob}, db,
                    )
                elif prior_hypo is not None and current_bg >= 80 and slope > -0.5:
                    fingerprint = f"hypo_recovery:{prior_hypo.id}"
                    observed.add(fingerprint)
                    snapshot["state"] = "watching"
                    await _upsert_episode(
                        user_id, fingerprint, "hypo_recovery", "high", "Recuperación de la hipoglucemia",
                        "La glucosa ha remontado. Comprueba de nuevo en unos 15 minutos para confirmar que la recuperación se mantiene y evitar sobretratar.",
                        "#/forecast", {"bg": current_bg, "slope": round(slope, 2), "iob_u": iob}, db,
                        expires_at=now + timedelta(minutes=45),
                    )
                elif sustained_high:
                    fingerprint = "sustained_high:active"
                    observed.add(fingerprint)
                    snapshot["state"] = "needs_attention"
                    message, route, action_context = _sustained_high_guidance(iob)
                    await _upsert_episode(
                        user_id, fingerprint, "sustained_high", "high", "Glucosa alta mantenida",
                        message, route, {
                            "bg": current_bg,
                            "slope": round(slope, 2),
                            "iob_u": iob,
                            "cob_g": cob,
                            **action_context,
                        }, db,
                    )
                elif slope >= 1.5 and predicted >= 160:
                    fingerprint = "rapid_rise:active"
                    observed.add(fingerprint)
                    snapshot["state"] = "watching"
                    await _upsert_episode(
                        user_id, fingerprint, "rapid_rise", "medium", "Subida rápida",
                        "La curva está subiendo. Revisa comida, estrés y la insulina activa; no propongo una dosis automática.",
                        "#/forecast", {"bg": current_bg, "slope": round(slope, 2), "iob_u": iob}, db,
                    )
                elif slope <= -1.5 and predicted <= 90:
                    fingerprint = "rapid_drop:active"
                    observed.add(fingerprint)
                    snapshot["state"] = "watching"
                    await _upsert_episode(
                        user_id, fingerprint, "rapid_drop", "high", "Bajada rápida",
                        "La glucosa desciende con rapidez. Comprueba de nuevo pronto y actúa según tu pauta si aparecen síntomas o entras en bajo.",
                        "#/forecast", {"bg": current_bg, "slope": round(slope, 2), "iob_u": iob}, db,
                    )

                recent_meals_by_key = {}
                for row in all_treatments:
                    carbs = float(getattr(row, "carbs", 0) or 0)
                    created = _aware(getattr(row, "created_at", None))
                    if carbs >= 15 and created:
                        recent_meals_by_key[(round(created.timestamp() / 300), round(carbs))] = row
                recent_meals = sorted(
                    recent_meals_by_key.values(),
                    key=lambda row: _aware(getattr(row, "created_at", None)),
                    reverse=True,
                )
                if recent_meals and current_bg >= 180:
                    meal_age = (now - _aware(recent_meals[0].created_at)).total_seconds() / 60
                    if 90 <= meal_age <= 240:
                        meal_id = getattr(recent_meals[0], "id", None) or round(_aware(recent_meals[0].created_at).timestamp())
                        fingerprint = f"postmeal_high:{meal_id}"
                        observed.add(fingerprint)
                        await _upsert_episode(
                            user_id, fingerprint, "postmeal_high", "high", "Revisión después de comer",
                            "La subida continúa tras la comida. Revisa absorción, cantidad estimada e insulina activa antes de decidir cualquier corrección.",
                            "#/forecast", {"bg": current_bg, "meal_age_min": round(meal_age), "iob_u": iob, "cob_g": cob}, db,
                            expires_at=_aware(recent_meals[0].created_at) + timedelta(hours=5),
                        )

    await _resolve_absent(user_id, observed, db)
    await db.commit()
    episodes = await list_active_episodes(user_id, db)
    return {
        "snapshot": snapshot,
        "episodes": [serialize_episode(row) for row in episodes],
        "preferences": serialize_preferences(pref),
    }


async def act_on_episode(
    user_id: str,
    episode_id: UUID,
    action: str,
    db: AsyncSession,
    *,
    snooze_minutes: int = 30,
) -> CompanionEpisode:
    row = (await db.execute(
        select(CompanionEpisode).where(
            CompanionEpisode.id == episode_id,
            CompanionEpisode.user_id == user_id,
        )
    )).scalar_one_or_none()
    if row is None:
        raise LookupError("episode_not_found")
    now = _utcnow()
    if action == "acknowledge":
        row.status = "monitoring"
        row.acknowledged_at = now
        row.snoozed_until = None
    elif action == "snooze":
        row.status = "snoozed"
        row.acknowledged_at = now
        row.snoozed_until = now + timedelta(minutes=snooze_minutes)
    elif action == "dismiss":
        row.status = "dismissed"
        row.acknowledged_at = now
        row.snoozed_until = None
    elif action == "resolve":
        row.status = "resolved"
        row.resolved_at = now
        row.snoozed_until = None
    else:
        raise ValueError("invalid_action")
    row.updated_at = now
    await db.commit()
    await db.refresh(row)
    return row


def _inside_quiet_hours(pref: CompanionPreference, now: datetime) -> bool:
    try:
        tz = get_user_timezone(pref.user_id)
        local_now = now.astimezone(tz).time()
        start = time.fromisoformat(pref.quiet_hours_start)
        end = time.fromisoformat(pref.quiet_hours_end)
        return start <= local_now < end if start < end else (local_now >= start or local_now < end)
    except Exception:
        return False


async def episodes_due_for_notification(user_id: str, db: AsyncSession) -> list[CompanionEpisode]:
    now = _utcnow()
    pref = await get_or_create_preferences(user_id, db)
    if not pref.enabled:
        return []
    quiet = _inside_quiet_hours(pref, now)
    rows = await list_active_episodes(user_id, db)
    due: list[CompanionEpisode] = []
    for row in rows:
        if row.status in ("snoozed", "monitoring"):
            continue
        if quiet and row.severity != "critical":
            continue
        if pref.mode == "quiet" and row.severity != "critical":
            continue
        if pref.mode == "balanced" and row.severity not in ("critical", "high"):
            continue
        last = _aware(row.last_notified_at)
        repeat = pref.repeat_critical_minutes if row.severity == "critical" else pref.repeat_high_minutes
        if last is None or (now - last) >= timedelta(minutes=repeat):
            due.append(row)
    return due


async def mark_episode_notified(row: CompanionEpisode, db: AsyncSession) -> None:
    now = _utcnow()
    row.status = "notified"
    row.last_notified_at = now
    row.updated_at = now
    await db.commit()


def summarize_rejection_reasons(reasons: Iterable[str]) -> dict[str, int]:
    """Shared deterministic helper, also useful in analysis tests/UI summaries."""
    return dict(Counter(reasons))
