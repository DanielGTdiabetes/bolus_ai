from datetime import date, datetime, timedelta
import logging
from apscheduler.triggers.cron import CronTrigger
from app.core.scheduler import init_scheduler, schedule_task
from app.core.settings import get_settings
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

def setup_periodic_tasks():
    init_scheduler()
    
    # Run at 07:00 AM every day
    trigger = CronTrigger(hour=7, minute=0)
    schedule_task(run_auto_night_scan, trigger, "auto_night_scan")
