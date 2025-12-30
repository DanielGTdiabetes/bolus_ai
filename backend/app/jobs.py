from datetime import date
import logging
from apscheduler.triggers.cron import CronTrigger
from app.core.scheduler import init_scheduler, schedule_task
from app.core.settings import get_settings
from app.core import config
from app.core.datastore import UserStore
from pathlib import Path
from app.services.basal_engine import scan_night_service
from app import jobs_state

logger = logging.getLogger(__name__)

async def _run_auto_night_scan_task():
    """
    Background Task: Scans night data for all users.
    Typically runs at 07:00 AM.
    """
    logger.info("Running Auto Night Scan Job...")
    settings = get_settings()
    data_dir = Path(settings.data.data_dir)
    user_store = UserStore(data_dir / "users.json")
    
    users = user_store.get_all_users()
    
    count = 0
    for user in users:
        # Skip if missing basic role or deactivated
        if not user.get("username"): 
            continue
        try:
             # TODO: Fetch NS config from DB for this user.
             logger.info(f"Checking night scan for user {user['username']}... (Skipping actual logic pending DB config access)")
             count += 1
        except Exception as e:
            logger.error(f"Error scanning for user {user.get('username')}: {e}")

    logger.info(f"Auto Night Scan Job Completed. Processed {count} users (dry-run).")

async def run_auto_night_scan():
    await jobs_state.run_job("auto_night_scan", _run_auto_night_scan_task)

async def _run_data_cleanup_task():
    """
    Background Task: Cleans up old data retention > 90 days.
    """
    from app.services.basal_repo import delete_old_data
    logger.info("Running Data Cleanup Job...")
    res = await delete_old_data(retention_days=90)
    logger.info(f"Cleanup finished. Stats: {res}")

async def run_data_cleanup():
    await jobs_state.run_job("data_cleanup", _run_data_cleanup_task)



async def _run_learning_evaluation_task():
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


async def run_learning_evaluation():
    return await jobs_state.run_job("learning_eval", _run_learning_evaluation_task)


def setup_periodic_tasks():
    init_scheduler()
    
    # Run at 07:00 AM every day
    trigger = CronTrigger(hour=7, minute=0)
    schedule_task(run_auto_night_scan, trigger, "auto_night_scan")
    jobs_state.refresh_next_run("auto_night_scan")

    # Run cleanup at 04:00 AM every day
    cleanup_trigger = CronTrigger(hour=4, minute=0)
    schedule_task(run_data_cleanup, cleanup_trigger, "data_cleanup")
    jobs_state.refresh_next_run("data_cleanup")

    # Run learning evaluation every 30 mins
    learning_trigger = CronTrigger(minute='*/30')
    schedule_task(run_learning_evaluation, learning_trigger, "learning_eval")
    jobs_state.refresh_next_run("learning_eval")

    # Run Guardian Mode (Glucose Alert) every 5 mins
    from app.bot.service import run_glucose_monitor_job
    guardian_trigger = CronTrigger(minute='*/5')
    async def _run_glucose_monitor():
        await jobs_state.run_job("glucose_monitor", run_glucose_monitor_job)

    schedule_task(_run_glucose_monitor, guardian_trigger, "guardian_check")
    jobs_state.refresh_next_run("glucose_monitor")

    # Light proactive v1 jobs (respect Render limits)
    if config.is_telegram_bot_enabled():
        from app.bot import proactive
        from app.bot import service as bot_service
        async def _run_morning():
            # bot is not needed anymore, internally resolved or passed explicitly to loggers if needed
            # proactive functions signature: (username="admin", chat_id=None)
            await jobs_state.run_job("morning_summary", proactive.morning_summary)

        async def _run_basal():
            await jobs_state.run_job("basal", proactive.basal_reminder)

        async def _run_premeal():
            await jobs_state.run_job("premeal", proactive.premeal_nudge)

        async def _run_combo():
             # combo_followup might also follow the pattern
            await proactive.combo_followup()



        schedule_task(_run_basal, CronTrigger(minute='*/45'), "basal_reminder")
        jobs_state.refresh_next_run("basal")

        schedule_task(_run_premeal, CronTrigger(minute='*/30'), "premeal_nudge")
        jobs_state.refresh_next_run("premeal")
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
