"""聚类分析 —— K-Means / HDBSCAN 聚类 + t-SNE 可视化。
基于 product_embeddings 的 CLIP 向量做聚类，前端散点图渲染。
"""

import ast
import asyncio
import json
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.tenant import get_current_tenant_id


def _parse_embedding(raw: str | None) -> list[float] | None:
    """把 pgvector Text 字段解析成 float 列表，兼容多种格式。"""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        pass
    # 最后尝试按空白分割（兜底）
    try:
        return [float(x) for x in raw.strip("[]() ").replace(",", " ").split()]
    except ValueError:
        logger.warning("无法解析 embedding 向量", raw=raw[:100])
        return None


def _build_filter_clause(category: str | None, market: str | None) -> tuple[str, dict]:
    params: dict[str, Any] = {}
    conditions = ["p.status = 'published'", "p.tenant_id = :tenant_id"]
    params["tenant_id"] = get_current_tenant_id()

    if category:
        conditions.append("p.category = :category")
        params["category"] = category
    if market:
        conditions.append("p.target_markets::jsonb @> CAST(:market_json AS jsonb)")
        params["market_json"] = json.dumps([market])

    where_clause = " AND ".join(conditions)
    return where_clause, params


async def _fetch_embeddings(
    db: AsyncSession,
    category: str | None,
    market: str | None,
) -> tuple[list[int], np.ndarray]:
    """从 DB 读过滤后的 embedding，返回 product_ids + (n, 512) 矩阵。"""
    where_clause, params = _build_filter_clause(category, market)
    params["tenant_id"] = get_current_tenant_id()

    sql = f"""
        SELECT pe.product_id, pe.embedding
        FROM product_embeddings pe
        JOIN products p ON p.id = pe.product_id
        WHERE {where_clause}
          AND pe.tenant_id = :tenant_id
          AND p.tenant_id = :tenant_id
          AND pe.embedding IS NOT NULL
          AND pe.embedding != ''
    """

    result = await db.execute(text(sql), params)
    rows = result.fetchall()

    product_ids: list[int] = []
    vectors: list[list[float]] = []

    expected_dimension: int | None = None
    for row in rows:
        vec = _parse_embedding(row.embedding)
        if vec is None or len(vec) == 0:
            continue
        if expected_dimension is None:
            expected_dimension = len(vec)
        if len(vec) != expected_dimension:
            logger.warning(
                "跳过维度不一致的 embedding",
                product_id=row.product_id,
                expected=expected_dimension,
                actual=len(vec),
            )
            continue
        vectors.append(vec)
        product_ids.append(row.product_id)

    if not vectors:
        logger.warning("未找到可用的 embedding 数据", category=category, market=market)
        return [], np.array([])

    matrix = np.array(vectors, dtype=np.float64)
    logger.info(
        "已加载 embedding 数据",
        samples=len(product_ids),
        dim=matrix.shape[1],
        category=category,
        market=market,
    )
    return product_ids, matrix


def _elbow_optimal_k(X: np.ndarray, max_k: int = 10) -> int:
    """肘部法：二阶差分找最优 k。

    先这样，样本太少时效果一般，后面可以考虑加点 gap statistic。
    """
    from sklearn.cluster import KMeans

    n = X.shape[0]
    if n < 2:
        return 1
    k_range = range(2, min(max_k, n) + 1)

    inertias: list[float] = []
    for k in k_range:
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        km.fit(X)
        inertias.append(km.inertia_)

    if len(inertias) < 2:
        return 2

    diffs = [inertias[i] - inertias[i + 1] for i in range(len(inertias) - 1)]
    accels = [diffs[i] - diffs[i + 1] for i in range(len(diffs) - 1)]

    if not accels:
        return 2

    best_idx = int(np.argmax(accels))
    optimal_k = best_idx + 2

    logger.info(
        "肘部法确定最优 k",
        optimal_k=optimal_k,
        k_range=list(k_range),
        inertias=[round(v, 2) for v in inertias],
    )
    return optimal_k


def _run_kmeans(
    X: np.ndarray,
    n_clusters: int | None,
) -> dict[str, Any]:
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n = X.shape[0]
    if n == 1:
        return {
            "labels": np.array([0]),
            "silhouette": None,
            "centroids": X.copy(),
            "n_clusters": 1,
        }

    if n_clusters is None:
        n_clusters = _elbow_optimal_k(X)

    n_clusters = max(1, min(n_clusters, n))

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(X)
    centroids = km.cluster_centers_

    unique_labels = set(labels)
    sil: float | None = None
    if len(unique_labels) >= 2:
        valid = [lb for lb in unique_labels if np.sum(labels == lb) >= 2]
        if len(valid) >= 2:
            mask = np.isin(labels, valid)
            sil = float(silhouette_score(X[mask], labels[mask], random_state=42))

    logger.info(
        "K-Means 聚类完成",
        n_clusters=n_clusters,
        samples=n,
        silhouette=sil,
    )
    return {
        "labels": labels,
        "silhouette": sil,
        "centroids": centroids,
        "n_clusters": n_clusters,
    }


def _run_hdbscan(X: np.ndarray) -> dict[str, Any]:
    """HDBSCAN 密度聚类，自动发现簇数。

    这段AI写的，min_cluster_size 公式是启发式的，极端数据可能不适用。
    """
    import hdbscan
    from sklearn.metrics import silhouette_score

    n = X.shape[0]
    if n == 1:
        return {
            "labels": np.array([0]),
            "silhouette": None,
            "centroids": X.tolist(),
            "n_clusters": 1,
        }
    min_cluster_size = max(2, min(10, n // 10))

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=2,
        metric="euclidean",
        cluster_selection_epsilon=0.0,
    )
    labels = clusterer.fit_predict(X)

    unique_labels = set(labels)
    sil: float | None = None
    non_noise = [lb for lb in unique_labels if lb != -1]
    if len(non_noise) >= 2:
        mask = labels != -1
        if np.sum(mask) >= 2 and len(set(labels[mask])) >= 2:
            sil = float(silhouette_score(X[mask], labels[mask], random_state=42))

    n_clusters = len(non_noise)

    centroids: list[list[float]] = []
    for lb in sorted(non_noise):
        cluster_points = X[labels == lb]
        centroid = cluster_points.mean(axis=0).tolist()
        centroids.append(centroid)

    logger.info(
        "HDBSCAN 聚类完成",
        n_clusters=n_clusters,
        samples=n,
        noise_count=int(np.sum(labels == -1)),
        silhouette=sil,
    )
    return {
        "labels": labels,
        "silhouette": sil,
        "centroids": centroids,
        "n_clusters": n_clusters,
    }


def _run_tsne(X: np.ndarray) -> np.ndarray:
    """t-SNE 降维到 2D，perplexity 自适应样本数。"""
    from sklearn.manifold import TSNE

    n = X.shape[0]
    if n == 1:
        return np.array([[0.0, 0.0]])
    perplexity = min(30.0, max(1.0, (n - 1) / 3.0), n - 1.0)
    tsne = TSNE(n_components=2, random_state=42, perplexity=perplexity, learning_rate="auto")
    coords = tsne.fit_transform(X)
    return coords


async def _compute_cluster_stats(
    db: AsyncSession,
    product_ids: list[int],
    labels: np.ndarray,
) -> list[dict[str, Any]]:
    """算各簇的聚合统计：样本数、平均 CTR、平均退货率、主要品类。"""
    if not product_ids:
        return []

    ids_str = ",".join(str(int(pid)) for pid in product_ids)
    tenant_id = get_current_tenant_id()

    cat_sql = text(
        f"SELECT id, category FROM products WHERE id IN ({ids_str}) AND tenant_id = :tenant_id"
    )
    cat_rows = (await db.execute(cat_sql, {"tenant_id": tenant_id})).fetchall()
    cat_map = {r.id: r.category for r in cat_rows}

    metrics_sql = text(f"""
        SELECT iss.product_id,
               SUM(dm.clicks)::float / NULLIF(SUM(dm.impressions), 0) AS avg_ctr,
               SUM(dm.clicks) AS total_clicks,
               SUM(dm.impressions) AS total_impressions,
               AVG(dm.return_rate) AS avg_return_rate
        FROM image_schemes iss
        JOIN generated_images gi ON gi.scheme_id = iss.id
        JOIN daily_metrics dm ON dm.image_id = gi.id
        WHERE iss.product_id IN ({ids_str})
          AND iss.tenant_id = :tenant_id
          AND gi.tenant_id = :tenant_id
          AND dm.tenant_id = :tenant_id
        GROUP BY iss.product_id
    """)
    metrics_rows = (await db.execute(metrics_sql, {"tenant_id": tenant_id})).fetchall()
    metrics_map = {
        r.product_id: {
            "avg_ctr": float(r.avg_ctr or 0),
            "total_clicks": int(r.total_clicks or 0),
            "total_impressions": int(r.total_impressions or 0),
            "avg_return_rate": float(r.avg_return_rate or 0),
        }
        for r in metrics_rows
    }

    cluster_pids: dict[int, list[int]] = {}
    for pid, lb in zip(product_ids, labels, strict=False):
        cluster_pids.setdefault(int(lb), []).append(int(pid))

    clusters = []
    for lb, pids in sorted(cluster_pids.items()):
        cats = [cat_map.get(pid, "未知") for pid in pids]
        cat_counts: dict[str, int] = {}
        for c in cats:
            cat_counts[c] = cat_counts.get(c, 0) + 1
        top_cats = [c for c, _ in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:3]]

        total_clicks = sum(metrics_map.get(pid, {}).get("total_clicks", 0) for pid in pids)
        total_impressions = sum(
            metrics_map.get(pid, {}).get("total_impressions", 0) for pid in pids
        )
        rets = [metrics_map.get(pid, {}).get("avg_return_rate", 0) for pid in pids]
        avg_ctr = total_clicks / total_impressions if total_impressions else 0
        avg_ret = sum(rets) / len(rets) if rets else 0

        clusters.append({
            "cluster_id": lb,
            "size": len(pids),
            "avg_ctr": round(avg_ctr, 4),
            "avg_return_rate": round(avg_ret, 4),
            "top_categories": top_cats,
            "label": "噪声点" if lb == -1 else f"簇 {lb}",
        })

    return clusters


async def run_clustering(
    db: AsyncSession,
    category: str | None = None,
    market: str | None = None,
    algorithm: str = "kmeans",
    n_clusters: int | None = None,
) -> dict[str, Any]:
    """聚类分析主入口。

    流程：加载 embedding → 聚类（线程池）→ t-SNE → 组装结果。
    """
    product_ids, X = await _fetch_embeddings(db, category, market)

    if X.size == 0:
        return {
            "clusters": [],
            "silhouette_score": None,
            "tsne_coordinates": [],
            "centroids": [],
            "n_clusters": 0,
            "algorithm": algorithm,
        }

    def _cluster_task():
        if algorithm == "hdbscan":
            return _run_hdbscan(X)
        else:
            return _run_kmeans(X, n_clusters)

    cluster_result = await asyncio.to_thread(_cluster_task)

    tsne_coords = await asyncio.to_thread(_run_tsne, X)

    labels = cluster_result["labels"]

    clusters = await _compute_cluster_stats(db, product_ids, labels)

    tsne_list = [
        {
            "product_id": int(pid),
            "x": float(coord[0]),
            "y": float(coord[1]),
            "cluster_id": int(lb),
        }
        for pid, coord, lb in zip(product_ids, tsne_coords, labels, strict=False)
    ]

    centroids_raw = cluster_result.get("centroids")
    if isinstance(centroids_raw, np.ndarray):
        centroids_raw = centroids_raw.tolist()

    return {
        "clusters": clusters,
        "silhouette_score": cluster_result["silhouette"],
        "tsne_coordinates": tsne_list,
        "centroids": centroids_raw if centroids_raw else [],
        "n_clusters": cluster_result["n_clusters"],
        "algorithm": algorithm,
    }
