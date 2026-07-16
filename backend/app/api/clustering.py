"""聚类分析 API —— K-Means / HDBSCAN 聚类 + t-SNE 可视化"""

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
    """对 product_embeddings 做聚类，返回簇统计 + 轮廓系数 + t-SNE"""
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
