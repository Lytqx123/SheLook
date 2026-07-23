"""
SheLook 后端入口，FastAPI 应用挂载点。
启动：uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

# 设置 HuggingFace 镜像（必须在 transformers 导入之前）
# 用镜像拉模型可以避开代理断流问题
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

from app.config import settings
from app.core.auth import (
    close_session_revocation_redis,
    is_feishu_login_configured,
    is_oidc_login_configured,
)
from app.core.exceptions import AppError
from app.core.logging import configure_logging, logger
from app.core.middleware import register_middleware

# --- 日志最早初始化 ---
configure_logging()

# --- Prometheus 指标 ---
REQUEST_COUNT = Counter(
    "shelook_requests_total",
    "总请求数",
    ["method", "route", "status"],
)
REQUEST_LATENCY = Histogram(
    "shelook_request_latency_seconds",
    "请求延迟（秒）",
    ["method", "route"],
)
ACTIVE_REQUESTS = Gauge(
    "shelook_active_requests",
    "当前活跃请求数",
)
BUILD_INFO = Gauge(
    "shelook_build_info",
    "当前部署版本信息",
    ["version", "revision", "environment", "region"],
)

# --- v2 新增监控指标 ---
QUALITY_PASS_RATE = Gauge(
    "shelook_quality_pass_rate",
    "质检通过率（按层级）",
    ["layer", "verdict"],
)
MODEL_PREDICTION_DRIFT = Gauge(
    "shelook_model_prediction_drift",
    "模型预测漂移（预测CTR与实际CTR的MAE差值）",
    ["model_type"],
)
GENERATION_TASK_DURATION = Histogram(
    "shelook_generation_task_duration_seconds",
    "图片生成任务耗时（秒）",
    ["provider", "status"],
    buckets=[10, 30, 60, 120, 180, 300, 600],
)
CELERY_QUEUE_LENGTH = Gauge(
    "shelook_celery_queue_length",
    "Celery 队列待处理任务数",
    ["queue"],
)

# --- 应用工厂 ---
def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _validate_production_security() -> None:
    """生产环境安全检查，缺了关键配置直接崩，省得上线才发现"""
    if settings.APP_ENV.lower() != "production":
        return

    errors = []
    warnings = []

    # SECRET_KEY 不能用默认值
    if settings.SECRET_KEY == "shelook-dev-insecure-key-change-in-production":
        errors.append("SECRET_KEY 使用了开发默认值")

    if settings.MINIO_ACCESS_KEY in {"shelook-dev", "shelook"}:
        errors.append("MINIO_ACCESS_KEY 使用了开发默认值")
    if settings.MINIO_SECRET_KEY in {"shelook-dev-secret", "shelook-dev-minio", "shelook123"}:
        errors.append("MINIO_SECRET_KEY 使用了开发默认值")
    if not settings.INTEGRATION_CREDENTIALS_ENCRYPTION_KEY:
        errors.append("生产环境必须配置 INTEGRATION_CREDENTIALS_ENCRYPTION_KEY")
    elif settings.INTEGRATION_CREDENTIALS_ENCRYPTION_KEY == settings.SECRET_KEY:
        errors.append("INTEGRATION_CREDENTIALS_ENCRYPTION_KEY 必须与 SECRET_KEY 独立")

    oidc_ready = is_oidc_login_configured()
    feishu_ready = is_feishu_login_configured()
    if not settings.ENABLE_AUTH:
        errors.append("生产环境必须启用企业认证")
    elif not (oidc_ready or feishu_ready):
        errors.append(
            "生产环境至少配置一个完整的企业登录提供方：通用 OIDC/SSO 或飞书 OAuth"
        )
    if oidc_ready:
        if not _is_https_url(settings.OIDC_ISSUER_URL):
            errors.append("OIDC_ISSUER_URL 必须使用 HTTPS")
        if not _is_https_url(settings.OIDC_REDIRECT_URI):
            errors.append("OIDC_REDIRECT_URI 必须使用 HTTPS")
    if feishu_ready and not _is_https_url(settings.FEISHU_REDIRECT_URI):
        errors.append("FEISHU_REDIRECT_URI 必须使用 HTTPS")
    if settings.FEISHU_TENANT_KEY_MAP and settings.FEISHU_ALLOWED_TENANT_KEYS:
        errors.append(
            "FEISHU_TENANT_KEY_MAP 与 FEISHU_ALLOWED_TENANT_KEYS 不能同时配置"
        )
    if (
        feishu_ready
        and not settings.FEISHU_TENANT_KEY_MAP
        and len(settings.FEISHU_ALLOWED_TENANT_KEYS) != 1
    ):
        errors.append(
            "单租户 FEISHU_ALLOWED_TENANT_KEYS 必须恰好包含一个企业；多租户请使用 FEISHU_TENANT_KEY_MAP"
        )
    if not settings.TENANT_ENFORCEMENT_ENABLED:
        errors.append("生产环境必须启用 TENANT_ENFORCEMENT_ENABLED")
    if not settings.TENANT_RLS_ENABLED:
        errors.append("生产环境必须启用 TENANT_RLS_ENABLED")
    if settings.ALLOW_GENERATION_MOCKS:
        errors.append("生产环境必须设置 ALLOW_GENERATION_MOCKS=false")
    if not settings.IMAGE_FETCH_ALLOWED_HOSTS:
        errors.append("IMAGE_FETCH_ALLOWED_HOSTS 不得为空")
    if settings.IMAGE_FETCH_TRUSTED_PRIVATE_HOSTS:
        errors.append("生产环境禁止配置 IMAGE_FETCH_TRUSTED_PRIVATE_HOSTS")
    if not settings.METRICS_API_KEY:
        errors.append("生产环境必须配置 METRICS_API_KEY")
    if not settings.C2PA_ENABLED or not settings.C2PA_REQUIRED:
        errors.append("生产环境必须启用并强制 C2PA 签名")
    if not settings.C2PA_CERT_PATH or not settings.C2PA_PRIVATE_KEY_PATH:
        errors.append("C2PA_CERT_PATH / C2PA_PRIVATE_KEY_PATH 未配置")
    else:
        for field in ("C2PA_CERT_PATH", "C2PA_PRIVATE_KEY_PATH"):
            if not Path(getattr(settings, field)).is_file():
                errors.append(f"{field} 指向的文件不存在")

    if errors:
        raise RuntimeError("生产环境安全配置未通过: " + "; ".join(errors))
    if warnings:
        logger.warning("生产环境安全检查发现问题", issues=warnings)
    else:
        logger.info("生产环境安全检查通过")


async def _validate_runtime_database_role() -> None:
    """Reject a production API role that could bypass PostgreSQL RLS."""
    if settings.APP_ENV.lower() != "production" or not settings.TENANT_RLS_ENABLED:
        return

    from sqlalchemy import text

    from app.db.session import engine

    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
            role = result.mappings().one_or_none()
    except Exception as exc:
        raise RuntimeError("无法验证生产数据库运行账号的 RLS 权限") from exc

    if role is None or role["rolsuper"] or role["rolbypassrls"]:
        raise RuntimeError(
            "生产数据库运行账号不得为超级用户或拥有 BYPASSRLS；请使用受限 runtime role"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    logger.info(
        "SheLook 后端启动中",
        env=settings.APP_ENV,
        debug=settings.DEBUG,
        port=settings.API_PORT,
        version=settings.APP_VERSION,
        revision=settings.APP_REVISION,
    )

    _validate_production_security()
    await _validate_runtime_database_role()
    app.state.started_at = asyncio.get_running_loop().time()
    BUILD_INFO.labels(
        version=settings.APP_VERSION,
        revision=settings.APP_REVISION,
        environment=settings.APP_ENV,
        region=settings.DEPLOYMENT_REGION,
    ).set(1)

    # 生产环境预加载 CLIP，避免首次请求超时
    if settings.APP_ENV == "production":
        try:
            from app.services.embedding_service import load_clip_model
            load_clip_model()
            logger.info("CLIP 模型预加载完成")
        except Exception as e:
            logger.error("CLIP 模型预加载失败", error=str(e))

    # Redis Pub/Sub（WebSocket 横向扩展用）
    try:
        from app.services.pubsub import get_pubsub
        await get_pubsub()
        logger.info("Redis Pub/Sub 已连接")
    except Exception as e:
        logger.warning("Redis Pub/Sub 初始化失败，WebSocket 降级为轮询模式", error=str(e))

    # OpenTelemetry，只在开了开关的时候初始化
    if settings.OTEL_ENABLED:
        try:
            from app.core.tracing import init_tracing
            init_tracing()
            logger.info("OpenTelemetry 追踪已初始化", service=settings.OTEL_SERVICE_NAME)
        except Exception as e:
            logger.warning("OpenTelemetry 初始化失败", error=str(e))

    # 业务指标上报后台任务
    from app.services.metrics_reporter import metrics_reporter_loop
    metrics_reporter_task = asyncio.create_task(metrics_reporter_loop())

    yield

    # 关闭
    logger.info("SheLook 后端关闭")

    metrics_reporter_task.cancel()
    with suppress(asyncio.CancelledError):
        await metrics_reporter_task

    from app.services.pubsub import pubsub
    if pubsub:
        try:
            await pubsub.disconnect()
            logger.info("Redis Pub/Sub 已断开")
        except Exception as e:
            logger.warning("Redis Pub/Sub 断开失败", error=str(e))

    await close_session_revocation_redis()

    from app.db.session import engine
    await engine.dispose()


app = FastAPI(
    title="SheLook API",
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# --- Prometheus /metrics ---
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# --- 全局异常处理 ---
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning(
        str(exc.detail),
        status_code=exc.status_code,
        **exc.extra,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, **exc.extra},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    logger.warning("参数校验失败", detail=str(exc))
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理的异常", error=str(exc))
    request_id = getattr(request.state, "request_id", None)
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }
    if request_id:
        headers["X-Request-ID"] = request_id
        headers["X-Audit-Trace-ID"] = request_id
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误"},
        headers=headers,
    )


# --- 健康检查 ---
@app.get("/api/health/live", tags=["Health"])
async def liveness_check() -> dict[str, Any]:
    """进程存活探针；不访问外部依赖，避免依赖短暂故障造成级联重启。"""
    return {
        "status": "alive",
        "version": settings.APP_VERSION,
        "revision": settings.APP_REVISION,
        "environment": settings.APP_ENV,
    }


@app.get("/api/health", tags=["Health"])
async def health_check() -> dict[str, Any]:
    from app.db.session import engine
    from app.services.pubsub import pubsub

    db_healthy = False
    try:
        conn = await engine.connect()
        await conn.close()
        db_healthy = True
    except Exception as exc:
        logger.warning("基础健康检查数据库不可用", error=str(exc))

    redis_healthy = pubsub is not None

    return {
        "status": "healthy" if db_healthy and redis_healthy else "degraded",
        "version": settings.APP_VERSION,
        "revision": settings.APP_REVISION,
        "environment": settings.APP_ENV,
        "checks": {
            "database": "ok" if db_healthy else "unavailable",
            "redis_pubsub": "ok" if redis_healthy else "unavailable",
        },
    }


@app.get("/api/health/ready", tags=["Health"])
async def readiness_check() -> JSONResponse:
    """K8s Readiness Probe，依赖挂了就返回 503"""
    checks = {}

    try:
        from app.db.session import engine
        conn = await engine.connect()
        await conn.close()
        checks["database"] = "ok"
    except Exception as e:
        logger.warning("就绪检查数据库不可用", error=str(e))
        checks["database"] = "unavailable"

    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.close()
        checks["redis"] = "ok"
    except Exception as e:
        logger.warning("就绪检查 Redis 不可用", error=str(e))
        checks["redis"] = "unavailable"

    try:
        from app.services.storage_service import get_minio_client
        minio = get_minio_client()
        await asyncio.to_thread(minio.list_buckets)
        checks["minio"] = "ok"
    except Exception as e:
        logger.warning("就绪检查 MinIO 不可用", error=str(e))
        checks["minio"] = "unavailable"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "status": "ready" if all_ok else "not_ready",
            "version": settings.APP_VERSION,
            "revision": settings.APP_REVISION,
            "checks": checks,
        },
    )


# --- 速率限制 ---
from app.core.rate_limit import RateLimitMiddleware

app.add_middleware(RateLimitMiddleware, redis_url=settings.REDIS_URL)
register_middleware(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 路由注册 ---
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.campaigns import compat_router as campaign_compat_router
from app.api.campaigns import router as campaign_router
from app.api.clustering import router as clustering_router
from app.api.dashboard import router as dashboard_router
from app.api.enterprise_data import router as enterprise_data_router
from app.api.experiment import router as experiment_router
from app.api.fairness import router as fairness_router
from app.api.flywheel import router as flywheel_router
from app.api.generation import router as generation_router
from app.api.integrations import router as integrations_router
from app.api.metrics import router as metrics_router
from app.api.organization import router as organization_router
from app.api.prediction import router as prediction_router
from app.api.products import router as product_router
from app.api.provider_configs import router as provider_configs_router
from app.api.review import router as review_router
from app.api.runtime_settings import router as runtime_settings_router
from app.api.schemes import router as scheme_router
from app.api.supplier import router as supplier_router
from app.api.video import router as video_router
from app.api.workflows import router as workflow_router
from app.core.auth import require_auth

protected = [Depends(require_auth)]
app.include_router(product_router, dependencies=protected)
app.include_router(scheme_router, dependencies=protected)
app.include_router(generation_router, dependencies=protected)
app.include_router(review_router, dependencies=protected)
app.include_router(prediction_router, dependencies=protected)
app.include_router(experiment_router, dependencies=protected)
app.include_router(dashboard_router, dependencies=protected)
app.include_router(flywheel_router, dependencies=protected)
app.include_router(audit_router, dependencies=protected)
app.include_router(video_router, dependencies=protected)
app.include_router(clustering_router, dependencies=protected)
app.include_router(fairness_router, dependencies=protected)
app.include_router(supplier_router, dependencies=protected)
app.include_router(auth_router)
app.include_router(organization_router, dependencies=protected)
app.include_router(workflow_router, dependencies=protected)
app.include_router(integrations_router, dependencies=protected)
app.include_router(provider_configs_router, dependencies=protected)
app.include_router(runtime_settings_router, dependencies=protected)
app.include_router(enterprise_data_router, dependencies=protected)
app.include_router(campaign_router, dependencies=protected)
app.include_router(campaign_compat_router, dependencies=protected)
# Metrics 写端点走机器 API Key，读端点在路由内部校验用户
app.include_router(metrics_router)

# 注意：请求计数中间件已改用 core/middleware.py 里的纯 ASGI 实现，
# 避免 BaseHTTPMiddleware 的 Content-Length 坑
