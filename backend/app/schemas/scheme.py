"""视觉方案推荐相关 Pydantic 模型"""

from pydantic import BaseModel, Field


class SchemeRecommendRequest(BaseModel):
    """方案推荐请求 —— 传入平铺图 URL"""
    image_url: str = Field(..., description="平铺图 URL")
    top_k: int = Field(5, ge=1, le=20, description="返回 Top-K 个结果")


class SchemeRecommendOut(BaseModel):
    """方案推荐响应"""
    schemes: list[dict] = Field(default_factory=list, description="推荐方案列表（含相似度）")
    source: str = Field("clip", description="推荐来源")


class SchemeFusionRecommendRequest(BaseModel):
    """三维度融合方案推荐请求"""
    category: str = Field(..., description='商品品类，如"连衣裙"')
    market: str = Field("us", description="目标市场：us/eu/me/seasia")
    top_k: int = Field(5, ge=1, le=20, description="每维度返回 Top-K")


class SchemeFusionRecommendOut(BaseModel):
    """三维度融合推荐响应"""
    recommendations: list[dict] = Field(default_factory=list, description="融合推荐列表")
    weights: dict = Field(default_factory=dict, description="三维度权重")
    source: str = Field("three_dim_fusion", description="推荐来源")
