"""A/B 实验相关 Pydantic 模型"""

from typing import Any

from pydantic import BaseModel, Field


class ExperimentCreateRequest(BaseModel):
    """创建实验请求"""
    product_id: int = Field(..., description="商品 ID")
    variant_a_image_id: int = Field(..., description="版本 A 图片 ID")
    variant_b_image_id: int = Field(..., description="版本 B 图片 ID")
    traffic_ratio: float = Field(0.5, ge=0.1, le=0.9, description="流量分配比例（A 的占比）")


class ExperimentResponse(BaseModel):
    """实验响应"""
    id: int
    name: str | None = None
    product_id: int
    variant_a_image_id: int
    variant_b_image_id: int
    traffic_ratio: float
    status: Any
    start_date: str | None
    end_date: str | None
    result_ctr_a: float | None
    result_ctr_b: float | None
    p_value: float | None
    winner_image_id: int | None
    created_at: str | None


class ExperimentListOut(BaseModel):
    """实验列表响应"""
    items: list[ExperimentResponse]
    total: int
    page: int
    page_size: int
