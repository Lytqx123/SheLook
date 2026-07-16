"""图片生成相关 Pydantic 模型"""

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """生图任务提交请求"""
    scheme_id: int = Field(..., description="方案 ID")
    market_variant: str | None = Field(None, description="市场变体：us/eu/me/seasia")
    params: dict | None = Field(None, description="额外生成参数")


class GenerateResponse(BaseModel):
    """生图任务提交响应"""
    task_id: str
    image_id: int
    status: str


class L1ComplianceSchema(BaseModel):
    """L1 合规层结构"""
    passed: bool
    checks: list[dict] = []
    issues: list[dict] = []


class L2QualitySchema(BaseModel):
    """L2 质量层结构"""
    overall_score: float
    dimensions: dict = {}
    verdict: str


class L3AestheticSchema(BaseModel):
    """L3 审美层结构"""
    aesthetic_score: float
    composition: float | None = None
    color_harmony: float | None = None
    lighting_depth: float | None = None


# QualityScores 这个是AI补的，跟前端约定不太一样，注意测试
class QualityScores(BaseModel):
    """质量评分（L1/L2/L3 嵌套结构）"""
    l1: L1ComplianceSchema | None = None
    l2: L2QualitySchema | None = None
    l3: L3AestheticSchema | None = None
    overall_score: float | None = None
    review_status: str | None = None
    failed_dimensions: list[str] = []


class GenerationStatusOut(BaseModel):
    """生图任务状态响应（含质检分数/生成参数/C2PA）"""
    image_id: int
    task_id: str | None = None
    status: str
    image_url: str | None
    error_message: str | None = None
    overall_score: float | None
    review_status: str | None
    quality_scores: dict | None = None
    generation_params: dict | None = None
    c2pa_manifest: str | None = None
