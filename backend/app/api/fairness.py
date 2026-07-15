"""公平性分析 API —— 肤色分布检测与冷启动策略

端点：
  GET  /api/fairness/distribution  —— 肤色分布分析（返回 SkinToneItem[]）
  GET  /api/fairness/report/{market} —— 全市场公平性对比报告（返回 {markets: [...]}）
  POST /api/fairness/check-scheme/{scheme_id} —— 方案级公平性检查
"""

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
    """查询已生成图片的肤色分布。

    返回 SkinToneItem[] 格式：[{label, count, percentage}, ...]
    使用 CLIP Zero-shot 按肤色标签进行分类并与目标市场
    的人口统计预期进行对比。偏差 >30% 将触发公平性告警。
    """
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
    """生成全市场公平性对比报告。

    返回 {markets: FairnessMarketDemographic[]} 格式，包含所有市场的
    预期分布、实际分布和偏差数据，供前端柱状图对比展示。
    每张图片仅 CLIP 分类一次，按 market_variant 分组统计。
    """
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
    """检查指定方案是否符合公平性约束。

    获取方案所在市场的肤色分布并根据公平性阈值给出
    通过/未通过的判定与建议。
    """
    result = await check_fairness_for_scheme(db, scheme_id=scheme_id)
    if result.get("market") is None and "不存在" in result.get("details", ""):
        raise HTTPException(status_code=404, detail=result["details"])

    logger.info("方案公平性检查", scheme_id=scheme_id, passes=result["passes_fairness"])
    return result
