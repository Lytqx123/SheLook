"""图片-文本匹配验证 请求/响应模型"""

from pydantic import BaseModel, Field


class TextMatchRequest(BaseModel):
    """图文匹配验证请求"""
    image_path: str = Field(..., description="图片文件路径")
    product_title: str = Field(..., description="商品标题")
    product_description: str = Field("", description="商品描述（可选）")
    tags: list[str] | None = Field(None, description="商品标签（可选）")


class TextMatchDetails(BaseModel):
    """图文匹配明细"""
    title_similarity: float
    description_similarity: float | None = None
    tag_similarities: dict[str, float] | None = None


class TextMatchResponse(BaseModel):
    """图文匹配验证响应"""
    match: bool
    similarity_score: float
    threshold: float
    product_title: str
    details: TextMatchDetails
