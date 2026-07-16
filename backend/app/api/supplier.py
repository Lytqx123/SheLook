"""供应商端 API —— 不用登录，有全局限流兜底"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.core.logging import logger
from app.db.session import get_db
from app.models.supplier_report import SupplierAnalysisReport
from app.schemas.supplier import (
    SupplierAnalyzeRequest,
    SupplierReportListItem,
    SupplierReportListResponse,
    SupplierReportResponse,
)
from app.services.supplier_report import SupplierReportService

router = APIRouter(prefix="/api/supplier", tags=["Supplier"])


# ---- 上传 & 分析 ----

@router.post("/upload-and-analyze", response_model=SupplierReportResponse)
async def upload_and_analyze(
    body: SupplierAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
):
    """供应商上传图片，跑三级质检 + 品类对比 + CTR/退货预测"""
    # 校验品类
    valid_categories = {
        "dress", "shoes", "tops", "bottoms", "outerwear",
        "accessories", "bags", "lingerie", "sportswear", "kids",
    }
    if body.category.lower() not in valid_categories:
        raise ValidationError(
            f"不支持的品类: {body.category}，可选值: {', '.join(sorted(valid_categories))}"
        )

    # 校验市场
    valid_markets = {
        "SG", "MY", "TH", "ID", "VN", "PH", "TW", "BR", "MX", "CO",
        "US", "EU", "ME", "SEASIA",
    }
    if body.market.upper() not in valid_markets:
        raise ValidationError(
            f"不支持的市场: {body.market}，可选值: {', '.join(sorted(valid_markets))}"
        )

    # 图片 URL 不能为空
    if not body.image_url:
        raise ValidationError("image_url 不能为空")

    logger.info(
        "供应商图片分析请求",
        category=body.category,
        market=body.market,
        supplier_id=body.supplier_id,
    )

    # 跑分析
    report = await SupplierReportService.analyze_image(
        image_path=body.image_url,
        category=body.category.lower(),
        market=body.market.upper(),
        db=db,
    )

    # 持久化报告，方便后续查历史
    if body.supplier_id:
        db.add(
            SupplierAnalysisReport(
                report_id=report.report_id,
                supplier_id=body.supplier_id,
                report_payload=report.model_dump(mode="json"),
                analyzed_at=report.analyzed_at,
            )
        )
        await db.flush()

    return report


# ---- 查历史报告 ----

@router.get("/report/{supplier_id}", response_model=SupplierReportListResponse)
async def get_supplier_reports(
    supplier_id: str,
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: AsyncSession = Depends(get_db),
):
    """查供应商的历史分析报告，按时间倒序"""
    total = (
        await db.execute(
            select(func.count(SupplierAnalysisReport.id)).where(
                SupplierAnalysisReport.supplier_id == supplier_id
            )
        )
    ).scalar() or 0
    reports = (
        await db.execute(
            select(SupplierAnalysisReport)
            .where(SupplierAnalysisReport.supplier_id == supplier_id)
            .order_by(SupplierAnalysisReport.analyzed_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    items = [
        SupplierReportListItem(
            report_id=r.report_id,
            image_url=r.report_payload["image_url"],
            category=r.report_payload["category"],
            market=r.report_payload["market"],
            overall_score=r.report_payload["overall_score"],
            quality_verdict=r.report_payload["quality_verdict"],
            analyzed_at=r.analyzed_at,
        )
        for r in reports
    ]

    return SupplierReportListResponse(
        supplier_id=supplier_id,
        total=total,
        reports=items,
    )
