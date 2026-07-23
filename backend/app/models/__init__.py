"""ORM 模型聚合导出，避免循环依赖。"""

from app.models.audit_log import AuditLog
from app.models.brand_standard import BrandStandard
from app.models.campaign import (
    CampaignInsight,
    CampaignInsightStatus,
    CampaignInsightType,
    CampaignStage,
    CampaignStatus,
    VisualOperationCampaign,
)
from app.models.enterprise_data import (
    CommerceFact,
    ExternalEntityMapping,
    ModelFeedbackLabel,
    PerformanceFact,
    PredictionSnapshot,
)
from app.models.experiment import ABExperiment, ExperimentStatus
from app.models.external_listing import ExternalListingMapping
from app.models.image import GeneratedImage, ImageScheme, ReviewStatus
from app.models.integration import DianxiaomiConnection, IntegrationSyncRun
from app.models.organization import OrganizationUnit, Tenant, TenantMembership, TenantQuota
from app.models.prediction import DailyMetric, PredictionRecord, ReturnRiskLevel
from app.models.product import Product, ProductStatus
from app.models.product_embedding import ProductEmbedding
from app.models.provider_config import ProviderConfig
from app.models.release_control import AIUsageRecord, TenantFeatureFlag, UsageStatus
from app.models.review import ReviewAction, ReviewRecord
from app.models.runtime_setting import RuntimeSetting, RuntimeSettingRevision
from app.models.supplier_report import SupplierAnalysisReport
from app.models.supplier_score import SupplierVisualScore
from app.models.workflow import OutboxEvent, OutboxStatus, WorkflowTask, WorkflowTaskStatus

__all__ = [
    # 商品
    "Product",
    "ProductStatus",
    # 方案与生成图片
    "ImageScheme",
    "GeneratedImage",
    "ReviewStatus",
    # 审核
    "ReviewRecord",
    "ReviewAction",
    # A/B 实验
    "ABExperiment",
    "ExperimentStatus",
    # 预测与指标
    "PredictionRecord",
    "ReturnRiskLevel",
    "DailyMetric",
    "ExternalListingMapping",
    "DianxiaomiConnection",
    "IntegrationSyncRun",
    "ProviderConfig",
    "ExternalEntityMapping",
    "CommerceFact",
    "PerformanceFact",
    "PredictionSnapshot",
    "ModelFeedbackLabel",
    # 向量
    "ProductEmbedding",
    # 品牌规范与供应商评分
    "BrandStandard",
    "SupplierVisualScore",
    "SupplierAnalysisReport",
    # 审计日志
    "AuditLog",
    # 视觉运营活动与知识沉淀
    "VisualOperationCampaign",
    "CampaignStatus",
    "CampaignStage",
    "CampaignInsight",
    "CampaignInsightType",
    "CampaignInsightStatus",
    # 企业组织
    "Tenant",
    "OrganizationUnit",
    "TenantMembership",
    "TenantQuota",
    "TenantFeatureFlag",
    "AIUsageRecord",
    "UsageStatus",
    "RuntimeSetting",
    "RuntimeSettingRevision",
    # 工作流与可靠消息
    "WorkflowTask",
    "WorkflowTaskStatus",
    "OutboxEvent",
    "OutboxStatus",
]
