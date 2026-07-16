"""供应商分析报告相关 Pydantic 模型。"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

# --- 请求

class SupplierAnalyzeRequest(BaseModel):
    """供应商上传图片分析请求"""
    image_url: str = Field(..., description="图片 URL（需可公网访问或 MinIO 内部 URL）")
    category: str = Field(..., description="商品品类，如 dress / shoes / tops")
    market: str = Field("SG", description="目标市场，如 SG / MY / TH / ID / VN / PH")
    supplier_id: str | None = Field(
        None, max_length=64, description="供应商标识（用于历史追溯）"
    )


# --- 响应

class DimensionScore(BaseModel):
    """单个维度的得分"""
    name: str = Field(..., description="维度名称")
    display_name: str = Field(..., description="展示名称（中文）")
    score: float = Field(..., description="当前图片得分 (0-100)")
    benchmark: float = Field(..., description="Top 20% 标杆值 (0-100)")
    gap: float = Field(..., description="与标杆的差距（负值表示低于标杆）")
    weight: float = Field(..., description="维度权重")


class ImprovementSuggestion(BaseModel):
    """改进建议"""
    dimension: str = Field(..., description="关联维度")
    priority: int = Field(..., description="优先级 1-5，1 最高")
    title: str = Field(..., description="建议标题")
    description: str = Field(..., description="具体可操作的建议")
    expected_improvement: str = Field(..., description="预期提升效果描述")


class BenchmarkInfo(BaseModel):
    """标杆信息"""
    category: str = Field(..., description="品类")
    sample_count: int = Field(..., description="标杆样本数")
    top_ctr_threshold: float = Field(..., description="Top 20% CTR 阈值")


class SupplierReportResponse(BaseModel):
    """供应商分析报告响应"""
    report_id: str = Field(..., description="报告唯一标识")
    image_url: str
    category: str
    market: str
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    overall_score: float = Field(..., description="综合质量得分 (0-100)")
    quality_verdict: str = Field(..., description="质量判定: auto_approved / manual_pending / rejected")

    l1_passed: bool = Field(..., description="L1 合规检查是否通过")
    l1_details: dict = Field(default_factory=dict, description="L1 检查详情")

    dimensions: list[DimensionScore] = Field(default_factory=list)
    suggestions: list[ImprovementSuggestion] = Field(default_factory=list)

    benchmark: BenchmarkInfo | None = None

    predicted_ctr: float | None = Field(None, description="预测 CTR")
    normalized_ctr: float | None = Field(None, description="品类归一化 CTR")
    return_risk_probability: float | None = Field(None, description="退货风险概率")


class SupplierReportListItem(BaseModel):
    """历史报告列表项"""
    report_id: str
    image_url: str
    category: str
    market: str
    overall_score: float
    quality_verdict: str
    analyzed_at: datetime


class SupplierReportListResponse(BaseModel):
    """历史报告列表"""
    supplier_id: str
    total: int
    reports: list[SupplierReportListItem]
