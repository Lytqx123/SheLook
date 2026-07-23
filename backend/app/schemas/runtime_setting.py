"""Contracts for tenant-managed business runtime settings."""

from datetime import datetime

from pydantic import BaseModel, Field


class RuntimeSettingUpdate(BaseModel):
    """Only numeric settings are allow-listed in the initial configuration center."""

    value: int | float = Field(..., description="符合该配置项约束的数值")


class RuntimeSettingResponse(BaseModel):
    key: str
    label: str
    description: str
    value_type: str
    default_value: int | float
    value: int | float
    is_overridden: bool
    version: int
    updated_by: str | None = None
    updated_at: datetime | None = None


class RuntimeSettingRevisionResponse(BaseModel):
    key: str
    version: int
    value: int | float | None = None
    action: str
    changed_by: str | None = None
    created_at: datetime
