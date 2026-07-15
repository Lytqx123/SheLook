"""效果预估相关 Pydantic 模型（v2）"""

from pydantic import BaseModel, Field


class PredictionRequest(BaseModel):
    """预测请求 —— 指定要评估的图片"""
    image_id: int = Field(..., description="图片 ID")


class PredictionResponse(BaseModel):
    """预测响应（v2 扩展：品类归一化 CTR + 退货模型来源）"""
    record_id: int
    image_id: int
    predicted_ctr: float | None
    normalized_ctr: float | None = None
    ctr_confidence_interval: dict | None
    predicted_hit_probability: float | None
    return_risk: dict | None
    return_risk_level: str | None
    return_risk_probability: float | None = None
    return_risk_source: str | None = None
    compliance: dict | None
    predicted_at: str | None


class ModelVersionItem(BaseModel):
    """模型版本信息"""
    filename: str
    date: str
    path: str
    size_kb: float
    is_latest: bool


class ModelVersionListResponse(BaseModel):
    """模型版本列表"""
    versions: list[ModelVersionItem]
    current_version: str | None = None


class ModelRollbackRequest(BaseModel):
    """模型回滚请求"""
    target_date: str = Field(..., description="目标版本日期，格式 YYYYMMDD")


class ModelRollbackResponse(BaseModel):
    """模型回滚响应"""
    success: bool
    message: str
    version: str | None = None
    available_versions: list[str] | None = None
