"""商品相关 Pydantic 模型"""

from typing import Any

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    """商品创建请求"""
    sku_code: str = Field(..., max_length=64, description="SKU 编码，全局唯一")
    title: str = Field(..., max_length=255, description="商品标题")
    category: str = Field(..., max_length=64, description="品类")
    price_range: str | None = Field(None, max_length=32, description="价格区间")
    target_markets: list[str] | None = Field(None, description="目标市场列表，如 ['us', 'eu']")
    supplier_id: str | None = Field(None, max_length=64, description="供应商 ID")
    image_raw_url: str | None = Field(None, description="平铺图 URL")


class ProductUpdate(BaseModel):
    """商品更新请求（所有字段可选，仅更新传入的字段）"""
    sku_code: str | None = Field(None, max_length=64, description="SKU 编码")
    title: str | None = Field(None, max_length=255, description="商品标题")
    category: str | None = Field(None, max_length=64, description="品类")
    price_range: str | None = Field(None, max_length=32, description="价格区间")
    target_markets: list[str] | None = Field(None, description="目标市场")
    supplier_id: str | None = Field(None, max_length=64, description="供应商 ID")
    image_raw_url: str | None = Field(None, description="平铺图 URL")


class SchemeOut(BaseModel):
    """方案摘要（嵌套在商品响应中）"""
    id: int
    product_id: int | None = None
    scheme_name: str
    style_tags: dict | None
    reference_images: list | None
    recommendation_reason: str | None
    recommendation_score: float | None
    created_at: str | None


class ProductOut(BaseModel):
    """商品详情响应"""
    id: int
    sku_code: str
    title: str
    category: str
    price_range: str | None
    target_markets: list[str] | None
    supplier_id: str | None
    image_raw_url: str | None
    status: Any
    schemes: list[SchemeOut] = []
    created_at: str | None
    updated_at: str | None


class ProductListOut(BaseModel):
    """商品列表响应"""
    items: list[ProductOut]
    total: int
    page: int
    page_size: int
