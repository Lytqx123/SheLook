"""Celery 应用实例 —— Worker + Beat 调度配置"""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

# Celery 实例
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

# 序列化配置
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,          # 单任务最大 10 分钟
    task_soft_time_limit=540,     # 软限制 9 分钟（触发 SoftTimeLimitExceeded）
    worker_prefetch_multiplier=1, # 按任务公平分配
)

# Celery Beat 定时任务调度
app.conf.beat_schedule = {
    "sync-daily-metrics": {
        "task": "sync_daily_metrics",
        "schedule": crontab(hour=2, minute=0),  # 每天凌晨 2:00
    },
    "retrain-models": {
        "task": "retrain_models",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),  # 每周日凌晨 3:00
    },
    "auto-create-experiments": {
        "task": "auto_create_experiments_task",
        "schedule": crontab(hour=4, minute=0),  # 每天凌晨 4:00 自动创建实验
    },
    "update-traffic-allocation": {
        "task": "update_traffic_allocation_task",
        "schedule": crontab(hour=6, minute=0),  # 每天凌晨 6:00 UCB 流量调整
    },
}

# 自动发现任务
app.autodiscover_tasks(["app.tasks"])

# Worker 启动命令：
# celery -A app.tasks worker --loglevel=info --concurrency=4
# Beat 启动命令（独立容器）：
# celery -A app.tasks beat --loglevel=info
