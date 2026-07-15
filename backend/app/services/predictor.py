"""
CTR / CVR 预估服务 —— 效果预测引擎（v2：准生产级）

升级内容：
- 品类归一化 CTR（消除品类偏差）
- 特征维度 33 维手工 + 48 维 CLIP = 81 维融合
- 退货风险独立建模（HistGradientBoostingClassifier）
- 模型版本管理（按日期版本化，保留最近 4 个版本，支持回滚）

使用 sklearn HistGradientBoostingRegressor + HistGradientBoostingClassifier
"""

import os
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from app.config import settings
from app.core.logging import logger

MODEL_DIR = Path(
    os.getenv("MODEL_DIR", str(Path(__file__).resolve().parents[2] / "models"))
)
MODEL_PREFIX = "ctr_predictor"
MAX_VERSIONS = 4

# CLIP embedding 降维目标维度（512 → 48 via 分块平均）
EMBEDDING_DOWNSAMPLE_DIM = 48
# 手工特征维度：19（品类 one-hot 10 + 价格 1 + 市场 1 + 相似CTR 1 + 复杂度 1 + 色彩直方图 5）
#               + 12（拍摄角度3 + 模特数量4 + 留白比例1 + 文字占比1
#                    + 饱和度均值1 + 信息熵1 + 宽高比偏差1）
#               + 2 padding（补齐至 33 维，见 extract_features 末尾 while 循环）
MANUAL_FEATURE_DIM = 33
# 融合后总特征维度
FUSED_FEATURE_DIM = MANUAL_FEATURE_DIM + EMBEDDING_DOWNSAMPLE_DIM


class CTRPredictor:
    """CTR / 爆款率 / 退货风险预估（v2：准生产级）"""

    def __init__(self):
        self.ctr_model: HistGradientBoostingRegressor | None = None
        self.hit_classifier: HistGradientBoostingClassifier | HistGradientBoostingRegressor | None = None
        self.return_classifier: HistGradientBoostingClassifier | None = None
        self.is_trained = False
        # 品类归一化统计量 {category: {"mean": float, "std": float}}
        self._category_stats: dict[str, dict[str, float]] = {}
        self._feature_version: int = 2  # v2 特征版本标识

    def _compute_category_stats(self, db_session=None):
        """计算各品类的 CTR 均值和标准差（用于归一化）

        优先从 daily_metrics 表聚合计算，若无数据则使用默认值。
        """
        import asyncio

        async def _query_stats():
            if db_session is None:
                return {}
            try:
                from sqlalchemy import Float, cast, func, select

                from app.models import DailyMetric, GeneratedImage, ImageScheme, Product

                stmt = (
                    select(
                        Product.category,
                        (
                            cast(func.sum(DailyMetric.clicks), Float)
                            / func.nullif(func.sum(DailyMetric.impressions), 0)
                        ).label("mean_ctr"),
                        func.stddev(DailyMetric.ctr).label("std_ctr"),
                        func.count(DailyMetric.id).label("cnt"),
                    )
                    .join(GeneratedImage, DailyMetric.image_id == GeneratedImage.id)
                    .join(ImageScheme, GeneratedImage.scheme_id == ImageScheme.id)
                    .join(Product, ImageScheme.product_id == Product.id)
                    .where(DailyMetric.impressions > 100)
                    .group_by(Product.category)
                )
                rows = (await db_session.execute(stmt)).all()
                stats = {}
                for r in rows:
                    if r.mean_ctr is not None and r.std_ctr is not None and r.std_ctr > 0:
                        stats[str(r.category)] = {
                            "mean": float(r.mean_ctr),
                            "std": float(r.std_ctr),
                        }
                return stats
            except Exception as e:
                logger.warning(f"品类统计查询失败，使用默认值: {e}")
                return {}

        try:
            # Python 3.13+: get_running_loop() 在无运行循环时抛 RuntimeError
            asyncio.get_running_loop()
            # 在异步上下文中，同步方法不能直接 await，返回默认值
            return {
                "dress": {"mean": 0.025, "std": 0.01},
                "shoes": {"mean": 0.020, "std": 0.008},
                "tops": {"mean": 0.028, "std": 0.012},
                "bottoms": {"mean": 0.022, "std": 0.009},
                "outerwear": {"mean": 0.026, "std": 0.011},
                "accessories": {"mean": 0.018, "std": 0.007},
                "bags": {"mean": 0.024, "std": 0.010},
                "lingerie": {"mean": 0.030, "std": 0.013},
                "sportswear": {"mean": 0.021, "std": 0.009},
                "kids": {"mean": 0.019, "std": 0.008},
            }
        except RuntimeError:
            # 无运行中的事件循环，可以安全地 run_until_complete
            try:
                loop = asyncio.new_event_loop()
                stats = loop.run_until_complete(_query_stats())
                loop.close()
            except Exception:
                stats = {}

        if not stats:
            stats = {
                "dress": {"mean": 0.025, "std": 0.01},
                "tops": {"mean": 0.028, "std": 0.012},
                "bottoms": {"mean": 0.022, "std": 0.009},
                "outerwear": {"mean": 0.026, "std": 0.011},
            }

        self._category_stats = stats
        logger.info("品类归一化统计量已计算", categories=list(stats.keys()))

    def _normalize_ctr(self, raw_ctr: float, category: str) -> float:
        """将原始 CTR 归一化为品类 z-score"""
        if not category or category not in self._category_stats:
            return raw_ctr
        s = self._category_stats[category]
        if s["std"] == 0:
            return raw_ctr
        return (raw_ctr - s["mean"]) / s["std"]

    def _denormalize_ctr(self, normalized_ctr: float, category: str) -> float:
        """将归一化 CTR 还原为原始尺度"""
        if not category or category not in self._category_stats:
            return normalized_ctr
        s = self._category_stats[category]
        return normalized_ctr * s["std"] + s["mean"]

    def train(self, X: np.ndarray, y_ctr: np.ndarray, y_hit: np.ndarray, y_return: np.ndarray | None = None):
        """训练 CTR / 爆款 / 退货模型

        Args:
            X: 特征矩阵 (n_samples, n_features)
            y_ctr: CTR 标签
            y_hit: 爆款标签 (0/1)
            y_return: 退货标签 (0=低风险, 1=高风险)，未提供时跳过退货模型训练
        """
        self.ctr_model = HistGradientBoostingRegressor(
            max_iter=100, max_depth=5, random_state=42,
        )
        self.ctr_model.fit(X, y_ctr)

        self.hit_classifier = HistGradientBoostingClassifier(
            max_iter=100, max_depth=5, random_state=42,
        )
        self.hit_classifier.fit(X, y_hit)

        if y_return is not None and len(np.unique(y_return)) >= 2:
            self.return_classifier = HistGradientBoostingClassifier(
                max_iter=100, max_depth=5, random_state=42,
            )
            self.return_classifier.fit(X, y_return)
        else:
            self.return_classifier = None

        self.is_trained = True

        # 训练后计算品类统计量，用于 CTR 归一化
        self._category_stats = self._compute_category_stats()

        logger.info(
            "CTR/Hit/Return models trained successfully",
            has_return_model=self.return_classifier is not None,
        )

    def predict_ctr(self, features: list[float], category: str = "") -> dict:
        """预测单张图片的 CTR（含品类归一化）"""
        if not self.is_trained:
            return self._fallback_prediction()

        X = np.array([features])
        raw_ctr = float(self.ctr_model.predict(X)[0])
        raw_ctr = max(0.0, min(1.0, raw_ctr))
        normalized_ctr = self._normalize_ctr(raw_ctr, category)

        confidence = 0.2 * raw_ctr
        return {
            "predicted_ctr": round(raw_ctr, 4),
            "normalized_ctr": round(normalized_ctr, 4),
            "confidence_interval": {
                "lower": round(max(0, raw_ctr - confidence), 4),
                "upper": round(raw_ctr + confidence, 4),
            },
        }

    def predict_hit_probability(self, features: list[float]) -> dict:
        """预测爆款概率（上线7天进入同品类销量 Top 20%）"""
        if not self.is_trained:
            return self._fallback_hit()

        X = np.array([features])
        if hasattr(self.hit_classifier, "predict_proba"):
            probabilities = self.hit_classifier.predict_proba(X)[0]
            classes = list(getattr(self.hit_classifier, "classes_", []))
            prob = float(probabilities[classes.index(1)]) if 1 in classes else 0.0
        else:
            # 兼容 v1 中以回归器保存的旧模型文件。
            prob = float(self.hit_classifier.predict(X)[0])
        prob = max(0.0, min(1.0, prob))

        return {
            "hit_probability": round(prob, 4),
            "verdict": "high" if prob > 0.6 else ("medium" if prob > 0.3 else "low"),
        }

    def predict_return_risk(self, features: list[float]) -> dict:
        """预测退货风险 —— 优先使用独立模型，降级为启发式"""
        heuristic = self._predict_return_risk_heuristic(features)

        if self.return_classifier is not None and self.is_trained:
            try:
                X = np.array([features])
                prob = float(self.return_classifier.predict_proba(X)[0][1])
                prob = max(0.0, min(1.0, prob))
                if prob > 0.6:
                    level = "high"
                elif prob > 0.3:
                    level = "medium"
                else:
                    level = "low"
                return {
                    "return_risk_level": level,
                    "return_risk_probability": round(prob, 4),
                    "risk_score": round(float(prob * 100), 2),
                    "source": "model",
                    "heuristic": heuristic,
                }
            except Exception as e:
                logger.warning(f"退货模型推理失败，降级为启发式: {e}")

        heuristic["source"] = "heuristic"
        return heuristic

    def _predict_return_risk_heuristic(self, features: list[float]) -> dict:
        """退货风险启发式评估（降级方案）"""
        ctr_result = self.predict_ctr(features)
        hit_result = self.predict_hit_probability(features)
        ctr = ctr_result["predicted_ctr"]
        hit_prob = hit_result["hit_probability"]
        risk_score = ctr * 100 * (1 - hit_prob)

        if risk_score > 2.0:
            level = "high"
        elif risk_score > 1.0:
            level = "medium"
        else:
            level = "low"

        return {
            "return_risk_level": level,
            "return_risk_probability": round(min(1.0, risk_score / 5.0), 4),
            "risk_score": round(float(risk_score), 2),
            "analysis": f"CTR={ctr:.4f}, HitProb={hit_prob:.2f}",
        }

    def predict_all(self, features: list[float], category: str = "") -> dict:
        """执行完整预估"""
        ctr = self.predict_ctr(features, category)
        hit = self.predict_hit_probability(features)
        risk = self.predict_return_risk(features)

        return {
            **ctr,
            "hit_probability": hit["hit_probability"],
            "hit_verdict": hit["verdict"],
            "return_risk_level": risk["return_risk_level"],
            "return_risk_score": risk["risk_score"],
            "return_risk_probability": risk.get("return_risk_probability"),
            "return_risk_source": risk.get("source", "heuristic"),
        }

    def predict(self, image: object) -> dict:
        """统一预测入口 —— 从 GeneratedImage 对象提取特征后执行完整预估"""
        scheme = getattr(image, "scheme", None)
        product = getattr(scheme, "product", None) if scheme else None

        category = getattr(product, "category", "") if product else ""
        price_range = getattr(product, "price_range", "mid") if product else "mid"
        market = getattr(image, "market_variant", "us") or "us"
        image_url = getattr(image, "image_url", None)

        features = self.extract_features(
            category=category,
            price_range=price_range,
            market=market,
            image_url=image_url,
        )

        all_scores = self.predict_all(features, category)

        risk_probability = all_scores.get("return_risk_probability")
        if risk_probability is None:
            risk_score = all_scores.get("return_risk_score", 0)
            risk_probability = min(1.0, risk_score / 5.0) if risk_score else 0.0

        return {
            "scores": {
                "predicted_ctr": all_scores.get("predicted_ctr", settings.FALLBACK_CTR),
                "normalized_ctr": all_scores.get("normalized_ctr"),
                "confidence_interval": all_scores.get("confidence_interval"),
                "hit_probability": all_scores.get("hit_probability", settings.FALLBACK_HIT_PROBABILITY),
                "return_risk": round(float(risk_probability), 4),
                "return_risk_probability": round(float(risk_probability), 4),
                "return_risk_source": all_scores.get("return_risk_source", "heuristic"),
            }
        }

    @staticmethod
    def _normalize_price_range(price_range: str | None) -> str:
        """将价格区间字符串归一化为 low/mid/high

        支持格式：
        - "low"/"mid"/"high"（直接返回）
        - "$15-25"（按均价归一化：<15→low, <25→mid, >=25→high）
        - None/空字符串 → "mid"
        """
        if not price_range:
            return "mid"
        pr = price_range.strip().lower()
        if pr in ("low", "mid", "high"):
            return pr
        # 解析 "$15-25" / "$5-15" / "$25+" 等格式
        import re
        nums = re.findall(r"\d+", pr)
        if len(nums) >= 2:
            avg = (int(nums[0]) + int(nums[1])) / 2
        elif len(nums) == 1:
            avg = int(nums[0])
        else:
            return "mid"
        if avg < 15:
            return "low"
        elif avg < 25:
            return "mid"
        else:
            return "high"

    @staticmethod
    def _downsample_embedding(
        clip_embedding: list[float] | None,
        target_dim: int = EMBEDDING_DOWNSAMPLE_DIM,
    ) -> list[float]:
        """将 CLIP 512 维 embedding 分块平均降维"""
        if not clip_embedding or len(clip_embedding) == 0:
            return [0.0] * target_dim

        src_dim = len(clip_embedding)
        chunk_size = max(1, src_dim // target_dim)
        downsampled = []
        for i in range(target_dim):
            start = i * chunk_size
            end = min(start + chunk_size, src_dim)
            if start >= src_dim:
                downsampled.append(0.0)
            else:
                chunk = clip_embedding[start:end]
                downsampled.append(sum(chunk) / len(chunk))
        return downsampled

    def extract_features(
        self,
        category: str,
        price_range: str,
        market: str,
        color_histogram: list[float] | None = None,
        complexity: float | None = None,
        similar_ctr_mean: float | None = None,
        clip_embedding: list[float] | None = None,
        image_url: str | None = None,
    ) -> list[float]:
        """特征工程（v2：81 维）

        手工特征 33 维 + CLIP embedding 降维 48 维 = 81 维
        """
        features = []

        # === 基础手工特征（19 维）===
        categories = ["dress", "shoes", "tops", "bottoms", "outerwear",
                       "accessories", "bags", "lingerie", "sportswear", "kids"]
        for cat in categories:
            features.append(1.0 if cat == category else 0.0)

        price_map = {"low": 0.0, "mid": 0.5, "high": 1.0}
        features.append(price_map.get(self._normalize_price_range(price_range), 0.5))

        market_map = {"us": 0.0, "eu": 0.25, "me": 0.5, "seasia": 0.75}
        features.append(market_map.get(market, 0.0))

        features.append(similar_ctr_mean if similar_ctr_mean is not None else 0.02)
        features.append(complexity if complexity is not None else 0.5)

        if color_histogram:
            for val in color_histogram[:5]:
                features.append(float(val))
        else:
            features.extend([0.0] * 5)

        # === 新增视觉特征（12 维）===
        visual_features = self._extract_visual_features(image_url) if image_url else {}
        # 拍摄角度（3 维：俯拍/平视/仰视）
        angle = visual_features.get("angle", [0.33, 0.34, 0.33])
        features.extend(angle[:3])
        # 模特数量（4 维：0/1/2-3/多人）
        model_count = visual_features.get("model_count", [0.4, 0.3, 0.2, 0.1])
        features.extend(model_count[:4])
        # 留白比例
        features.append(visual_features.get("whitespace_ratio", 0.3))
        # 文字占比
        features.append(visual_features.get("text_density", 0.1))
        # 饱和度均值
        features.append(visual_features.get("saturation_mean", 0.5))
        # 信息熵
        features.append(visual_features.get("image_entropy", 0.6))
        # 宽高比偏差
        features.append(visual_features.get("aspect_ratio_deviation", 0.0))

        # === CLIP embedding 降维特征 ===
        embedding_features = self._downsample_embedding(clip_embedding)
        features.extend(embedding_features)

        while len(features) < FUSED_FEATURE_DIM:
            features.append(0.0)

        return features[:FUSED_FEATURE_DIM]

    @staticmethod
    def _extract_visual_features(image_url: str | None) -> dict:
        """从图片 URL 提取视觉特征（拍摄角度/模特数量/留白/文字/饱和度等）

        优先使用 CLIP Zero-shot 分类，CLIP 不可用时降级为像素级估算。
        """
        result = {
            "angle": [0.33, 0.34, 0.33],
            "model_count": [0.4, 0.3, 0.2, 0.1],
            "whitespace_ratio": 0.3,
            "text_density": 0.1,
            "saturation_mean": 0.5,
            "image_entropy": 0.6,
            "aspect_ratio_deviation": 0.0,
        }
        if not image_url:
            return result

        try:
            from app.services.image_analysis_utils import (
                aspect_ratio_deviation,
                image_entropy,
                load_image_pixels,
                saturation_mean,
                text_density,
                whitespace_ratio,
            )
            pixels = load_image_pixels(image_url)
            if pixels is not None:
                result["whitespace_ratio"] = whitespace_ratio(pixels)
                result["text_density"] = text_density(pixels)
                result["saturation_mean"] = saturation_mean(pixels)
                result["image_entropy"] = image_entropy(pixels)
                result["aspect_ratio_deviation"] = aspect_ratio_deviation(image_url)

            # CLIP Zero-shot 分类（拍摄角度 + 模特数量）
            try:
                from app.services.embedding_service import (
                    compute_similarity,
                    encode_image,
                    encode_text,
                )
                image_vector = encode_image(str(image_url))

                angle_labels = [
                    "a product photo shot from above looking down high angle",
                    "a product photo shot at eye level straight on",
                    "a product photo shot from below looking up low angle",
                ]
                angle_scores = []
                for label in angle_labels:
                    tv = encode_text(label)
                    angle_scores.append(compute_similarity(image_vector, tv))
                total = sum(angle_scores) + 1e-10
                result["angle"] = [round(s / total, 4) for s in angle_scores]

                model_labels = [
                    "a product photo with no person or model",
                    "a product photo with one model person",
                    "a product photo with two or three models",
                    "a product photo with a crowd of many people",
                ]
                model_scores = []
                for label in model_labels:
                    tv = encode_text(label)
                    model_scores.append(compute_similarity(image_vector, tv))
                total_m = sum(model_scores) + 1e-10
                result["model_count"] = [round(s / total_m, 4) for s in model_scores]

            except Exception as e:
                logger.debug(f"CLIP 视觉特征提取失败，使用默认值: {e}")

        except Exception as e:
            logger.debug(f"像素级特征提取失败，使用默认值: {e}")

        return result

    # === 模型版本管理 ===

    def save(self, path: Path | None = None, versioned: bool = True):
        """保存模型

        Args:
            path: 保存路径，None 时自动按日期版本化命名
            versioned: True 时使用版本化路径并清理旧版本
        """
        if not self.is_trained:
            return

        if path is None and versioned:
            today = datetime.now().strftime("%Y%m%d")
            path = MODEL_DIR / f"{MODEL_PREFIX}_{today}.pkl"

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "ctr": self.ctr_model,
                "hit": self.hit_classifier,
                "return": self.return_classifier,
                "category_stats": self._category_stats,
                "feature_version": self._feature_version,
            }, f)
        logger.info(f"Models saved to {path}")

        if versioned:
            self._cleanup_old_versions()

    def _cleanup_old_versions(self):
        """保留最近 4 个版本，删除旧的"""
        versions = sorted(MODEL_DIR.glob(f"{MODEL_PREFIX}_*.pkl"))
        if len(versions) > MAX_VERSIONS:
            for old in versions[:-MAX_VERSIONS]:
                try:
                    old.unlink()
                    logger.info(f"已删除旧模型版本: {old.name}")
                except OSError as e:
                    logger.warning(f"删除旧版本失败: {old.name}: {e}")

    @classmethod
    def list_versions(cls) -> list[dict]:
        """列出所有可用模型版本"""
        versions = sorted(MODEL_DIR.glob(f"{MODEL_PREFIX}_*.pkl"), reverse=True)
        result = []
        for v in versions:
            date_str = v.stem.replace(f"{MODEL_PREFIX}_", "")
            size_kb = round(v.stat().st_size / 1024, 1) if v.exists() else 0
            result.append({
                "filename": v.name,
                "date": date_str,
                "path": str(v),
                "size_kb": size_kb,
                "is_latest": v == versions[0] if versions else False,
            })
        return result

    @classmethod
    def get_latest_version(cls) -> Path | None:
        """获取最新版本路径"""
        versions = sorted(MODEL_DIR.glob(f"{MODEL_PREFIX}_*.pkl"), reverse=True)
        return versions[0] if versions else None

    def load(self, path: Path | None = None):
        """加载模型"""
        if path is None:
            path = self.get_latest_version()
            if path is None:
                path = MODEL_DIR / f"{MODEL_PREFIX}.pkl"

        path = Path(path)
        if not path.exists():
            logger.warning(f"Model file not found: {path}")
            return

        with open(path, "rb") as f:
            data = pickle.load(f)

        self.ctr_model = data.get("ctr")
        self.hit_classifier = data.get("hit")
        self.return_classifier = data.get("return")
        self._category_stats = data.get("category_stats", {})
        self._feature_version = data.get("feature_version", 1)
        self.is_trained = self.ctr_model is not None

        logger.info(f"Models loaded from {path}", feature_version=self._feature_version)

    @classmethod
    def rollback(cls, target_date: str) -> dict:
        """回滚到指定日期的模型版本"""
        target_path = MODEL_DIR / f"{MODEL_PREFIX}_{target_date}.pkl"
        if not target_path.exists():
            available = [v.stem.replace(f"{MODEL_PREFIX}_", "") for v in
                        sorted(MODEL_DIR.glob(f"{MODEL_PREFIX}_*.pkl"))]
            return {
                "success": False,
                "message": f"版本 {target_date} 不存在",
                "available_versions": available,
            }

        predictor.load(target_path)
        predictor.save(path=MODEL_DIR / f"{MODEL_PREFIX}.pkl", versioned=False)

        logger.info(f"模型已回滚到版本 {target_date}")
        return {
            "success": True,
            "message": f"模型已回滚到 {target_date}",
            "version": target_date,
        }

    @staticmethod
    def _fallback_prediction() -> dict:
        ctr = settings.FALLBACK_CTR
        return {
            "predicted_ctr": ctr,
            "normalized_ctr": ctr,
            "confidence_interval": {
                "lower": round(ctr * 0.8, 4),
                "upper": round(ctr * 1.2, 4),
            },
        }

    @staticmethod
    def _fallback_hit() -> dict:
        prob = settings.FALLBACK_HIT_PROBABILITY
        return {
            "hit_probability": prob,
            "verdict": "high" if prob > 0.6 else ("medium" if prob > 0.3 else "low"),
        }


# 全局单例
predictor = CTRPredictor()
_loaded_model_path: Path | None = None
_loaded_model_mtime: float | None = None


def get_runtime_predictor() -> CTRPredictor:
    """返回运行时预测器；模型文件更新后自动热加载最新版本。"""
    global _loaded_model_mtime, _loaded_model_path

    model_path = CTRPredictor.get_latest_version()
    if model_path is None:
        fallback = MODEL_DIR / f"{MODEL_PREFIX}.pkl"
        model_path = fallback if fallback.exists() else None

    if model_path is None:
        return predictor

    mtime = model_path.stat().st_mtime
    if _loaded_model_path != model_path or _loaded_model_mtime != mtime:
        predictor.load(model_path)
        _loaded_model_path = model_path
        _loaded_model_mtime = mtime
    return predictor


# 启动时加载已有模型；无模型文件时保留显式的降级预测。
get_runtime_predictor()

# 兼容别名
Predictor = CTRPredictor
