"""租户级发布开关：默认保持既有功能可用，显式关闭即可立即熔断。"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import get_current_tenant_id
from app.models.release_control import TenantFeatureFlag

DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    "ai_generation": True,
    "video_generation": True,
    "automated_experiments": True,
}


async def is_feature_enabled(db: AsyncSession, flag_key: str) -> bool:
    """返回当前租户的有效开关值；未配置时使用兼容性默认值。"""
    flag = await db.scalar(
        select(TenantFeatureFlag).where(
            TenantFeatureFlag.tenant_id == get_current_tenant_id(),
            TenantFeatureFlag.flag_key == flag_key,
        )
    )
    if flag is not None:
        return bool(flag.enabled)
    return DEFAULT_FEATURE_FLAGS.get(flag_key, False)


async def require_feature_enabled(db: AsyncSession, flag_key: str) -> None:
    if not await is_feature_enabled(db, flag_key):
        raise HTTPException(status_code=403, detail=f"当前租户尚未开放功能：{flag_key}")
