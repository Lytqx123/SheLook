"""效果预估 API —— CTR 预测 / 退货风险 / 模型版本管理"""

import asyncio

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import UserInfo, has_permission, require_auth
from app.core.deps import get_predictor
from app.core.exceptions import NotFoundError
from app.core.logging import logger
from app.core.tenant import get_current_tenant_id
from app.db.session import get_db
from app.models.enterprise_data import PredictionSnapshot
from app.models.image import GeneratedImage, ImageScheme
from app.models.prediction import DailyMetric, PredictionRecord, ReturnRiskLevel
from app.models.product import Product
from app.schemas import ModelRollbackRequest, PredictionRequest, PredictionResponse
from app.services.predictor import CTRPredictor

router = APIRouter(prefix="/api/prediction", tags=["Prediction"])


async def _execute_prediction(
    db: AsyncSession,
    predictor: CTRPredictor,
    image: GeneratedImage,
    image_id: int,
) -> PredictionResponse:
    """共享预测逻辑，predict_image 和 predict_by_scheme 都走这里

    调用方要确保 image 已预加载 scheme.product 关系。
    """
    from app.services.attribution import generate_attribution_report
    from app.services.compliance_checker import full_compliance_check
    from app.services.storage_service import resolve_image_url

    await resolve_image_url(image)

    # 跑预测（CLIP 推理走 asyncio.to_thread 不阻塞事件循环）
    result = await asyncio.to_thread(predictor.predict, image)
    scores = result.get("scores", {})

    # 退货风险归因（只在高风险时跑）
    attribution = None
    if scores.get("return_risk") and scores["return_risk"] > 0.3:
        baseline_stmt = (
            select(
                func.coalesce(func.sum(DailyMetric.impressions), 1000).label("total_impressions"),
                func.coalesce(func.sum(DailyMetric.clicks), 100).label("total_clicks"),
                func.coalesce(func.sum(DailyMetric.cvr), 50).label("total_conversions"),
                func.coalesce(func.sum(DailyMetric.return_rate), 40).label("total_returns"),
            )
            .join(GeneratedImage, DailyMetric.image_id == GeneratedImage.id)
            .join(ImageScheme, GeneratedImage.scheme_id == ImageScheme.id)
            .join(Product, ImageScheme.product_id == Product.id)
            .where(
                GeneratedImage.created_at < func.now() - text("INTERVAL '30 days'"),
            )
        )
        baseline_row = (await db.execute(baseline_stmt)).one_or_none()

        if baseline_row:
            control_metrics = {
                "impressions": max(int(baseline_row.total_impressions or 1000), 100),
                "clicks": max(int(baseline_row.total_clicks or 100), 1),
                "conversions": max(int(baseline_row.total_conversions or 50), 1),
                "returns": max(int(baseline_row.total_returns or 40), 1),
            }
        else:
            control_metrics = {"impressions": 1000, "clicks": 100, "conversions": 50, "returns": 40}

        attribution = generate_attribution_report(
            image_id=image_id,
            variant_metrics={
                "impressions": 1000,
                "clicks": int(1000 * scores.get("predicted_ctr", 0.025)),
                "conversions": 50,
                "returns": int(1000 * scores["return_risk"]),
            },
            control_metrics=control_metrics,
        )

    # 合规校验
    compliance = None
    if image.image_url:
        try:
            from app.services.image_fetcher import fetch_image_to_temp_sync

            tmp_path = await asyncio.to_thread(fetch_image_to_temp_sync, image.image_url)
            try:
                compliance = await asyncio.to_thread(full_compliance_check, tmp_path)
            finally:
                import os
                os.unlink(tmp_path)
        except Exception as e:
            logger.warning("合规校验失败（非阻断）", error=str(e))

    # 持久化
    risk_level = None
    if scores.get("return_risk"):
        risk = scores["return_risk"]
        if risk < 0.3:
            risk_level = ReturnRiskLevel.LOW
        elif risk < 0.6:
            risk_level = ReturnRiskLevel.MEDIUM
        else:
            risk_level = ReturnRiskLevel.HIGH

    record = PredictionRecord(
        image_id=image_id,
        predicted_ctr=scores.get("predicted_ctr"),
        ctr_confidence_interval=scores.get("confidence_interval"),
        predicted_hit_probability=scores.get("hit_probability"),
        return_risk_level=risk_level,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)

    snapshot = PredictionSnapshot(
        tenant_id=get_current_tenant_id(),
        prediction_record_id=record.id,
        image_id=image_id,
        predicted_ctr=record.predicted_ctr,
        model_version=CTRPredictor.get_current_version(get_current_tenant_id()),
        feature_version="v1",
        entity_snapshot_json={
            "image_id": image_id,
            "scheme_id": image.scheme_id,
            "product_id": image.scheme.product_id if image.scheme else None,
            "market": image.market_variant,
        },
        predicted_at=record.predicted_at,
    )
    db.add(snapshot)
    await db.flush()

    logger.info("预测完成", image_id=image_id, ctr=record.predicted_ctr)

    return PredictionResponse(
        record_id=record.id,
        image_id=image_id,
        predicted_ctr=record.predicted_ctr,
        normalized_ctr=scores.get("normalized_ctr"),
        ctr_confidence_interval=record.ctr_confidence_interval,
        predicted_hit_probability=record.predicted_hit_probability,
        return_risk=attribution,
        return_risk_level=record.return_risk_level,
        return_risk_probability=scores.get("return_risk_probability"),
        return_risk_source=scores.get("return_risk_source"),
        compliance=compliance,
        predicted_at=record.predicted_at.isoformat() if record.predicted_at else None,
    )


@router.post("", response_model=PredictionResponse)
async def predict_image(
    request: Request,
    body: PredictionRequest,
    db: AsyncSession = Depends(get_db),
    predictor: CTRPredictor = Depends(get_predictor),
):
    """按图片 ID 预测 CTR / 爆款概率 / 退货风险"""
    # 查图片（预加载 scheme + product，避免 sync predictor 里 MissingGreenlet）
    img_result = await db.execute(
        select(GeneratedImage)
        .options(selectinload(GeneratedImage.scheme).selectinload(ImageScheme.product))
        .where(GeneratedImage.id == body.image_id)
    )
    image = img_result.scalar_one_or_none()
    if not image:
        raise NotFoundError(detail=f"图片 #{body.image_id} 不存在")

    return await _execute_prediction(db, predictor, image, body.image_id)


@router.post("/by-scheme/{scheme_id}", response_model=PredictionResponse)
async def predict_by_scheme(
    scheme_id: int,
    db: AsyncSession = Depends(get_db),
    predictor: CTRPredictor = Depends(get_predictor),
):
    """按方案预测 —— 自动取该方案下 overall_score 最高的图片来跑"""
    img_result = await db.execute(
        select(GeneratedImage)
        .options(selectinload(GeneratedImage.scheme).selectinload(ImageScheme.product))
        .where(GeneratedImage.scheme_id == scheme_id)
        .order_by(desc(GeneratedImage.overall_score))
        .limit(1)
    )
    image = img_result.scalar_one_or_none()
    if not image:
        raise NotFoundError(detail=f"方案 #{scheme_id} 下没有可预测的生成图片")

    return await _execute_prediction(db, predictor, image, image.id)


@router.get("/history/{image_id}", response_model=dict)
async def get_prediction_history(
    image_id: int,
    db: AsyncSession = Depends(get_db),
):
    """查某图片的预测历史，按时间倒序"""
    result = await db.execute(
        select(PredictionRecord)
        .where(
            PredictionRecord.image_id == image_id,
            or_(
                PredictionRecord.ctr_confidence_interval["source"].as_string().is_(None),
                PredictionRecord.ctr_confidence_interval["source"].as_string() != "actual",
            ),
        )
        .order_by(desc(PredictionRecord.predicted_at))
        .limit(50)
    )
    records = result.scalars().all()

    return {
        "image_id": image_id,
        "count": len(records),
        "items": [
            {
                "id": r.id,
                "predicted_ctr": r.predicted_ctr,
                "ctr_confidence_interval": r.ctr_confidence_interval,
                "predicted_hit_probability": r.predicted_hit_probability,
                "return_risk_level": r.return_risk_level,
                "predicted_at": r.predicted_at.isoformat() if r.predicted_at else None,
            }
            for r in records
        ],
    }


# ---- 模型版本管理 ----

@router.get("/model-versions", response_model=dict)
async def list_model_versions():
    """列出可用的预测模型版本"""
    from app.services.predictor import CTRPredictor

    tenant_id = get_current_tenant_id()
    versions = CTRPredictor.list_versions(tenant_id)
    current = CTRPredictor.get_current_version(tenant_id)

    return {
        "versions": versions,
        "current_version": current,
    }


@router.post("/rollback", response_model=dict)
async def rollback_model(
    body: ModelRollbackRequest,
    user: UserInfo = Depends(require_auth),
):
    """回滚预测模型到指定日期版本，管理员手动操作"""
    if user.role != "admin" and not has_permission(user, "model:manage"):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="需要模型管理权限")
    result = CTRPredictor.rollback(body.target_date, tenant_id=user.tenant_id)

    try:
        from app.core.audit import audit_operation
        await audit_operation(
            operation="model_rollback",
            model_name=f"ctr_predictor_{body.target_date}",
            status="success" if result["success"] else "failed",
        )
    except Exception as error:
        logger.warning("模型回滚完成但审计日志写入异常", error=str(error))

    return result
