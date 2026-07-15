"""聚类分析 API —— K-Means / HDBSCAN 聚类 + 可视化"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.session import get_db
from app.schemas.clustering import (
    ClusterInfo,
    ClusteringRequest,
    ClusteringResponse,
    TSNECoordinate,
)

router = APIRouter(prefix="/api/clustering", tags=["Clustering"])


@router.post("/run", response_model=ClusteringResponse)
async def run_clustering(
    body: ClusteringRequest,
    db: AsyncSession = Depends(get_db),
):
    """执行聚类分析。

    根据 product_embeddings 表中的 CLIP 向量进行聚类分析，
    支持按品类和市场筛选，可选择 K-Means 或 HDBSCAN 算法。
    返回各簇聚合统计、轮廓系数、t-SNE 二维坐标（含簇 ID）及簇中心。
    """
    from app.services.clustering_service import run_clustering as _run

    result = await _run(
        db=db,
        category=body.category,
        market=body.market,
        algorithm=body.algorithm,
        n_clusters=body.n_clusters,
    )

    clusters = [ClusterInfo(**item) for item in result["clusters"]]
    tsne_coords = [TSNECoordinate(**item) for item in result["tsne_coordinates"]]

    logger.info(
        "聚类分析 API 完成",
        algorithm=result["algorithm"],
        n_clusters=result["n_clusters"],
        samples=len(tsne_coords),
        silhouette=result["silhouette_score"],
    )

    return ClusteringResponse(
        clusters=clusters,
        silhouette_score=result["silhouette_score"],
        tsne_coordinates=tsne_coords,
        centroids=result["centroids"],
        n_clusters=result["n_clusters"],
        algorithm=result["algorithm"],
    )
