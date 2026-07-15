"""A/B 实验 API —— 创建 / 列表 / 详情 / 停止 / 自动管理 / 归因下钻"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import logger
from app.db.session import get_db
from app.models.experiment import ABExperiment, ExperimentStatus
from app.models.image import GeneratedImage, ImageScheme
from app.models.product import Product
from app.schemas import (
    ExperimentCreateRequest,
    ExperimentListOut,
    ExperimentResponse,
)

router = APIRouter(prefix="/api/experiments", tags=["Experiments"])


def _format_experiment(exp: ABExperiment) -> ExperimentResponse:
    """格式化实验响应"""
    return ExperimentResponse(
        id=exp.id,
        name=f"实验 #{exp.id}",
        product_id=exp.product_id,
        variant_a_image_id=exp.variant_a_image_id,
        variant_b_image_id=exp.variant_b_image_id,
        traffic_ratio=exp.traffic_ratio,
        status=exp.status,
        start_date=exp.start_date.isoformat() if exp.start_date else None,
        end_date=exp.end_date.isoformat() if exp.end_date else None,
        result_ctr_a=exp.result_ctr_a,
        result_ctr_b=exp.result_ctr_b,
        p_value=exp.p_value,
        winner_image_id=exp.winner_image_id,
        created_at=exp.created_at.isoformat() if exp.created_at else None,
    )


# ============ 列表 / 创建（固定路径，无路径参数冲突风险）============

@router.get("", response_model=ExperimentListOut)
async def list_experiments(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: ExperimentStatus | None = None,
):
    """分页查询实验列表"""
    query = select(ABExperiment)
    count_query = select(func.count(ABExperiment.id))

    if status:
        query = query.where(ABExperiment.status == status)
        count_query = count_query.where(ABExperiment.status == status)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(ABExperiment.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    experiments = result.scalars().all()

    return ExperimentListOut(
        items=[_format_experiment(e) for e in experiments],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ExperimentResponse, status_code=201)
async def create_experiment(
    request: Request,
    body: ExperimentCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建 A/B 实验"""
    if body.variant_a_image_id == body.variant_b_image_id:
        raise ValidationError(detail="A/B 变体必须是两张不同的图片")

    product = (
        await db.execute(select(Product.id).where(Product.id == body.product_id))
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError(detail=f"商品 #{body.product_id} 不存在")

    image_ids = [body.variant_a_image_id, body.variant_b_image_id]
    image_rows = (
        await db.execute(
            select(GeneratedImage.id, ImageScheme.product_id)
            .join(ImageScheme, GeneratedImage.scheme_id == ImageScheme.id)
            .where(GeneratedImage.id.in_(image_ids))
        )
    ).all()
    image_products = {row.id: row.product_id for row in image_rows}
    for image_id in image_ids:
        if image_id not in image_products:
            raise NotFoundError(detail=f"图片 #{image_id} 不存在")
        if image_products[image_id] != body.product_id:
            raise ValidationError(
                detail=f"图片 #{image_id} 不属于商品 #{body.product_id}"
            )

    experiment = ABExperiment(
        product_id=body.product_id,
        variant_a_image_id=body.variant_a_image_id,
        variant_b_image_id=body.variant_b_image_id,
        traffic_ratio=body.traffic_ratio,
        status=ExperimentStatus.RUNNING,
        start_date=datetime.utcnow(),
    )
    db.add(experiment)
    await db.flush()
    await db.refresh(experiment)

    logger.info(
        "实验创建成功",
        experiment_id=experiment.id,
        product_id=body.product_id,
    )

    return _format_experiment(experiment)


# ============ 自动实验管理（固定路径，必须在 /{experiment_id} 之前）============

@router.post("/auto/create", response_model=dict)
async def trigger_auto_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """手动触发自动创建 A/B 实验

    扫描所有已审核通过 + 已预测的图片，按商品找预测分接近的两张自动建实验。
    正常由 Celery Beat 每天 4:00 自动执行，此端点用于手动触发。
    """
    from app.services.experiment_auto_service import auto_create_experiments

    result = await auto_create_experiments(db)

    logger.info(
        "手动触发自动实验创建",
        created=result["created"],
        scanned=result["scanned_products"],
    )

    return result


@router.get("/auto/summary", response_model=dict)
async def get_auto_summary(
    db: AsyncSession = Depends(get_db),
):
    """查询自动实验统计概览"""
    from app.services.experiment_auto_service import get_auto_experiment_summary

    return await get_auto_experiment_summary(db)


# ============ 单实验操作（路径参数 /{experiment_id}）============

@router.get("/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment(
    experiment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取实验详情（含 CTR 对比、显著性、胜出方）"""
    result = await db.execute(select(ABExperiment).where(ABExperiment.id == experiment_id))
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise NotFoundError(detail=f"实验 #{experiment_id} 不存在")

    return _format_experiment(experiment)


@router.post("/{experiment_id}/stop", response_model=ExperimentResponse)
async def stop_experiment(
    experiment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """停止实验"""
    result = await db.execute(select(ABExperiment).where(ABExperiment.id == experiment_id))
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise NotFoundError(detail=f"实验 #{experiment_id} 不存在")

    # 从 daily_metrics 聚合实际 CTR
    from app.models import DailyMetric

    variant_metrics: dict[str, dict[str, float | int]] = {}
    for variant, img_id, attr in [
        ("A", experiment.variant_a_image_id, "result_ctr_a"),
        ("B", experiment.variant_b_image_id, "result_ctr_b"),
    ]:
        metrics = (await db.execute(
            select(
                func.coalesce(func.sum(DailyMetric.impressions), 0).label("impressions"),
                func.coalesce(func.sum(DailyMetric.clicks), 0).label("clicks"),
            ).where(DailyMetric.image_id == img_id)
        )).one()
        ctr = metrics.clicks / metrics.impressions if metrics.impressions > 0 else 0.0
        setattr(experiment, attr, ctr)
        variant_metrics[variant] = {
            "ctr": ctr,
            "impressions": int(metrics.impressions),
            "clicks": int(metrics.clicks),
        }

    # 计算显著性
    from app.services.reward_scorer import calculate_significance
    significance = calculate_significance(
        variant_metrics["A"],
        variant_metrics["B"],
    )

    experiment.p_value = significance.get("p_value")
    experiment.winner_image_id = (
        experiment.variant_a_image_id if significance.get("winner") == "A"
        else experiment.variant_b_image_id if significance.get("winner") == "B"
        else None
    )
    # 人工终止与达到预设样本/时间窗的自然完成是两个不同业务事件。
    experiment.status = ExperimentStatus.STOPPED
    experiment.end_date = datetime.utcnow()

    await db.flush()
    await db.refresh(experiment)

    logger.info("实验已人工停止", experiment_id=experiment_id, winner=experiment.winner_image_id)

    return _format_experiment(experiment)


@router.get("/{experiment_id}/breakdown")
async def get_experiment_breakdown(
    experiment_id: int,
    db: AsyncSession = Depends(get_db),
    dimension: str = "date",
):
    """多维度下钻归因分析

    按维度切片重算 A/B 实验的 Lift + 显著性：
    - dimension=date：按日期看 Lift 趋势（默认）
    - dimension=market：按市场看各市场表现差异
    - dimension=category：按品类聚合（跨品类实验时有意义）
    """
    from app.services.attribution import SUPPORTED_DIMENSIONS, dimension_breakdown

    if dimension not in SUPPORTED_DIMENSIONS:
        from app.core.exceptions import ValidationError
        raise ValidationError(
            detail=f"不支持的维度: {dimension}，可选: {list(SUPPORTED_DIMENSIONS)}"
        )

    try:
        result = await dimension_breakdown(db, experiment_id, dimension)
    except ValueError as e:
        raise NotFoundError(detail=str(e)) from e

    logger.info(
        "下钻归因查询",
        experiment_id=experiment_id,
        dimension=dimension,
        slices=len(result["breakdown"]),
    )

    return result


@router.post("/{experiment_id}/update-traffic", response_model=dict)
async def trigger_traffic_update(
    experiment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """手动触发单个实验的 UCB 流量分配更新

    基于 daily_metrics 历史数据动态调整 variant A/B 的流量比例。
    正常由 Celery Beat 每天 6:00 批量执行，此端点用于手动调整单个实验。
    """
    from app.services.experiment_auto_service import update_traffic_allocation

    try:
        result = await update_traffic_allocation(db, experiment_id)
    except ValueError as e:
        raise NotFoundError(detail=str(e)) from e

    logger.info(
        "手动触发流量分配更新",
        experiment_id=experiment_id,
        new_ratio=result["new_ratio"],
        method=result["method"],
    )

    return result
