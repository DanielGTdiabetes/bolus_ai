from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

from app.bot.state import cooldowns, health
from app.core import config
from app.core.settings import get_settings
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient
from app.services.iob import compute_iob_from_sources
from app.services.bolus import recommend_bolus, BolusRequestData
from app.services.basal_repo import get_latest_basal_dose
from app.services.nightscout_secrets_service import get_ns_config
from app.core.db import get_engine, AsyncSession

logger = logging.getLogger(__name__)

COOLDOWN_MINUTES = {
    "basal": 45,
    "premeal": 60,
    "combo": 45,
    "morning": 720,
}


async def _get_chat_id() -> Optional[int]:
    return config.get_allowed_telegram_user_id()


async def _send(bot, chat_id: int, text: str, *, log_context: str, **kwargs):
    from app.bot.service import bot_send

    await bot_send(chat_id=chat_id, text=text, bot=bot, log_context=log_context, **kwargs)


async def _get_ns_client(user_id: str) -> Optional[NightscoutClient]:
    engine = get_engine()
    if not engine:
        return None
    async with AsyncSession(engine) as session:
        cfg = await get_ns_config(session, user_id)
        if not cfg or not cfg.url:
            return None
        return NightscoutClient(cfg.url, cfg.api_secret, timeout_seconds=8)


async def basal_reminder(bot) -> None:
    if bot is None:
        return

    # TODO: map Telegram chat_id to username/user_id once multi-user support exists.
    user_id = "admin"

    try:
        chat_id = await _get_chat_id()
        if not chat_id or not cooldowns.is_ready("basal", COOLDOWN_MINUTES["basal"] * 60):
            return

        engine = get_engine()
        if not engine:
            logger.info("Basal reminder running without database engine; using fallback storage.")

        latest = await get_latest_basal_dose(user_id=user_id)
        if latest:
            age_hours = (datetime.utcnow() - latest.created_at).total_seconds() / 3600
            if age_hours < 18:
                return
        cooldowns.touch("basal")
        keyboard = [
            [{"text": "✅ Sí, ya puesta", "callback_data": "basal_ack_yes"}],
            [{"text": "⏰ En 15 min", "callback_data": "basal_ack_later"}],
            [{"text": "🙈 Ignorar", "callback_data": "ignore"}],
        ]
        await _send(
            bot,
            chat_id,
            "⏰ ¿Basal diaria puesta? Marca 'Sí' para registrar.",
            log_context="proactive_basal",
            reply_markup={"inline_keyboard": keyboard},
        )
    except Exception as exc:
        logger.error("Basal reminder failed: %s", exc)
        try:
            health.set_error(f"Basal reminder failed: {exc}")
        except Exception:
            logger.debug("Unable to record bot health error for basal reminder.")


async def premeal_nudge(bot) -> None:
    if bot is None:
        return
    chat_id = await _get_chat_id()
    if not chat_id or not cooldowns.is_ready("premeal", COOLDOWN_MINUTES["premeal"] * 60):
        return
    user_id = "admin"
    ns_client = await _get_ns_client(user_id)
    if not ns_client:
        return
    try:
        sgv = await ns_client.get_latest_sgv()
    except Exception:
        await ns_client.aclose()
        return
    finally:
        try:
            await ns_client.aclose()
        except Exception:
            pass
    # Simple heuristic: rising and >140
    if sgv.sgv < 140 or (sgv.delta or 0) < 2:
        return
    cooldowns.touch("premeal")
    await _send(
        bot,
        chat_id,
        f"🍽️ Parece que se acerca comida (BG {sgv.sgv} {sgv.direction}). ¿Anotamos carbohidratos?",
        log_context="proactive_premeal",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "✅ Registrar", "callback_data": "premeal_add"},
                    {"text": "⏳ Luego", "callback_data": "ignore"},
                ]
            ]
        },
    )


async def combo_followup(bot) -> None:
    if bot is None:
        return
    chat_id = await _get_chat_id()
    if not chat_id or not cooldowns.is_ready("combo", COOLDOWN_MINUTES["combo"] * 60):
        return
    settings = get_settings()
    store = DataStore(Path(settings.data.data_dir))
    events = store.load_events()
    now = datetime.utcnow()
    pending = [e for e in events if e.get("type") == "combo" and datetime.fromisoformat(e["notify_at"]) <= now]
    if not pending:
        return
    cooldowns.touch("combo")
    await _send(
        bot,
        chat_id,
        "⏳ Seguimiento de bolo extendido. ¿Cómo va la glucosa? Responde con valor o usa /start.",
        log_context="proactive_combo",
    )


async def morning_summary(bot) -> None:
    if bot is None:
        return
    chat_id = await _get_chat_id()
    if not chat_id or not cooldowns.is_ready("morning", COOLDOWN_MINUTES["morning"] * 60):
        return
    user_id = "admin"
    ns_client = await _get_ns_client(user_id)
    if not ns_client:
        return
    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=8)
        entries = await ns_client.get_sgv_range(start, now, count=120)
        await ns_client.aclose()
    except Exception:
        return
    if not entries:
        return
    values = [e.sgv for e in entries if e.sgv is not None]
    tir = sum(1 for v in values if 70 <= v <= 180) / len(values) * 100 if values else 0
    lows = sum(1 for v in values if v < 70)
    msg = f"🌅 Resumen noche: TIR {tir:.0f}% | Hipos {lows} | Último {values[-1] if values else '?'} mg/dL"
    cooldowns.touch("morning")
    await _send(bot, chat_id, msg, log_context="proactive_morning")


async def light_guardian(bot) -> None:
    """
    Wrapper around existing glucose monitor job using same bot instance.
    """
    try:
        from app.bot.service import run_glucose_monitor_job
        await run_glucose_monitor_job()
    except Exception as exc:
        logger.warning("Guardian job failed: %s", exc)
