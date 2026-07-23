"""Contract checks for the visual-operation campaign foundation."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.campaigns import _validate_status_transition
from app.models.campaign import CampaignStage, CampaignStatus, VisualOperationCampaign
from app.schemas.campaign import CampaignCreateRequest, CampaignUpdateRequest


def test_campaign_request_matches_activity_workbench_defaults() -> None:
    campaign = CampaignCreateRequest(
        name="US summer launch",
        market="us",
        objective="Validate a higher first-image CTR",
        description="Targeting summer apparel shoppers.",
    )

    assert campaign.status == CampaignStatus.DRAFT
    assert campaign.current_stage == CampaignStage.BRIEF
    assert campaign.description == "Targeting summer apparel shoppers."


def test_campaign_plan_alias_is_materialized_as_scheme_id() -> None:
    campaign = CampaignUpdateRequest(plan_id=42)

    assert campaign.scheme_ids == [42]


def test_campaign_status_transitions_keep_terminal_state_protected() -> None:
    _validate_status_transition(CampaignStatus.DRAFT, CampaignStatus.IN_PROGRESS)
    _validate_status_transition(CampaignStatus.IN_PROGRESS, CampaignStatus.LEARNING)

    with pytest.raises(HTTPException) as exc_info:
        _validate_status_transition(CampaignStatus.ARCHIVED, CampaignStatus.IN_PROGRESS)
    assert exc_info.value.status_code == 409


def test_campaign_model_and_migration_share_persisted_contract() -> None:
    model_columns = set(VisualOperationCampaign.__table__.columns.keys())
    required_columns = {
        "tenant_id",
        "product_id",
        "description",
        "recommended_action",
        "current_stage",
        "scheme_ids",
        "image_ids",
        "experiment_ids",
    }
    assert required_columns <= model_columns

    migration = (
        Path(__file__).parents[1] / "app/db/migrations/versions/015_visual_operation_campaigns.py"
    )
    migration_source = migration.read_text(encoding="utf-8")
    for column in required_columns:
        assert f'"{column}"' in migration_source
    assert 'server_default="brief"' in migration_source
    assert 'sa.Column("recommended_action", sa.JSON()' in migration_source
