"""Allow-listed business settings resolved at request/task execution time."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.runtime_setting import RuntimeSetting, RuntimeSettingRevision

SettingValueType = Literal["integer", "number"]


@dataclass(frozen=True, slots=True)
class RuntimeSettingSpec:
    key: str
    label: str
    description: str
    value_type: SettingValueType
    default: int | float
    minimum: int | float
    maximum: int | float


@dataclass(frozen=True, slots=True)
class EffectiveRuntimeSetting:
    spec: RuntimeSettingSpec
    value: int | float
    version: int
    updated_by: str | None
    updated_at: object | None
    is_overridden: bool


class RuntimeSettingError(ValueError):
    """Raised for an unknown or invalid business runtime setting."""


RUNTIME_SETTING_SPECS: tuple[RuntimeSettingSpec, ...] = (
    RuntimeSettingSpec(
        key="ctr.dashboard_baseline",
        label="运营看板 CTR 基线",
        description="运营首页中用于比较当前 CTR 的业务基线，不改变原始指标。",
        value_type="number",
        default=settings.DASHBOARD_CTR_BASELINE,
        minimum=0,
        maximum=1,
    ),
    RuntimeSettingSpec(
        key="experiments.completion_impressions",
        label="A/B 实验完成曝光阈值",
        description="两个变体累计达到该曝光量后，系统结束实验并计算显著性。",
        value_type="integer",
        default=settings.EXPERIMENT_COMPLETION_IMPRESSIONS,
        minimum=100,
        maximum=100_000_000,
    ),
    RuntimeSettingSpec(
        key="ctr.minimum_mature_impressions",
        label="CTR 反馈最小成熟曝光量",
        description="预测快照必须累计达到该真实曝光量，才可生成模型校正标签。",
        value_type="integer",
        default=1_000,
        minimum=100,
        maximum=100_000_000,
    ),
)
_SPECS_BY_KEY = {spec.key: spec for spec in RUNTIME_SETTING_SPECS}


def get_runtime_setting_spec(setting_key: str) -> RuntimeSettingSpec:
    spec = _SPECS_BY_KEY.get(setting_key)
    if spec is None:
        raise RuntimeSettingError("未知或不可由 Web 管理的运行时配置项")
    return spec


def validate_runtime_setting_value(spec: RuntimeSettingSpec, value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RuntimeSettingError(f"{spec.label} 必须是数值")
    if spec.value_type == "integer" and not isinstance(value, int):
        raise RuntimeSettingError(f"{spec.label} 必须是整数")
    normalized: int | float = int(value) if spec.value_type == "integer" else float(value)
    if not spec.minimum <= normalized <= spec.maximum:
        raise RuntimeSettingError(
            f"{spec.label} 必须在 {spec.minimum} 到 {spec.maximum} 之间"
        )
    return normalized


async def get_effective_runtime_setting(
    db: AsyncSession,
    *,
    tenant_id: str,
    setting_key: str,
) -> EffectiveRuntimeSetting:
    spec = get_runtime_setting_spec(setting_key)
    setting = await db.scalar(
        select(RuntimeSetting).where(
            RuntimeSetting.tenant_id == tenant_id,
            RuntimeSetting.setting_key == setting_key,
        )
    )
    if setting is None:
        return EffectiveRuntimeSetting(
            spec=spec,
            value=spec.default,
            version=0,
            updated_by=None,
            updated_at=None,
            is_overridden=False,
        )
    value = validate_runtime_setting_value(spec, setting.value_json)
    return EffectiveRuntimeSetting(
        spec=spec,
        value=value,
        version=setting.version,
        updated_by=setting.updated_by,
        updated_at=setting.updated_at,
        is_overridden=True,
    )


async def list_effective_runtime_settings(
    db: AsyncSession, *, tenant_id: str
) -> list[EffectiveRuntimeSetting]:
    configured = {
        item.setting_key: item
        for item in (
            await db.execute(
                select(RuntimeSetting).where(RuntimeSetting.tenant_id == tenant_id)
            )
        ).scalars()
    }
    result: list[EffectiveRuntimeSetting] = []
    for spec in RUNTIME_SETTING_SPECS:
        setting = configured.get(spec.key)
        if setting is None:
            result.append(
                EffectiveRuntimeSetting(spec, spec.default, 0, None, None, False)
            )
            continue
        result.append(
            EffectiveRuntimeSetting(
                spec,
                validate_runtime_setting_value(spec, setting.value_json),
                setting.version,
                setting.updated_by,
                setting.updated_at,
                True,
            )
        )
    return result


async def set_runtime_setting(
    db: AsyncSession,
    *,
    tenant_id: str,
    setting_key: str,
    value: object,
    actor_id: str,
    action: str = "updated",
) -> EffectiveRuntimeSetting:
    spec = get_runtime_setting_spec(setting_key)
    normalized = validate_runtime_setting_value(spec, value)
    setting = await db.scalar(
        select(RuntimeSetting).where(
            RuntimeSetting.tenant_id == tenant_id,
            RuntimeSetting.setting_key == setting_key,
        )
    )
    if setting is None:
        previous_version = int(
            (
                await db.scalar(
                    select(func.max(RuntimeSettingRevision.version)).where(
                        RuntimeSettingRevision.tenant_id == tenant_id,
                        RuntimeSettingRevision.setting_key == setting_key,
                    )
                )
            )
            or 0
        )
        setting = RuntimeSetting(
            tenant_id=tenant_id,
            setting_key=setting_key,
            value_json=normalized,
            version=previous_version + 1,
            updated_by=actor_id,
        )
        db.add(setting)
        await db.flush()
    else:
        setting.value_json = normalized
        setting.version += 1
        setting.updated_by = actor_id
        await db.flush()

    db.add(
        RuntimeSettingRevision(
            tenant_id=tenant_id,
            setting_id=setting.id,
            setting_key=setting_key,
            version=setting.version,
            value_json=normalized,
            action=action,
            changed_by=actor_id,
        )
    )
    await db.flush()
    await db.refresh(setting)
    return EffectiveRuntimeSetting(
        spec, normalized, setting.version, setting.updated_by, setting.updated_at, True
    )


async def reset_runtime_setting(
    db: AsyncSession,
    *,
    tenant_id: str,
    setting_key: str,
    actor_id: str,
) -> EffectiveRuntimeSetting:
    spec = get_runtime_setting_spec(setting_key)
    setting = await db.scalar(
        select(RuntimeSetting).where(
            RuntimeSetting.tenant_id == tenant_id,
            RuntimeSetting.setting_key == setting_key,
        )
    )
    if setting is None:
        return EffectiveRuntimeSetting(spec, spec.default, 0, None, None, False)

    next_version = setting.version + 1
    db.add(
        RuntimeSettingRevision(
            tenant_id=tenant_id,
            setting_id=None,
            setting_key=setting_key,
            version=next_version,
            value_json=None,
            action="reset_to_default",
            changed_by=actor_id,
        )
    )
    await db.delete(setting)
    await db.flush()
    return EffectiveRuntimeSetting(spec, spec.default, next_version, actor_id, None, False)


async def list_runtime_setting_revisions(
    db: AsyncSession,
    *,
    tenant_id: str,
    setting_key: str,
) -> list[RuntimeSettingRevision]:
    get_runtime_setting_spec(setting_key)
    result = await db.execute(
        select(RuntimeSettingRevision)
        .where(
            RuntimeSettingRevision.tenant_id == tenant_id,
            RuntimeSettingRevision.setting_key == setting_key,
        )
        .order_by(RuntimeSettingRevision.version.desc())
    )
    return list(result.scalars())
