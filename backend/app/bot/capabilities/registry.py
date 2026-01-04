from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from app import jobs_state
from app.bot import tools as bot_tools
from app.bot import proactive as bot_proactive

from app.core.scheduler import get_scheduler
from app.services import bolus_engine, bolus_split
from app.services import iob as iob_service
from app.services import autosens_service
from app.services import export_service
from app.services import learning_service
from app.services import nightscout_client
from app.services import nightscout_secrets_service
from app.services import settings_service
from app.services import basal_repo
from app.services.math import curves
from app.services.basal_engine import scan_night_service
from app.core.datastore import UserStore
from app.services.store import DataStore


class Permission(str, Enum):
    public_read = "public_read"
    user_write = "user_write"
    admin_only = "admin_only"


def _fn_ref(fn: Optional[Callable[..., Any]]) -> Optional[str]:
    if not fn:
        return None
    try:
        return f"{fn.__module__}.{fn.__qualname__}"
    except Exception:
        return repr(fn)


def _safe_call(callable_obj: Optional[Callable[[], Any]]) -> Optional[Any]:
    if not callable_obj:
        return None
    try:
        return callable_obj()
    except Exception:
        # Swallow errors for safe introspection
        return None


@dataclass
class DataSourceDef:
    id: str
    description: str
    fields: list[str] = field(default_factory=list)
    sensitivity: str = "protected"
    fetch_fn: Optional[Callable[..., Awaitable[Any] | Any]] = None

    def to_safe_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fetch_fn"] = _fn_ref(self.fetch_fn)
        return payload


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | str
    fn: Optional[Callable[..., Awaitable[Any] | Any]] = None
    permission: Permission = Permission.public_read

    def to_safe_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fn"] = _fn_ref(self.fn)
        payload["permission"] = self.permission.value
        return payload


@dataclass
class JobDef:
    id: str
    description: str
    next_run_fn: Optional[Callable[[], Any]] = None
    last_run_state_fn: Optional[Callable[[], Any]] = None
    run_now_fn: Optional[Callable[..., Awaitable[Any] | Any]] = None
    permission: Permission = Permission.admin_only

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "description": self.description,
            "next_run": _safe_call(self.next_run_fn),
            "last_state": _safe_call(self.last_run_state_fn),
            "run_now_fn": _fn_ref(self.run_now_fn),
            "permission": self.permission.value,
        }
        return payload


@dataclass
class Registry:
    data_sources: list[DataSourceDef] = field(default_factory=list)
    tools: list[ToolDef] = field(default_factory=list)
    jobs: list[JobDef] = field(default_factory=list)

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "data_sources": [ds.to_safe_dict() for ds in self.data_sources],
            "tools": [tool.to_safe_dict() for tool in self.tools],
            "jobs": [job.to_safe_dict() for job in self.jobs],
        }


def _scheduler_next_run(job_id: str) -> Optional[str]:
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id) if scheduler else None
    if not job or not job.next_run_time:
        return None
    return job.next_run_time.isoformat()


def _job_state_lookup(job_key: str) -> Callable[[], Any]:
    return lambda: jobs_state.get_all_states().get(job_key)


def _build_data_sources() -> list[DataSourceDef]:
    return [
        DataSourceDef(
            id="nightscout_current",
            description="Lectura actual y tendencia de glucosa desde Nightscout.",
            fields=["sgv", "direction", "delta", "timestamp"],
            sensitivity="protected",
            fetch_fn=nightscout_client.NightscoutClient.get_latest_sgv,
        ),
        DataSourceDef(
            id="nightscout_history",
            description="Historial de glucosa y tratamientos Nightscout.",
            fields=["sgv_history", "treatments", "profile"],
            sensitivity="protected",
            fetch_fn=nightscout_client.NightscoutClient.get_sgv_range,
        ),
        DataSourceDef(
            id="user_settings_store",
            description="Configuración del usuario (objetivos, ratios, Nightscout) almacenada en DataStore.",
            fields=["targets", "cr", "cf", "nightscout", "safety_limits"],
            sensitivity="private",
            fetch_fn=DataStore.load_settings,
        ),
        DataSourceDef(
            id="db_repositories",
            description="Repositorios y servicios persistentes (basal_repo, auth_repo, export_service, learning_service).",
            fields=["basal_dose", "basal_night_summary", "auth_users", "learning_outcomes"],
            sensitivity="private",
            fetch_fn=basal_repo.get_latest_basal_dose,
        ),
        DataSourceDef(
            id="math_engine",
            description="Motor matemático para bolus/correction/dual/isf/iob y curvas.",
            fields=["bolus_recommendation", "corrections", "dual_wave", "isf_curve", "iob_curve"],
            sensitivity="public",
            fetch_fn=bolus_engine.calculate_bolus_v2,
        ),
        DataSourceDef(
            id="autosens",
            description="Autosens y análisis de sensibilidad basada en datos recientes.",
            fields=["autosens_ratio", "confidence", "lookback_hours"],
            sensitivity="private",
            fetch_fn=getattr(autosens_service.AutosensService, "calculate_autosens", None),
        ),
        DataSourceDef(
            id="nightscout_secrets",
            description="Credenciales Nightscout persistidas (hash/secret) por usuario.",
            fields=["url", "token", "api_secret"],
            sensitivity="admin_only",
            fetch_fn=nightscout_secrets_service.get_ns_config,
        ),
        DataSourceDef(
            id="export_service",
            description="Exportación agregada de datos del usuario (auditoría/backup).",
            fields=["tables", "counts", "export_date"],
            sensitivity="admin_only",
            fetch_fn=export_service.export_all_user_data,
        ),
        DataSourceDef(
            id="user_store",
            description="Registro de usuarios en archivo users.json para modo sin DB.",
            fields=["username", "role", "needs_password_change"],
            sensitivity="admin_only",
            fetch_fn=UserStore.get_all_users,
        ),
    ]


def _build_tools() -> list[ToolDef]:
    from app.bot.service import fetch_history_context
    return [
        ToolDef(
            name="get_status_context",
            description="Contexto actual de glucosa, tendencia, IOB y COB.",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {"bg_mgdl": {"type": "number"}}},
            fn=bot_tools.get_status_context,
            permission=Permission.public_read,
        ),
        ToolDef(
            name="calculate_bolus",
            description="Calcula bolo recomendado para comida con ajustes de seguridad.",
            input_schema={"type": "object", "properties": {"carbs": {"type": "number"}}},
            output_schema={"type": "object", "properties": {"units": {"type": "number"}}},
            fn=bot_tools.calculate_bolus,
            permission=Permission.user_write,
        ),
        ToolDef(
            name="calculate_correction",
            description="Sugiere corrección a objetivo configurable.",
            input_schema={"type": "object", "properties": {"target_bg": {"type": "number"}}},
            output_schema={"type": "object", "properties": {"units": {"type": "number"}}},
            fn=bot_tools.calculate_correction,
            permission=Permission.public_read,
        ),
        ToolDef(
            name="simulate_whatif",
            description="Simulación rápida de carbohidratos sin bolo usando ForecastEngine.",
            input_schema={"type": "object", "properties": {"carbs": {"type": "number"}}},
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
            fn=bot_tools.simulate_whatif,
            permission=Permission.public_read,
        ),
        ToolDef(
            name="get_nightscout_stats",
            description="Estadísticas simples Nightscout (TIR, promedio, alertas).",
            input_schema={"type": "object", "properties": {"range_hours": {"type": "integer"}}},
            output_schema={"type": "object", "properties": {"avg_bg": {"type": "number"}}},
            fn=bot_tools.get_nightscout_stats,
            permission=Permission.public_read,
        ),
        ToolDef(
            name="set_temp_mode",
            description="Define modo temporal sport/sick/normal en estado local.",
            input_schema={"type": "object", "properties": {"mode": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"mode": {"type": "string"}, "expires_at": {"type": "string"}}},
            fn=bot_tools.set_temp_mode,
            permission=Permission.user_write,
        ),
        ToolDef(
            name="add_treatment",
            description="Registrar tratamiento manual (carbos/insulina).",
            input_schema={"type": "object", "properties": {"carbs": {"type": "number"}, "insulin": {"type": "number"}, "fat": {"type": "number"}, "protein": {"type": "number"}, "notes": {"type": "string"}}},
            output_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "treatment_id": {"type": "string"},
                    "insulin": {"type": "number"},
                    "carbs": {"type": "number"},
                    "ns_uploaded": {"type": "boolean"},
                    "ns_error": {"type": "string"},
                    "injection_site": {"type": "object", "description": "Rotación de zona sugerida"},
                },
            },
            fn=bot_tools.add_treatment,
            permission=Permission.user_write,
        ),
        ToolDef(
            name="save_favorite_food",
            description="Guardar comida en favoritos con perfil nutricional.",
            input_schema={"type": "object", "properties": {"name": {"type": "string"}, "carbs": {"type": "number"}, "fat": {"type": "number"}, "protein": {"type": "number"}, "notes": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}, "favorite": {"type": "object"}}},
            fn=bot_tools.save_favorite_food,
            permission=Permission.user_write,
        ),
        ToolDef(
            name="get_last_injection_site",
            description="Consultar dónde se realizó la última inyección. Útil para recordar el sitio previo.",
            input_schema={"type": "object", "properties": {"plan": {"type": "string", "enum": ["rapid", "basal"]}}},
            output_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            fn=bot_tools.get_last_injection_site,
            permission=Permission.public_read,
        ),
        ToolDef(
            name="search_food",

            description="Buscar comida en favoritos por nombre.",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"found": {"type": "boolean"}, "items": {"type": "array"}}},
            fn=bot_tools.search_food,
            permission=Permission.public_read,
        ),
        ToolDef(
            name="start_restaurant_session",
            description="Inicia sesión modo restaurante (comida compleja).",
            input_schema={"type": "object", "properties": {"expected_carbs": {"type": "number"}, "expected_fat": {"type": "number"}, "expected_protein": {"type": "number"}, "notes": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}, "session_id": {"type": "string"}}},
            fn=bot_tools.start_restaurant_session,
            permission=Permission.user_write,
        ),
        ToolDef(
            name="add_plate_to_session",
            description="Añade plato a la sesión restaurante activa.",
            input_schema={"type": "object", "properties": {"session_id": {"type": "string"}, "carbs": {"type": "number"}, "fat": {"type": "number"}, "protein": {"type": "number"}, "name": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}, "summary": {"type": "string"}}},
            fn=bot_tools.add_plate_to_session,
            permission=Permission.user_write,
        ),
        ToolDef(
            name="end_restaurant_session",
            description="Cierra sesión restaurante y valida desviación final.",
            input_schema={"type": "object", "properties": {"session_id": {"type": "string"}, "outcome_score": {"type": "integer"}}},
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}, "summary": {"type": "string"}}},
            fn=bot_tools.end_restaurant_session,
            permission=Permission.user_write,
        ),
        ToolDef(
            name="get_history_context",
            description="Resumen de historial reciente usado por el bot (texto).",
            input_schema={"type": "object", "properties": {"hours": {"type": "integer"}}},
            output_schema={"type": "string"},
            fn=fetch_history_context,
            permission=Permission.public_read,
        ),
        ToolDef(
            name="bolus_split_math",
            description="Motor de cálculo de bolos extendidos/dual (referencia).",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            fn=bolus_split.split_bolus if hasattr(bolus_split, "split_bolus") else None,
            permission=Permission.public_read,
        ),
        ToolDef(
            name="configure_basal_reminder",
            description="Configura el recordatorio proactivo de basal.",
            input_schema={"type": "object", "properties": {"enabled": {"type": "boolean"}, "time": {"type": "string", "description": "HH:MM"}, "units": {"type": "number"}}},
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}, "enabled": {"type": "boolean"}, "time_local": {"type": "string"}}},
            fn=bot_tools.configure_basal_reminder,
            permission=Permission.user_write,
        ),
    ]


def _build_jobs() -> list[JobDef]:
    from app.bot.service import run_glucose_monitor_job
    return [
        JobDef(
            id="glucose_monitor",
            description="Monitoreo guardian de glucosa y alertas Telegram.",
            next_run_fn=lambda: _scheduler_next_run("guardian_check"),
            last_run_state_fn=_job_state_lookup("glucose_monitor"),
            run_now_fn=run_glucose_monitor_job,
        ),
        JobDef(
            id="premeal",
            description="Empuja recordatorio previo a comida cuando BG sube.",
            next_run_fn=lambda: _scheduler_next_run("premeal_nudge"),
            last_run_state_fn=_job_state_lookup("premeal"),
            run_now_fn=lambda: bot_proactive.premeal_nudge(trigger="manual"),
        ),
        JobDef(
            id="basal",
            description="Recordatorio de basal diaria.",
            next_run_fn=lambda: _scheduler_next_run("basal_reminder"),
            last_run_state_fn=_job_state_lookup("basal"),
            run_now_fn=bot_proactive.basal_reminder,
        ),
        JobDef(
            id="morning_summary",
            description="Resumen de glucosa nocturna.",
            next_run_fn=lambda: _scheduler_next_run("morning_summary"),
            last_run_state_fn=_job_state_lookup("morning_summary"),
            run_now_fn=bot_proactive.morning_summary,
        ),
        JobDef(
            id="learning_eval",
            description="Evaluación periódica de outcomes de comidas (LearningService).",
            next_run_fn=lambda: _scheduler_next_run("learning_eval"),
            last_run_state_fn=_job_state_lookup("learning_eval"),
            run_now_fn=learning_service.LearningService.evaluate_pending_outcomes if hasattr(learning_service, "LearningService") else None,
        ),
        JobDef(
            id="auto_night_scan",
            description="Escaneo nocturno automático para detectar hipos y minimos.",
            next_run_fn=lambda: _scheduler_next_run("auto_night_scan"),
            last_run_state_fn=_job_state_lookup("auto_night_scan"),
            run_now_fn=scan_night_service,
        ),
        JobDef(
            id="data_cleanup",
            description="Depuración de datos antiguos (>90 días).",
            next_run_fn=lambda: _scheduler_next_run("data_cleanup"),
            last_run_state_fn=_job_state_lookup("data_cleanup"),
            run_now_fn=None,
        ),
        JobDef(
            id="combo_followup",
            description="Seguimiento de bolos extendidos para feedback.",
            next_run_fn=lambda: _scheduler_next_run("combo_followup"),
            last_run_state_fn=_job_state_lookup("combo_followup"),
            run_now_fn=bot_proactive.combo_followup,
        ),
        JobDef(
            id="trend_alert",
            description="Alertas de tendencia rápida de glucosa.",
            next_run_fn=lambda: _scheduler_next_run("trend_alert"),
            last_run_state_fn=_job_state_lookup("trend_alert"),
            run_now_fn=lambda: bot_proactive.trend_alert(trigger="manual"),
        ),
        JobDef(
            id="app_notifications",
            description="Chequeo periódico de notificaciones App (Sugerencias, Impacto, etc).",
            next_run_fn=lambda: _scheduler_next_run("app_notifications"),
            last_run_state_fn=_job_state_lookup("app_notifications"),
            run_now_fn=lambda: bot_proactive.check_app_notifications(trigger="manual"),
        ),
    ]


def build_registry() -> Registry:
    registry = Registry()
    registry.data_sources = _build_data_sources()
    registry.tools = _build_tools()
    registry.jobs = _build_jobs()
    return registry
