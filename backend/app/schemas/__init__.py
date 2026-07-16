"""Pydantic 请求/响应模型，统一 re-export。"""

# --- 认证
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    UserResponse,
)

# --- 聚类分析
from app.schemas.clustering import (
    ClusterInfo,
    ClusteringRequest,
    ClusteringResponse,
    TSNECoordinate,
)

# --- A/B 实验
from app.schemas.experiment import (
    ExperimentCreateRequest,
    ExperimentListOut,
    ExperimentResponse,
)

# --- 公平性约束
from app.schemas.fairness import (
    FairnessDistributionOut,
    FairnessReportOut,
    SchemeFairnessOut,
    SkinToneDistribution,
)

# --- 图片生成
from app.schemas.generation import (
    GenerateRequest,
    GenerateResponse,
    GenerationStatusOut,
    L1ComplianceSchema,
    L2QualitySchema,
    L3AestheticSchema,
    QualityScores,
)

# --- 数据指标
from app.schemas.metrics import (
    MetricsBatchItem,
    MetricsBatchRequest,
    MetricsBatchResponse,
    MetricsRawItem,
    MetricsStatsResponse,
    MetricsSyncResponse,
    MetricsUpsertResult,
)

# --- 效果预估
from app.schemas.prediction import (
    ModelRollbackRequest,
    ModelRollbackResponse,
    ModelVersionItem,
    ModelVersionListResponse,
    PredictionRequest,
    PredictionResponse,
)
from app.schemas.product import (
    ProductCreate,
    ProductListOut,
    ProductOut,
    ProductUpdate,
    SchemeOut,
)

# --- 审核
from app.schemas.review import (
    ReviewRequest,
    ReviewResponse,
)

# --- 视觉方案
from app.schemas.scheme import (
    SchemeFusionRecommendOut,
    SchemeFusionRecommendRequest,
    SchemeRecommendOut,
    SchemeRecommendRequest,
)

# --- 供应商分析
from app.schemas.supplier import (
    BenchmarkInfo,
    DimensionScore,
    ImprovementSuggestion,
    SupplierAnalyzeRequest,
    SupplierReportListItem,
    SupplierReportListResponse,
    SupplierReportResponse,
)

# --- 图文匹配
from app.schemas.text_match import (
    TextMatchDetails,
    TextMatchRequest,
    TextMatchResponse,
)

# --- 视频生成
from app.schemas.video import (
    VideoGenerateRequest,
)

# --- 九维审美启发式评分
from app.schemas.vision_reward import (
    PairwiseComparison,
    VisionRewardRequest,
    VisionRewardResponse,
)

__all__ = [
    # 商品
    "ProductCreate",
    "ProductUpdate",
    "ProductOut",
    "ProductListOut",
    "SchemeOut",
    # 视觉方案
    "SchemeRecommendRequest",
    "SchemeRecommendOut",
    "SchemeFusionRecommendRequest",
    "SchemeFusionRecommendOut",
    # 图片生成
    "GenerateRequest",
    "GenerateResponse",
    "L1ComplianceSchema",
    "L2QualitySchema",
    "L3AestheticSchema",
    "QualityScores",
    "GenerationStatusOut",
    # 图文匹配
    "TextMatchRequest",
    "TextMatchResponse",
    "TextMatchDetails",
    # 审核
    "ReviewRequest",
    "ReviewResponse",
    # 效果预估
    "PredictionRequest",
    "PredictionResponse",
    "ModelVersionItem",
    "ModelVersionListResponse",
    "ModelRollbackRequest",
    "ModelRollbackResponse",
    # 聚类分析
    "ClusteringRequest",
    "ClusteringResponse",
    "ClusterInfo",
    "TSNECoordinate",
    # A/B 实验
    "ExperimentCreateRequest",
    "ExperimentResponse",
    "ExperimentListOut",
    # 公平性约束
    "SkinToneDistribution",
    "FairnessDistributionOut",
    "SchemeFairnessOut",
    "FairnessReportOut",
    # 九维审美启发式评分
    "VisionRewardRequest",
    "VisionRewardResponse",
    "PairwiseComparison",
    # 认证
    "LoginRequest",
    "TokenResponse",
    "UserResponse",
    # 视频生成
    "VideoGenerateRequest",
    # 数据指标
    "MetricsBatchItem",
    "MetricsBatchRequest",
    "MetricsBatchResponse",
    "MetricsStatsResponse",
    "MetricsSyncResponse",
    "MetricsUpsertResult",
    "MetricsRawItem",
    # 供应商分析
    "SupplierAnalyzeRequest",
    "SupplierReportResponse",
    "DimensionScore",
    "ImprovementSuggestion",
    "BenchmarkInfo",
    "SupplierReportListItem",
    "SupplierReportListResponse",
]
