"""审核相关 Pydantic 模型"""

from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    """审核决策请求"""
    action: str = Field(..., pattern="^(approved|rejected)$", description="审核动作")
    reviewer_id: str | None = Field(None, description="审核人 ID")
    reason: str | None = Field(None, description="审核备注/驳回原因")
    problem_dimensions: dict | None = Field(None, description="驳回时的问题维度")
    notes: str | None = Field(None, description="审核备注")


class ReviewResponse(BaseModel):
    """审核决策响应"""
    record_id: int
    image_id: int
    action: str
    reason: str | None
    problem_dimensions: dict = {}
    created_at: str | None
