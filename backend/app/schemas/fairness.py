"""公平性约束相关 Pydantic 模型"""

from pydantic import BaseModel


class SkinToneDistribution(BaseModel):
    """肤色分布统计"""
    light: int = 0
    medium: int = 0
    dark: int = 0
    no_person: int = 0
    unknown: int = 0


class FairnessDistributionOut(BaseModel):
    """肤色分布分析响应"""
    total_images: int
    distribution: SkinToneDistribution
    fairness_alert: bool
    alert_details: str | None = None
    recommendation: str
    expected_demographics: dict = {}
    deviations: dict = {}


class SchemeFairnessOut(BaseModel):
    """方案级公平性检查响应"""
    scheme_id: int
    market: str | None = None
    passes_fairness: bool
    current_distribution: dict = {}
    details: str
    expected_demographics: dict | None = None


class FairnessReportOut(BaseModel):
    """市场公平性报告响应"""
    market: str
    date_range_days: int
    total_images: int
    distribution: SkinToneDistribution
    expected_demographics: dict = {}
    deviations: dict = {}
    fairness_alert: bool
    recommendation: str
    generated_at: str
