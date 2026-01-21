from datetime import date, datetime
import logging
from apscheduler.triggers.cron import CronTrigger
from app.core.scheduler import init_scheduler, schedule_task
from app.core.settings import get_settings
from app.core import config
from app.core.datastore import UserStore
from pathlib import Path
from app.services.basal_engine import scan_night_service
from app.services.stability_monitor import StabilityMonitor
from app import jobs_state

logger = logging.getLogger(__name__)

from app.bot import proactive

async def _run_auto_night_scan_task():
    """
    Background Task: Scans night data for all users.
    Typically runs at 07:00 AM.
    """
    logger.info("Running Auto Night Scan Job...")
    settings = get_settings()
    data_dir = Path(settings.data.data_dir)
    user_store = UserStore(data_dir / "users.json")
    
    # Audit H14: Use DB users instead of local file
    from app.core.db import get_engine, get_db_session
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.store import DataStore
    
    # Feature Flag for Safety
    write_enabled = settings.autoscan_write_enabled
    logger.info(f"Autoscan Write Mode: {'ENABLED' if write_enabled else 'SAFE (Dry Run)'}")

    users = []
    engine = get_engine()
    
    # 1. Get Users
    try:
        if engine:
            async with engine.connect() as conn:
                res = await conn.execute(text("SELECT username FROM users"))
                rows = res.fetchall()
                users = [{"username": r[0]} for r in rows]
        else:
             users = user_store.get_all_users()
    except Exception as e:
        logger.error(f"Failed to load users from DB: {e}")
        users = user_store.get_all_users()
    
    if not engine:
        logger.warning("No DB Engine available for Autoscan. Skipping.")
        return

    # 2. Run Scan
    count = 0
    ds = DataStore(data_dir)
    
    async with AsyncSession(engine) as session:
        from app.services.nightscout_secrets_service import get_ns_config
        from app.services.nightscout_client import NightscoutClient
        
        for user in users:
            username = user.get("username")
            if not username: continue
            
            try:
                # Get NS Client
                ns_cfg = await get_ns_config(session, username)
                if not ns_cfg or not ns_cfg.url:
                    continue
                    
                client = NightscoutClient(ns_cfg.url, ns_cfg.api_secret, timeout_seconds=30)
                
                try:
                    # Target Date: Yesterday? Or Today's morning? 
                    # Usually we scan "Last Night". If running at 7AM, we scan the night that just ended.
                    # Which is technically "Today's date" for the morning hours (00-06).
                    target_date = date.today()
                    
                    result = await scan_night_service(username, target_date, client, session, write_enabled=write_enabled)
                    
                    if not write_enabled:
                         # Persist Safe Log
                         log_entry = {
                             "user": username,
                             "date": target_date.isoformat(),
                             "result": result,
                             "timestamp": datetime.now().isoformat()
                         }
                         # Append to daily log or rotational log
                         try:
                             logs = ds.read_json("night_scan_safemode.json", [])
                             logs.insert(0, log_entry)
                             ds.write_json("night_scan_safemode.json", logs[:100]) # Keep last 100
                         except Exception as log_e:
                             logger.error(f"Failed to write safemode log: {log_e}")

                    count += 1
                finally:
                    await client.aclose()
                    
            except Exception as e:
               logger.error(f"Error scanning for user {username}: {e}")

    logger.info(f"Auto Night Scan Job Completed. Processed {count} users.")

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
    from sqlalchemy import text

    logger.info("Running Learning Evaluation Job...")
    engine = get_engine()
    if not engine:
        logger.warning("No DB engine for learning evaluation.")
        return

    settings = get_settings()
    data_dir = Path(settings.data.data_dir)
    user_store = UserStore(data_dir / "users.json")
    
    # Audit H14: Use DB users
    users = []
    try:
         async with engine.connect() as conn:
            res = await conn.execute(text("SELECT username FROM users"))
            users = [{"username": r[0]} for r in res.fetchall()]
    except Exception:
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
                    await ls.evaluate_pending_outcomes(client, user_id=username)
                finally:
                    await client.aclose()
                    
            except Exception as e:
                logger.error(f"Evaluating user {username} failed: {e}")
    
    logger.info("Learning Evaluation Job Completed.")


async def run_learning_evaluation():
    return await jobs_state.run_job("learning_eval", _run_learning_evaluation_task)

async def _run_ml_training_snapshot_task() -> None:
    """
    Background Task: Collects ML training snapshots for all users.
    Runs every 5 minutes.
    """
    from app.core.db import get_engine
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.ml_training_pipeline import collect_and_persist_training_snapshot
    from sqlalchemy import text

    logger.info("Running ML Training Snapshot Job...")
    engine = get_engine()
    if not engine:
        logger.warning("No DB engine for ML training snapshot.")
        return

    settings = get_settings()
    data_dir = Path(settings.data.data_dir)
    user_store = UserStore(data_dir / "users.json")

    users = []
    try:
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT username FROM users"))
            users = [{"username": r[0]} for r in res.fetchall()]
    except Exception as exc:
        logger.error("Failed to load users for ML snapshot: %s", exc)
        users = user_store.get_all_users()

    async with AsyncSession(engine) as session:
        for user in users:
            username = user.get("username")
            if not username:
                continue
            try:
                await collect_and_persist_training_snapshot(username, session)
            except Exception as exc:
                logger.error("ML snapshot failed for user %s: %s", username, exc)

    logger.info("ML Training Snapshot Job Completed.")


async def run_ml_training_snapshot() -> None:
    await jobs_state.run_job("ml_training_snapshot", _run_ml_training_snapshot_task)


def setup_periodic_tasks():
    init_scheduler()
    
    # --- Emergency Monitor (Always check configuration inside, or explicit here) ---
    # Only run monitor if we ARE in emergency mode (or want to monitor from standby)
    settings = get_settings()
    if settings.emergency_mode:
        schedule_task(StabilityMonitor.check_health, CronTrigger(minute='*'), "check_nas_health")
        logger.info("⚠️ Emergency Mode: Scheduler running ONLY Stability Monitor.")
        return # STOP HERE. Do not schedule normal data ingestion tasks.

    # --- Normal Operations (NAS Primary) ---

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

    # Run ML training snapshot every 5 mins
    ml_training_trigger = CronTrigger(minute='*/5')
    schedule_task(run_ml_training_snapshot, ml_training_trigger, "ml_training_snapshot")
    jobs_state.refresh_next_run("ml_training_snapshot")

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



        async def _run_app_notifications():
             await jobs_state.run_job("app_notifications", proactive.check_app_notifications)

        schedule_task(_run_basal, CronTrigger(minute='*/45'), "basal_reminder")
        jobs_state.refresh_next_run("basal")

        schedule_task(_run_premeal, CronTrigger(minute='*/30'), "premeal_nudge")
        jobs_state.refresh_next_run("premeal")
        schedule_task(_run_combo, CronTrigger(minute='*/30'), "combo_followup")
        
        # Schedule Notification Check (Every 1 hour)
        schedule_task(_run_app_notifications, CronTrigger(minute='0'), "app_notifications")
        jobs_state.refresh_next_run("app_notifications")

        async def _run_isf_check():
            try:
                await jobs_state.run_job("isf_check", proactive.check_isf_suggestions)
            except AttributeError:
                pass # proactive might not have it yet if hot-reloading issues, but usually fine

        schedule_task(_run_isf_check, CronTrigger(hour=8, minute=0), "isf_check")
        jobs_state.refresh_next_run("isf_check")

        async def _run_active_plans():
            await jobs_state.run_job("active_plans_check", proactive.check_active_plans)

        schedule_task(_run_active_plans, CronTrigger(minute='*/2'), "active_plans_check") # Check every 2 min
        jobs_state.refresh_next_run("active_plans_check")

        # Missing Jobs (Audit Remediation)
        async def _run_trend_alert():
             # Trigger auto
             await jobs_state.run_job("trend_alert", proactive.trend_alert)

        async def _run_supplies_check():
             await jobs_state.run_job("supplies_check", proactive.check_supplies_status)

        # Trend alert: frequent check (e.g. every 10 min)
        schedule_task(_run_trend_alert, CronTrigger(minute='*/10'), "trend_alert")
        jobs_state.refresh_next_run("trend_alert")

        # Supplies check: Daily at 9:00 AM
        schedule_task(_run_supplies_check, CronTrigger(hour=9, minute=0), "supplies_check")
        jobs_state.refresh_next_run("supplies_check")

