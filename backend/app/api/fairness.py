"""公平性分析 API —— 肤色分布 + 冷启动策略"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.session import get_db
from app.schemas.fairness import SchemeFairnessOut
from app.services.fairness_service import (
    check_fairness_for_scheme,
    detect_skin_tone_distribution,
    get_all_markets_report,
)

router = APIRouter(prefix="/api/fairness", tags=["Fairness"])

# 有效的市场代码
VALID_MARKETS = {"us", "eu", "me", "seasia"}

# 肤色标签展示顺序
SKIN_TONE_ORDER = ["light", "medium", "dark", "no_person", "unknown"]


@router.get("/distribution")
async def get_distribution(
    market: str | None = Query(None, description="目标市场过滤（us/eu/me/seasia）"),
    category: str | None = Query(None, description="品类过滤"),
    db: AsyncSession = Depends(get_db),
):
    """查已生成图片的肤色分布，跟目标市场人口预期做对比"""
    if market and market not in VALID_MARKETS:
        raise HTTPException(
            status_code=422,
            detail=f"无效市场代码 '{market}'，有效选项: {', '.join(sorted(VALID_MARKETS))}",
        )

    result = await detect_skin_tone_distribution(db, market=market, category=category)
    logger.info("公平性分布查询", market=market, alert=result["fairness_alert"])

    total = result["total_images"]
    dist = result["distribution"]
    items = []
    for label in SKIN_TONE_ORDER:
        count = dist.get(label, 0)
        items.append({
            "label": label,
            "count": count,
            "percentage": round(count / total * 100, 1) if total > 0 else 0,
        })
    return items


@router.get("/report/{market}")
async def get_report(
    market: str,
    db: AsyncSession = Depends(get_db),
):
    """全市场公平性对比报告，前端柱状图用"""
    if market not in VALID_MARKETS:
        raise HTTPException(
            status_code=422,
            detail=f"无效市场代码 '{market}'，有效选项: {', '.join(sorted(VALID_MARKETS))}",
        )

    result = await get_all_markets_report(db, markets=[market])
    logger.info("单市场公平性报告已生成", market=market)
    return result


@router.post("/check-scheme/{scheme_id}", response_model=SchemeFairnessOut)
async def check_scheme(
    scheme_id: int,
    db: AsyncSession = Depends(get_db),
):
    """检查指定方案有没有过公平性阈值"""
    result = await check_fairness_for_scheme(db, scheme_id=scheme_id)
    if result.get("market") is None and "不存在" in result.get("details", ""):
        raise HTTPException(status_code=404, detail=result["details"])

    logger.info("方案公平性检查", scheme_id=scheme_id, passes=result["passes_fairness"])
    return result
