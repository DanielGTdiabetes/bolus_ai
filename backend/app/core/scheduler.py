import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler = None

def init_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.start()
    logger.info("Background Scheduler initialized.")

def get_scheduler():
    return _scheduler

def schedule_task(func, trigger, task_id, replace=True):
    if not _scheduler:
        raise RuntimeError("Scheduler not initialized")
    
    job = _scheduler.add_job(
        func, 
        trigger, 
        id=task_id, 
        replace_existing=replace
    )
    logger.info(f"Scheduled task '{task_id}' with trigger: {trigger}")
    return job
