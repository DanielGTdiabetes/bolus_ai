from datetime import date, datetime, timedelta
import logging
from apscheduler.triggers.cron import CronTrigger
from app.core.scheduler import init_scheduler, schedule_task
from app.core.settings import get_settings
from app.core import config
from app.core.datastore import UserStore
from pathlib import Path
from app.services.basal_engine import scan_night_service

logger = logging.getLogger(__name__)

async def run_auto_night_scan():
    """
    Background Task: Scans night data for all users.
    Typically runs at 07:00 AM.
    """
    logger.info("Running Auto Night Scan Job...")
    settings = get_settings()
    data_dir = Path(settings.data.data_dir)
    user_store = UserStore(data_dir / "users.json")
    
    users = user_store.get_all_users()
    today = date.today() # Local server time

    count = 0
    for user in users:
        # Skip if missing basic role or deactivated
        if not user.get("username"): 
            continue
            
        # We need Nightscout credentials. Currently these are expected to be passed 
        # via API or stored. If we rely on stored settings (new DB table user_settings),
        # we would fetch them here.
        
        # However, `scan_night_service` in `basal_engine.py` currently takes `nightscout_config`.
        # We must refactor or ensure we can get config for headless run.
        # For now, we will log a placeholder if we can't get config easily without DB details.
        
        # NOTE: With recent refactor, `user_settings` table stores NS config if synced.
        # But `scan_night_service` signature is: 
        # async def scan_night_service(user_id: str, current_date: date, ns_config: dict[str, str])
        
        # Let's try to fetch user settings from DB if possible, or just log for now until full integration.
        # Since we are in an async job, we can use the DB.
        
        try:
             # TODO: Fetch NS config from DB for this user.
             # For this task, we will assume we can get it or skip.
             # To keep it simple for this step:
             logger.info(f"Checking night scan for user {user['username']}... (Skipping actual logic pending DB config access)")
             count += 1
        except Exception as e:
            logger.error(f"Error scanning for user {user.get('username')}: {e}")

    logger.info(f"Auto Night Scan Job Completed. Processed {count} users (dry-run).")


async def run_learning_evaluation():
    """
    Background Task: Evaluates outcomes of past meals (Effect Memory).
    """
    from app.core.db import get_engine
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.learning_service import LearningService
    from app.services.nightscout_secrets_service import get_ns_config
    from app.services.nightscout_client import NightscoutClient, NightscoutError

    logger.info("Running Learning Evaluation Job...")
    engine = get_engine()
    if not engine:
        logger.warning("No DB engine for learning evaluation.")
        return

    settings = get_settings()
    user_store = UserStore(Path(settings.data.data_dir) / "users.json")
    users = user_store.get_all_users()
    
    async with AsyncSession(engine) as session:
        ls = LearningService(session)
        
        for user in users:
            username = user.get("username")
            if not username: continue
            
            try:
                ns_cfg = await get_ns_config(session, username)
                if not ns_cfg or not ns_cfg.url:
                    continue
                    
                # Create Client
                token = ns_cfg.api_secret
                client = NightscoutClient(ns_cfg.url, token, timeout_seconds=10)
                
                try:
                    await ls.evaluate_pending_outcomes(client)
                finally:
                    await client.aclose()
                    
            except Exception as e:
                logger.error(f"Evaluating user {username} failed: {e}")
    
    logger.info("Learning Evaluation Job Completed.")


def setup_periodic_tasks():
    init_scheduler()
    
    # Run at 07:00 AM every day
    trigger = CronTrigger(hour=7, minute=0)
    schedule_task(run_auto_night_scan, trigger, "auto_night_scan")

    # Run cleanup at 04:00 AM every day
    cleanup_trigger = CronTrigger(hour=4, minute=0)
    schedule_task(run_data_cleanup, cleanup_trigger, "data_cleanup")

    # Run learning evaluation every 30 mins
    learning_trigger = CronTrigger(minute='*/30')
    schedule_task(run_learning_evaluation, learning_trigger, "learning_eval")

    # Run Guardian Mode (Glucose Alert) every 5 mins
    from app.bot.service import run_glucose_monitor_job
    guardian_trigger = CronTrigger(minute='*/5')
    schedule_task(run_glucose_monitor_job, guardian_trigger, "guardian_check")

    # Light proactive v1 jobs (respect Render limits)
    if config.is_telegram_bot_enabled():
        from app.bot import proactive
        from app.bot import service as bot_service
        async def _run_morning():
            bot_app = bot_service.get_bot_application()
            bot = bot_app.bot if bot_app else None
            await proactive.morning_summary(bot)

        async def _run_basal():
            bot_app = bot_service.get_bot_application()
            bot = bot_app.bot if bot_app else None
            await proactive.basal_reminder(bot)

        async def _run_premeal():
            bot_app = bot_service.get_bot_application()
            bot = bot_app.bot if bot_app else None
            await proactive.premeal_nudge(bot)

        async def _run_combo():
            bot_app = bot_service.get_bot_application()
            bot = bot_app.bot if bot_app else None
            await proactive.combo_followup(bot)

        schedule_task(_run_morning, CronTrigger(hour=8, minute=5), "morning_summary")
        schedule_task(_run_basal, CronTrigger(minute='*/45'), "basal_reminder")
        schedule_task(_run_premeal, CronTrigger(minute='*/30'), "premeal_nudge")
        schedule_task(_run_combo, CronTrigger(minute='*/30'), "combo_followup")


async def run_data_cleanup():
    """
    Background Task: Cleans up old data retention > 90 days.
    """
    from app.services.basal_repo import delete_old_data
    logger.info("Running Data Cleanup Job...")
    try:
        res = await delete_old_data(retention_days=90)
        logger.info(f"Cleanup finished. Stats: {res}")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
