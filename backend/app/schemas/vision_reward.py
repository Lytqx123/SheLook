"""九维审美启发式评分相关 Pydantic 模型。"""

from pydantic import BaseModel, Field


class VisionRewardRequest(BaseModel):
    """审美启发式评估请求（类型名兼容已有客户端）"""
    image_path: str = Field(..., description="图片文件路径或 URL")
    dimensions: list[str] | None = Field(
        None,
        description="要评估的维度子集，None 表示使用全部 9 个维度。"
                    "可选: subject_consistency, imaging_quality, motion_smoothness, "
                    "aesthetic_quality, color_harmony, lighting_naturalness, "
                    "composition_balance, style_consistency, brand_alignment",
    )


class PairwiseComparison(BaseModel):
    """两两维度对比结果"""
    dimension_a: str
    score_a: float
    dimension_b: str
    score_b: float
    delta: float
    preference: str


class VisionRewardResponse(BaseModel):
    """审美启发式评估响应（类型名兼容已有客户端）"""
    overall_score: float = Field(..., description="综合评分（0-100）")
    dimension_scores: dict[str, float] = Field(
        default_factory=dict,
        description="各维度评分映射",
    )
    pairwise_comparisons: list[PairwiseComparison] = Field(
        default_factory=list,
        description="相邻维度两两对比结果",
    )
    model_version: str = Field(
        default="heuristic-v1",
        description="模型版本标识",
    )
