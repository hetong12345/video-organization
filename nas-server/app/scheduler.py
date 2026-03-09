from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import settings


scheduler = BackgroundScheduler()


def setup_scheduler():
    scheduler.start()


def shutdown_scheduler():
    scheduler.shutdown()
