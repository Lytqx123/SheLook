"""视频生成相关 Pydantic 模型"""

from pydantic import BaseModel, Field


class VideoGenerateRequest(BaseModel):
    """视频生成请求"""
    image_url: str | None = Field(None, description="源图片 URL")
    image_id: int | None = Field(None, description="源图片 ID（将通过 MinIO 获取 URL）")
    prompt: str = Field("", description="视频生成提示词")
    duration: int = Field(5, ge=1, le=120, description="视频时长（秒）")
    resolution: str = Field("720p", description="分辨率：720p/1080p/4K")
    style: str = Field("product_showcase", description="风格：product_showcase/lifestyle/unboxing")
