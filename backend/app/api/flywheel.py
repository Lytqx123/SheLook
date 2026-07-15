"""数据飞轮 API —— 手动触发数据回流与模型迭代"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(prefix="/api/flywheel", tags=["Flywheel"])


@router.post("/sync")
async def trigger_sync(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """手动触发数据回流 + 自动标注

    通常由 Celery Beat 每天凌晨 2:00 自动执行，
    此端点用于手动补跑或调试。

    Args:
        days: 回溯天数（默认 30 天）
    """
    from app.services.data_flywheel import aggregate_performance_data, auto_label_samples

    perf_data = await aggregate_performance_data(db, days=days)
    result = await auto_label_samples(db, performance_data=perf_data, days=days)

    # 去掉 training_data（太大了不返回给前端）
    result.pop("training_data", None)

    return {
        "status": "success",
        "days": days,
        **result,
    }


@router.post("/retrain")
async def trigger_retrain(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """手动触发模型迭代训练

    通常由 Celery Beat 每周日凌晨 3:00 自动执行，
    此端点用于手动触发或调试。

    Args:
        days: 回溯天数（默认 30 天）
    """
    from app.services.data_flywheel import trigger_model_retraining

    result = await trigger_model_retraining(db, days=days)
    return result
