"""Celery 应用实例 —— Worker + Beat 调度配置"""

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

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
        "app.tasks.integration_task",
        "app.tasks.vector_task",
        "app.tasks.outbox_task",
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
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_queue="orchestration",
    task_default_exchange="shelook",
    task_default_routing_key="orchestration",
    task_queues=(
        Queue("orchestration", Exchange("shelook"), routing_key="orchestration"),
        Queue("generation", Exchange("shelook"), routing_key="generation"),
        Queue("model", Exchange("shelook"), routing_key="model"),
        Queue("analytics", Exchange("shelook"), routing_key="analytics"),
    ),
    task_routes={
        "dispatch_outbox_events": {"queue": "orchestration", "routing_key": "orchestration"},
        "generate_single_image": {"queue": "generation", "routing_key": "generation"},
        "evaluate_image_quality": {"queue": "model", "routing_key": "model"},
        "index_product_embedding": {"queue": "model", "routing_key": "model"},
        "sync_daily_metrics": {"queue": "analytics", "routing_key": "analytics"},
        "retrain_models": {"queue": "analytics", "routing_key": "analytics"},
        "auto_create_experiments_task": {"queue": "analytics", "routing_key": "analytics"},
        "update_traffic_allocation_task": {"queue": "analytics", "routing_key": "analytics"},
        "sync_dianxiaomi_connection": {"queue": "orchestration", "routing_key": "orchestration"},
    },
    broker_transport_options={"visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT_SECONDS},
    result_expires=settings.CELERY_RESULT_EXPIRES_SECONDS,
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
    "dispatch-outbox-events": {
        "task": "dispatch_outbox_events",
        "schedule": 10.0,
    },
}

app.autodiscover_tasks(["app.tasks"])

# Worker: celery -A app.tasks worker --loglevel=info --concurrency=4
# Beat:   celery -A app.tasks beat --loglevel=info
