from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.services.task_manager import task_manager
from app.config import settings


scheduler = BackgroundScheduler()


def setup_scheduler():
    scheduler.add_job(
        task_manager.scan_and_process,
        trigger=IntervalTrigger(minutes=5),
        id='scan_videos',
        name='Scan for new videos',
        replace_existing=True
    )
    
    scheduler.add_job(
        task_manager.create_cluster_task,
        trigger=IntervalTrigger(minutes=10),
        id='create_cluster_task',
        name='Create cluster task if needed',
        replace_existing=True
    )
    
    scheduler.start()


def shutdown_scheduler():
    scheduler.shutdown()
