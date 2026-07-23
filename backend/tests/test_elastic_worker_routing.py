"""阶段四：任务按负载类型隔离，避免慢任务挤占核心调度。"""

from app.tasks.celery_app import app


def test_tasks_route_to_isolated_queues() -> None:
    routes = app.conf.task_routes
    assert routes["dispatch_outbox_events"]["queue"] == "orchestration"
    assert routes["generate_single_image"]["queue"] == "generation"
    assert routes["evaluate_image_quality"]["queue"] == "model"
    assert routes["sync_daily_metrics"]["queue"] == "analytics"


def test_delivery_configuration_is_recoverable_after_worker_loss() -> None:
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert {queue.name for queue in app.conf.task_queues} == {
        "orchestration",
        "generation",
        "model",
        "analytics",
    }
