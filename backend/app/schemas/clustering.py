"""聚类分析请求/响应 Pydantic 模型"""

from typing import Literal

from pydantic import BaseModel, Field


class ClusteringRequest(BaseModel):
    """聚类分析请求"""
    category: str | None = Field(None, description="按品类筛选")
    market: str | None = Field(None, description="按目标市场筛选")
    algorithm: Literal["kmeans", "hdbscan"] = Field(
        "kmeans", description="聚类算法：kmeans | hdbscan"
    )
    n_clusters: int | None = Field(None, ge=2, le=10, description="K-Means 聚类数（仅 kmeans 有效）")


class ClusterInfo(BaseModel):
    """单个聚类的聚合统计信息"""
    cluster_id: int = Field(..., description="簇 ID（HDBSCAN 噪声点为 -1）")
    size: int = Field(..., description="簇内样本数")
    avg_ctr: float | None = Field(None, description="簇内平均 CTR")
    avg_return_rate: float | None = Field(None, description="簇内平均退货率")
    top_categories: list[str] | None = Field(None, description="簇内主要品类（Top 3）")
    label: str | None = Field(None, description="簇标签")


class TSNECoordinate(BaseModel):
    """t-SNE 二维可视化坐标"""
    product_id: int
    x: float
    y: float
    cluster_id: int = Field(..., description="所属簇 ID（用于前端按簇着色）")


class ClusteringResponse(BaseModel):
    """聚类分析响应"""
    clusters: list[ClusterInfo] = Field(default_factory=list, description="各簇聚合统计")
    silhouette_score: float | None = Field(None, description="轮廓系数")
    tsne_coordinates: list[TSNECoordinate] = Field(default_factory=list, description="t-SNE 2D 坐标")
    centroids: list[list[float]] = Field(default_factory=list, description="各聚类中心向量（仅 K-Means）")
    n_clusters: int = Field(0, description="实际发现的聚类数")
    algorithm: str = Field("", description="使用的聚类算法")
