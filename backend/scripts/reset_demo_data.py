"""清理开发环境的演示业务数据、对象与任务状态。

必须显式传入 ``--confirm``。脚本只允许在 development/test 环境执行，并保留
Alembic 迁移记录及 ``default`` 租户，使数据库可直接填充新版演示数据。
"""

import argparse
import asyncio
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.services.storage_service import get_minio_client

BUSINESS_TABLES = (
    "campaign_insights",
    "visual_operation_campaigns",
    "outbox_events",
    "workflow_tasks",
    "ai_usage_records",
    "tenant_feature_flags",
    "audit_logs",
    "external_listing_mappings",
    "supplier_analysis_reports",
    "supplier_visual_scores",
    "review_records",
    "prediction_records",
    "daily_metrics",
    "ab_experiments",
    "generated_images",
    "image_schemes",
    "product_embeddings",
    "brand_standards",
    "products",
    "tenant_memberships",
    "organization_units",
    "tenant_quotas",
)


def _ensure_safe_to_run(confirmed: bool) -> None:
    if not confirmed:
        raise SystemExit("拒绝执行：请显式传入 --confirm")
    if settings.APP_ENV.lower() not in {"development", "test"}:
        raise SystemExit("拒绝执行：仅 development/test 环境允许清理演示数据")


async def _reset_database() -> dict[str, int]:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            dialect = make_url(settings.DATABASE_URL).get_backend_name()
            if dialect == "postgresql":
                await connection.execute(
                    text(f"TRUNCATE TABLE {', '.join(BUSINESS_TABLES)} RESTART IDENTITY CASCADE")
                )
                await connection.execute(text("DELETE FROM tenants WHERE id <> 'default'"))
                await connection.execute(
                    text("INSERT INTO tenant_quotas (tenant_id) VALUES ('default') ON CONFLICT DO NOTHING")
                )
            else:
                for table in BUSINESS_TABLES:
                    await connection.execute(text(f"DELETE FROM {table}"))
                await connection.execute(text("DELETE FROM tenants WHERE id <> 'default'"))
                await connection.execute(
                    text("INSERT OR IGNORE INTO tenant_quotas (tenant_id) VALUES ('default')")
                )

            checks = {
                "products": "products",
                "images": "generated_images",
                "metrics": "daily_metrics",
                "workflows": "workflow_tasks",
                "tenants": "tenants",
            }
            return {
                label: int((await connection.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one())
                for label, table in checks.items()
            }
    finally:
        await engine.dispose()


def _reset_object_storage() -> dict[str, int]:
    client = get_minio_client()
    deleted: dict[str, int] = {}
    for bucket in {settings.MINIO_BUCKET, settings.MINIO_PRIVATE_BUCKET}:
        count = 0
        if client.bucket_exists(bucket):
            for item in client.list_objects(bucket, recursive=True):
                client.remove_object(bucket, item.object_name)
                count += 1
        deleted[bucket] = count
    return deleted


def _reset_model_artifacts() -> int:
    model_dir = Path(os.getenv("MODEL_DIR", "models"))
    if not model_dir.exists():
        return 0

    removed = 0
    for child in model_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


async def _reset_redis() -> list[str]:
    urls = {settings.REDIS_URL, settings.CELERY_BROKER_URL, settings.CELERY_RESULT_BACKEND}
    reset: list[str] = []
    for redis_url in urls:
        client = aioredis.from_url(redis_url)
        try:
            await client.flushdb()
            location = urlparse(redis_url)
            reset.append(f"{location.hostname or 'redis'}{location.path or '/0'}")
        finally:
            await client.aclose()
    return sorted(reset)


async def reset_demo_data() -> dict[str, object]:
    database = await _reset_database()
    objects = await asyncio.to_thread(_reset_object_storage)
    model_entries = await asyncio.to_thread(_reset_model_artifacts)
    redis_databases = await _reset_redis()
    return {
        "database_remaining": database,
        "object_storage_deleted": objects,
        "model_artifacts_removed": model_entries,
        "redis_databases_reset": redis_databases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true", help="确认永久清理开发演示数据")
    args = parser.parse_args()
    _ensure_safe_to_run(args.confirm)
    print(json.dumps(asyncio.run(reset_demo_data()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
