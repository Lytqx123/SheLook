from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类，所有 Model 继承这个"""


class TenantScopedMixin:
    """需要由企业租户隔离的业务模型通用字段。"""

    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="所属企业租户",
    )
