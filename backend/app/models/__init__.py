"""SheLook ORM 模型聚合导出

所有 router / task / migration 都从这里 import，避免循环依赖。
"""

from app.models.audit_log import AuditLog
from app.models.brand_standard import BrandStandard
from app.models.experiment import ABExperiment, ExperimentStatus
from app.models.external_listing import ExternalListingMapping
from app.models.image import GeneratedImage, ImageScheme, ReviewStatus
from app.models.prediction import DailyMetric, PredictionRecord, ReturnRiskLevel
from app.models.product import Product, ProductStatus
from app.models.product_embedding import ProductEmbedding
from app.models.review import ReviewAction, ReviewRecord
from app.models.supplier_report import SupplierAnalysisReport
from app.models.supplier_score import SupplierVisualScore

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
    # 向量
    "ProductEmbedding",
    # 品牌规范与供应商评分（002 迁移）
    "BrandStandard",
    "SupplierVisualScore",
    "SupplierAnalysisReport",
    # 审计日志（004 迁移）
    "AuditLog",
]
