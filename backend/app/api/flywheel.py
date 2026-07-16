"""数据飞轮 API —— 手动触发数据回流和模型迭代"""

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

    平时由 Celery Beat 自动跑，这个端点主要用来调试和补跑。
    days: 回溯天数，默认 30
    """
    from app.services.data_flywheel import aggregate_performance_data, auto_label_samples

    perf_data = await aggregate_performance_data(db, days=days)
    result = await auto_label_samples(db, performance_data=perf_data, days=days)

    # training_data 太大了，不返回前端
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
    """手动触发模型重训，平时也是 Celery Beat 定时跑"""
    from app.services.data_flywheel import trigger_model_retraining

    result = await trigger_model_retraining(db, days=days)
    return result
