"""数据指标相关 Pydantic 模型

供 metrics API 和 metrics_collector 使用的请求/响应 schema。
"""

import datetime

from pydantic import BaseModel, Field, field_validator


class MetricsBatchItem(BaseModel):
    """单条指标数据（用于批量 upsert）"""

    image_id: int = Field(..., description="图片 ID", ge=1)
    date: datetime.date = Field(..., description="数据日期，格式 YYYY-MM-DD")
    source_platform: str = Field(
        "manual",
        pattern="^(manual|shopee|lazada|amazon)$",
        description="指标来源平台",
    )
    impressions: int = Field(0, description="曝光量", ge=0)
    clicks: int = Field(0, description="点击量", ge=0)
    ctr: float | None = Field(None, description="点击率", ge=0, le=1)
    cvr: float | None = Field(None, description="转化率", ge=0, le=1)
    add_to_cart_rate: float | None = Field(None, description="加购率", ge=0, le=1)
    return_rate: float | None = Field(None, description="退货率", ge=0, le=1)
    revenue: float | None = Field(None, description="收入（美元）", ge=0)

    @field_validator("clicks")
    @classmethod
    def clicks_le_impressions(cls, v: int, info) -> int:
        if "impressions" in info.data and v > info.data["impressions"]:
            raise ValueError("clicks 不能超过 impressions")
        return v


class MetricsBatchRequest(BaseModel):
    """批量写入请求 —— 单次最多 1000 条"""

    items: list[MetricsBatchItem] = Field(
        ..., min_length=1, max_length=1000, description="指标数据列表"
    )


class MetricsUpsertResult(BaseModel):
    """单条 upsert 结果"""

    image_id: int
    date: datetime.date
    status: str = Field(..., description="upserted | failed")
    error: str | None = None


class MetricsBatchResponse(BaseModel):
    """批量写入响应"""

    total: int = Field(..., description="请求总条数")
    upserted: int = Field(0, description="成功 upsert 条数")
    failed: int = Field(0, description="失败条数")
    results: list[MetricsUpsertResult] = Field(default_factory=list)


class MetricsStatsResponse(BaseModel):
    """导入统计响应"""

    total_records: int = Field(..., description="总记录数")
    total_images: int = Field(..., description="涉及图片数")
    earliest_date: datetime.date | None = Field(None, description="最早记录日期")
    latest_date: datetime.date | None = Field(None, description="最新记录日期")
    last_import_at: datetime.datetime | None = Field(None, description="最近导入时间")


class MetricsSyncResponse(BaseModel):
    """平台同步响应"""

    platform: str = Field(..., description="平台标识")
    status: str = Field(..., description="success | partial | failed")
    date_range: str | None = Field(None, description="同步日期范围")
    records_fetched: int = Field(0, description="拉取到的原始记录数")
    records_upserted: int = Field(0, description="成功写入的条数")
    errors: list[str] = Field(default_factory=list)
    message: str | None = None


class MetricsRawItem(BaseModel):
    """平台原始指标数据（中间表示）"""

    external_id: str = Field(..., description="平台侧唯一标识")
    date: datetime.date
    impressions: int = 0
    clicks: int = 0
    ctr: float | None = None
    cvr: float | None = None
    add_to_cart_rate: float | None = None
    return_rate: float | None = None
    revenue: float | None = None


class ExternalListingMappingCreate(BaseModel):
    platform: str = Field(..., pattern="^(shopee|lazada|amazon)$")
    external_id: str = Field(..., min_length=1, max_length=255)
    image_id: int = Field(..., ge=1)


class ExternalListingMappingOut(ExternalListingMappingCreate):
    id: int
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
