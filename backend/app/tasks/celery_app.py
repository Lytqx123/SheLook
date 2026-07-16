"""Celery 应用实例 —— Worker + Beat 调度配置"""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

app = Celery(
    "shelook",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.generation_task",
        "app.tasks.evaluation_task",
        "app.tasks.flywheel_task",
        "app.tasks.experiment_task",
        "app.tasks.vector_task",
    ],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_prefetch_multiplier=1,
)

# Beat 定时任务调度
app.conf.beat_schedule = {
    "sync-daily-metrics": {
        "task": "sync_daily_metrics",
        "schedule": crontab(hour=2, minute=0),
    },
    "retrain-models": {
        "task": "retrain_models",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),
    },
    "auto-create-experiments": {
        "task": "auto_create_experiments_task",
        "schedule": crontab(hour=4, minute=0),
    },
    "update-traffic-allocation": {
        "task": "update_traffic_allocation_task",
        "schedule": crontab(hour=6, minute=0),
    },
}

app.autodiscover_tasks(["app.tasks"])

# Worker: celery -A app.tasks worker --loglevel=info --concurrency=4
# Beat:   celery -A app.tasks beat --loglevel=info
