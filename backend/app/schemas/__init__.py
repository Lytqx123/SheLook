"""Pydantic 请求/响应模型，统一 re-export。"""

# --- 认证
from app.schemas.auth import (
    AuthConfigResponse,
    LoginMethodResponse,
    LoginRequest,
    TokenResponse,
    UserResponse,
)

# --- 视觉运营活动
from app.schemas.campaign import (
    CampaignActionItem,
    CampaignCreateRequest,
    CampaignDecisionSummary,
    CampaignDetailResponse,
    CampaignExperimentSummary,
    CampaignImageSummary,
    CampaignInsightCreateRequest,
    CampaignInsightListResponse,
    CampaignInsightResponse,
    CampaignListResponse,
    CampaignProductSummary,
    CampaignResponse,
    CampaignStatusUpdateRequest,
    CampaignTimelineItem,
    CampaignUpdateRequest,
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
from app.schemas.integration import (
    DianxiaomiConfigCheckResponse,
    DianxiaomiConnectionCreate,
    DianxiaomiConnectionResponse,
    DianxiaomiConnectionUpdate,
    DianxiaomiCredentialsInput,
    IntegrationSyncRunResponse,
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
from app.schemas.organization import (
    OrganizationUnitCreate,
    OrganizationUnitResponse,
    TenantContextResponse,
    TenantFeatureFlagResponse,
    TenantFeatureFlagUpdate,
    TenantMemberInvite,
    TenantMemberResponse,
    TenantMemberUpsert,
    TenantQuotaResponse,
    TenantQuotaUpdate,
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
from app.schemas.provider_config import (
    ProviderConfigResponse,
    ProviderConfigUpsert,
    ProviderConfigValidationResponse,
)

# --- 审核
from app.schemas.review import (
    ReviewRequest,
    ReviewResponse,
)
from app.schemas.runtime_setting import (
    RuntimeSettingResponse,
    RuntimeSettingRevisionResponse,
    RuntimeSettingUpdate,
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
from app.schemas.workflow import (
    WorkflowActionResponse,
    WorkflowTaskListResponse,
    WorkflowTaskResponse,
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
    "AuthConfigResponse",
    "LoginRequest",
    "LoginMethodResponse",
    "TokenResponse",
    "UserResponse",
    # 视觉运营活动
    "CampaignCreateRequest",
    "CampaignUpdateRequest",
    "CampaignStatusUpdateRequest",
    "CampaignResponse",
    "CampaignListResponse",
    "CampaignDetailResponse",
    "CampaignProductSummary",
    "CampaignImageSummary",
    "CampaignExperimentSummary",
    "CampaignDecisionSummary",
    "CampaignActionItem",
    "CampaignTimelineItem",
    "CampaignInsightCreateRequest",
    "CampaignInsightResponse",
    "CampaignInsightListResponse",
    # 企业组织
    "TenantContextResponse",
    "OrganizationUnitCreate",
    "OrganizationUnitResponse",
    "TenantMemberInvite",
    "TenantMemberUpsert",
    "TenantMemberResponse",
    "TenantQuotaUpdate",
    "TenantQuotaResponse",
    "TenantFeatureFlagUpdate",
    "TenantFeatureFlagResponse",
    # 工作流任务中心
    "WorkflowTaskResponse",
    "WorkflowTaskListResponse",
    "WorkflowActionResponse",
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
    # 店小秘集成
    "DianxiaomiCredentialsInput",
    "DianxiaomiConnectionCreate",
    "DianxiaomiConnectionUpdate",
    "DianxiaomiConnectionResponse",
    "DianxiaomiConfigCheckResponse",
    "IntegrationSyncRunResponse",
    "RuntimeSettingUpdate",
    "RuntimeSettingResponse",
    "RuntimeSettingRevisionResponse",
    "ProviderConfigUpsert",
    "ProviderConfigResponse",
    "ProviderConfigValidationResponse",
    # 供应商分析
    "SupplierAnalyzeRequest",
    "SupplierReportResponse",
    "DimensionScore",
    "ImprovementSuggestion",
    "BenchmarkInfo",
    "SupplierReportListItem",
    "SupplierReportListResponse",
]
