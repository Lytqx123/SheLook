"""验证租户隔离、引用一致性、RLS 与迁移版本。"""

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

EXPECTED_REVISION = "019"
TENANT_TABLES = (
    "products",
    "image_schemes",
    "generated_images",
    "review_records",
    "ab_experiments",
    "prediction_records",
    "daily_metrics",
    "product_embeddings",
    "brand_standards",
    "supplier_visual_scores",
    "supplier_analysis_reports",
    "audit_logs",
    "external_listing_mappings",
    "workflow_tasks",
    "outbox_events",
    "organization_units",
    "tenant_memberships",
    "tenant_quotas",
    "tenant_feature_flags",
    "ai_usage_records",
    "visual_operation_campaigns",
    "campaign_insights",
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
)
RELATIONSHIP_CHECKS = {
    "scheme_product_tenant": """
        SELECT COUNT(*) FROM image_schemes s
        JOIN products p ON p.id = s.product_id
        WHERE s.tenant_id <> p.tenant_id
    """,
    "image_scheme_tenant": """
        SELECT COUNT(*) FROM generated_images i
        JOIN image_schemes s ON s.id = i.scheme_id
        WHERE i.tenant_id <> s.tenant_id
    """,
    "metric_image_tenant": """
        SELECT COUNT(*) FROM daily_metrics m
        JOIN generated_images i ON i.id = m.image_id
        WHERE m.tenant_id <> i.tenant_id
    """,
    "prediction_image_tenant": """
        SELECT COUNT(*) FROM prediction_records p
        JOIN generated_images i ON i.id = p.image_id
        WHERE p.tenant_id <> i.tenant_id
    """,
    "embedding_product_tenant": """
        SELECT COUNT(*) FROM product_embeddings e
        JOIN products p ON p.id = e.product_id
        WHERE e.tenant_id <> p.tenant_id
    """,
    "campaign_product_tenant": """
        SELECT COUNT(*) FROM visual_operation_campaigns c
        JOIN products p ON p.id = c.product_id
        WHERE c.product_id IS NOT NULL
          AND c.tenant_id <> p.tenant_id
    """,
    "campaign_insight_tenant": """
        SELECT COUNT(*) FROM campaign_insights insight
        JOIN visual_operation_campaigns campaign ON campaign.id = insight.campaign_id
        WHERE insight.tenant_id <> campaign.tenant_id
    """,
    "integration_sync_connection_tenant": """
        SELECT COUNT(*) FROM integration_sync_runs run
        JOIN dianxiaomi_connections connection ON connection.id = run.connection_id
        WHERE run.tenant_id <> connection.tenant_id
    """,
    "runtime_setting_revision_tenant": """
        SELECT COUNT(*) FROM runtime_setting_revisions revision
        JOIN runtime_settings setting ON setting.id = revision.setting_id
        WHERE revision.setting_id IS NOT NULL
          AND revision.tenant_id <> setting.tenant_id
    """,
    "external_mapping_product_tenant": """
        SELECT COUNT(*) FROM external_entity_mappings mapping
        JOIN products product ON product.id = mapping.product_id
        WHERE mapping.product_id IS NOT NULL
          AND mapping.tenant_id <> product.tenant_id
    """,
    "external_mapping_image_tenant": """
        SELECT COUNT(*) FROM external_entity_mappings mapping
        JOIN generated_images image ON image.id = mapping.image_id
        WHERE mapping.image_id IS NOT NULL
          AND mapping.tenant_id <> image.tenant_id
    """,
    "commerce_fact_sync_run_tenant": """
        SELECT COUNT(*) FROM commerce_facts fact
        JOIN integration_sync_runs run ON run.id = fact.sync_run_id
        WHERE fact.sync_run_id IS NOT NULL
          AND fact.tenant_id <> run.tenant_id
    """,
    "performance_fact_mapping_tenant": """
        SELECT COUNT(*) FROM performance_facts fact
        JOIN external_entity_mappings mapping ON mapping.id = fact.mapping_id
        WHERE fact.mapping_id IS NOT NULL
          AND fact.tenant_id <> mapping.tenant_id
    """,
    "performance_fact_image_tenant": """
        SELECT COUNT(*) FROM performance_facts fact
        JOIN generated_images image ON image.id = fact.image_id
        WHERE fact.image_id IS NOT NULL
          AND fact.tenant_id <> image.tenant_id
    """,
    "prediction_snapshot_record_tenant": """
        SELECT COUNT(*) FROM prediction_snapshots snapshot
        JOIN prediction_records record ON record.id = snapshot.prediction_record_id
        WHERE snapshot.tenant_id <> record.tenant_id
    """,
    "prediction_snapshot_image_tenant": """
        SELECT COUNT(*) FROM prediction_snapshots snapshot
        JOIN generated_images image ON image.id = snapshot.image_id
        WHERE snapshot.tenant_id <> image.tenant_id
    """,
    "feedback_label_snapshot_tenant": """
        SELECT COUNT(*) FROM model_feedback_labels label
        JOIN prediction_snapshots snapshot ON snapshot.id = label.prediction_snapshot_id
        WHERE label.tenant_id <> snapshot.tenant_id
    """,
    "feedback_label_image_tenant": """
        SELECT COUNT(*) FROM model_feedback_labels label
        JOIN generated_images image ON image.id = label.image_id
        WHERE label.tenant_id <> image.tenant_id
    """,
}


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    value: int | str
    detail: str


async def _scalar(connection, statement: str) -> int | str | None:
    return (await connection.execute(text(statement))).scalar_one()


async def verify() -> dict[str, object]:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    checks: list[Check] = []
    try:
        async with engine.connect() as connection:
            revision = await _scalar(connection, "SELECT version_num FROM alembic_version")
            checks.append(
                Check(
                    "migration_head",
                    revision == EXPECTED_REVISION,
                    str(revision),
                    f"expected {EXPECTED_REVISION}",
                )
            )

            for table in TENANT_TABLES:
                orphaned = await _scalar(
                    connection,
                    f"SELECT COUNT(*) FROM {table} t "
                    "LEFT JOIN tenants tenant ON tenant.id = t.tenant_id "
                    "WHERE tenant.id IS NULL",
                )
                checks.append(Check(f"{table}_tenant_fk", orphaned == 0, int(orphaned or 0), "orphan rows"))

            for name, statement in RELATIONSHIP_CHECKS.items():
                mismatches = await _scalar(connection, statement)
                checks.append(Check(name, mismatches == 0, int(mismatches or 0), "cross-tenant relation"))

            missing_quotas = await _scalar(
                connection,
                """
                SELECT COUNT(*) FROM tenants tenant
                LEFT JOIN tenant_quotas quota ON quota.tenant_id = tenant.id
                WHERE tenant.status = 'active' AND quota.tenant_id IS NULL
                """,
            )
            checks.append(Check("active_tenant_quota", missing_quotas == 0, int(missing_quotas or 0), "missing quota"))

            table_list = ", ".join(f"'{table}'" for table in TENANT_TABLES)
            rls_missing = await _scalar(
                connection,
                f"""
                SELECT COUNT(*) FROM pg_class relation
                JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relname IN ({table_list})
                  AND NOT relation.relrowsecurity
                """,
            )
            checks.append(Check("tenant_rls_enabled", rls_missing == 0, int(rls_missing or 0), "tables without RLS"))
    finally:
        await engine.dispose()

    return {
        "passed": all(check.passed for check in checks),
        "environment": settings.APP_ENV,
        "expected_revision": EXPECTED_REVISION,
        "checks": [asdict(check) for check in checks],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="JSON 报告输出路径")
    args = parser.parse_args()
    report = asyncio.run(verify())
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
