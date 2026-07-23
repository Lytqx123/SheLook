"""第六阶段：灰度开关与预算预留回归测试。"""

import asyncio
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi import HTTPException

from app.api.generation import _enforce_generation_quota
from app.models.release_control import UsageStatus
from app.services.feature_flags import is_feature_enabled, require_feature_enabled
from scripts.phase6.verify_data_integrity import (
    EXPECTED_REVISION,
    RELATIONSHIP_CHECKS,
    TENANT_TABLES,
)


def test_feature_flag_uses_platform_default_when_no_override_exists():
    db = mock.AsyncMock()
    db.scalar.return_value = None

    assert asyncio.run(is_feature_enabled(db, "ai_generation")) is True


def test_disabled_feature_flag_rejects_new_admission():
    db = mock.AsyncMock()
    db.scalar.return_value = SimpleNamespace(enabled=False)

    with pytest.raises(HTTPException, match="ai_generation") as error:
        asyncio.run(require_feature_enabled(db, "ai_generation"))

    assert error.value.status_code == 403


def test_generation_budget_counts_reserved_usage_before_admission():
    quota = SimpleNamespace(
        generation_concurrency=4,
        monthly_generation_limit=None,
        monthly_budget_cents=10,
    )
    db = mock.AsyncMock()
    db.scalar.side_effect = [quota, 0, 5]

    with pytest.raises(HTTPException, match="AI 预算") as error:
        asyncio.run(_enforce_generation_quota(db, estimated_cost_cents=8))

    assert error.value.status_code == 429
    assert UsageStatus.RESERVED == "reserved"


def test_release_integrity_gate_covers_current_enterprise_feedback_tables():
    assert EXPECTED_REVISION == "019"
    assert {
        "dianxiaomi_connections",
        "integration_sync_runs",
        "runtime_settings",
        "runtime_setting_revisions",
        "external_entity_mappings",
        "commerce_facts",
        "performance_facts",
        "prediction_snapshots",
        "model_feedback_labels",
        "provider_configs",
    }.issubset(TENANT_TABLES)
    assert {
        "integration_sync_connection_tenant",
        "runtime_setting_revision_tenant",
        "performance_fact_mapping_tenant",
        "prediction_snapshot_record_tenant",
        "feedback_label_snapshot_tenant",
    }.issubset(RELATIONSHIP_CHECKS)
