"""
SheLook FastAPI 应用入口

启动方式：
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import os
from pathlib import Path

# 设置 HuggingFace 镜像站（必须在 huggingface_hub/transformers 导入之前）
# 镜像站为正规 HTTPS 证书，无需禁用 SSL 验证，可避开 Clash 代理大文件断流问题
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

from app.config import settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, logger
from app.core.middleware import register_middleware

# ========== 结构化日志初始化（最早调用） ==========
configure_logging()

# ========== Prometheus 指标 ==========
REQUEST_COUNT = Counter(
    "shelook_requests_total",
    "总请求数",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "shelook_request_latency_seconds",
    "请求延迟（秒）",
    ["method", "endpoint"],
)
ACTIVE_REQUESTS = Gauge(
    "shelook_active_requests",
    "当前活跃请求数",
)

# ---- v2 新增监控指标（Phase 3） ----
QUALITY_PASS_RATE = Gauge(
    "shelook_quality_pass_rate",
    "质检通过率（按层级）",
    ["layer", "verdict"],  # layer: L1/L2/L3, verdict: auto_approved/manual_pending/rejected
)
MODEL_PREDICTION_DRIFT = Gauge(
    "shelook_model_prediction_drift",
    "模型预测漂移（预测CTR与实际CTR的MAE差值）",
    ["model_type"],  # model_type: ctr/hit/return
)
GENERATION_TASK_DURATION = Histogram(
    "shelook_generation_task_duration_seconds",
    "图片生成任务耗时（秒）",
    ["provider", "status"],  # provider: replicate/sdwebui/gemini, status: success/failed
    buckets=[10, 30, 60, 120, 180, 300, 600],
)
CELERY_QUEUE_LENGTH = Gauge(
    "shelook_celery_queue_length",
    "Celery 队列待处理任务数",
    ["queue"],  # queue: celery/default/flower
)

# ========== 应用工厂 ==========
def _validate_production_security() -> None:
    """生产环境启动时的安全检查"""
    if settings.APP_ENV != "production":
        return

    errors = []
    warnings = []

    # 检查 SECRET_KEY 是否已更改
    if settings.SECRET_KEY == "shelook-dev-insecure-key-change-in-production":
        errors.append("SECRET_KEY 使用了开发默认值")

    # 检查 MinIO 凭证
    if settings.MINIO_ACCESS_KEY == "shelook-dev":
        errors.append("MINIO_ACCESS_KEY 使用了开发默认值")
    if settings.MINIO_SECRET_KEY == "shelook-dev-secret":
        errors.append("MINIO_SECRET_KEY 使用了开发默认值")

    if not settings.ENABLE_AUTH:
        errors.append("生产环境必须启用企业 OIDC 认证")
    for field in ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"):
        if not getattr(settings, field):
            errors.append(f"{field} 未配置")
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

    # 检查 API 密钥
    if not settings.REPLICATE_API_TOKEN:
        warnings.append("REPLICATE_API_TOKEN 未配置，Replicate 生图链路将不可用")
    if not settings.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY 未配置，Google 生图/标签/审核链路将降级")

    if errors:
        raise RuntimeError("生产环境安全配置未通过: " + "; ".join(errors))
    if warnings:
        logger.warning("生产环境安全检查发现问题", issues=warnings)
    else:
        logger.info("生产环境安全检查通过")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # === 启动 ===
    logger.info(
        "SheLook 后端启动中",
        env=settings.APP_ENV,
        debug=settings.DEBUG,
        port=settings.API_PORT,
    )

    # 生产环境安全检查
    _validate_production_security()

    # 预加载 CLIP 模型（生产环境）
    if settings.APP_ENV == "production":
        try:
            from app.services.embedding_service import load_clip_model
            load_clip_model()
            logger.info("CLIP 模型预加载完成")
        except Exception as e:
            logger.error("CLIP 模型预加载失败", error=str(e))

    # 初始化 Redis Pub/Sub（WebSocket 横向扩展）
    try:
        from app.services.pubsub import get_pubsub
        await get_pubsub()
        logger.info("Redis Pub/Sub 已连接")
    except Exception as e:
        logger.warning("Redis Pub/Sub 初始化失败，WebSocket 降级为轮询模式", error=str(e))

    # 初始化 OpenTelemetry 分布式追踪
    if settings.OTEL_ENABLED:
        try:
            from app.core.tracing import init_tracing
            init_tracing()
            logger.info("OpenTelemetry 追踪已初始化", service=settings.OTEL_SERVICE_NAME)
        except Exception as e:
            logger.warning("OpenTelemetry 初始化失败", error=str(e))

    # 启动业务指标上报后台任务
    # 必须在被 Prometheus 抓取的 backend 进程内更新自定义 Gauge/Histogram
    from app.services.metrics_reporter import metrics_reporter_loop
    metrics_reporter_task = asyncio.create_task(metrics_reporter_loop())

    yield

    # === 关闭 ===
    logger.info("SheLook 后端关闭")

    # 停止业务指标上报
    metrics_reporter_task.cancel()
    with suppress(asyncio.CancelledError):
        await metrics_reporter_task

    # 释放 Redis Pub/Sub 连接
    from app.services.pubsub import pubsub
    if pubsub:
        try:
            await pubsub.disconnect()
            logger.info("Redis Pub/Sub 已断开")
        except Exception as e:
            logger.warning("Redis Pub/Sub 断开失败", error=str(e))

    # 释放数据库连接池
    from app.db.session import engine
    await engine.dispose()


app = FastAPI(
    title="SheLook API",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# ========== CORS 中间件 ==========
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 自定义中间件 ==========
register_middleware(app)

# ========== Prometheus /metrics 端点 ==========
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ========== 全局异常处理器 ==========
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """统一处理自定义异常"""
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
    """Pydantic 校验失败 或 业务 ValueError"""
    logger.warning("参数校验失败", detail=str(exc))
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底：未预期的运行时异常"""
    logger.exception("未处理的异常", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误"},
    )


# ========== 健康检查 ==========
@app.get("/api/health", tags=["Health"])
async def health_check() -> dict[str, Any]:
    """基础健康检查 —— 返回服务状态"""
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
        "version": "1.0.0",
        "environment": settings.APP_ENV,
        "checks": {
            "database": "ok" if db_healthy else "unavailable",
            "redis_pubsub": "ok" if redis_healthy else "unavailable",
        },
    }


@app.get("/api/health/ready", tags=["Health"])
async def readiness_check() -> JSONResponse:
    """Readiness Probe：关键依赖不可用时返回 503，避免继续接收流量。"""
    checks = {}

    # 数据库
    try:
        from app.db.session import engine
        conn = await engine.connect()
        await conn.close()
        checks["database"] = "ok"
    except Exception as e:
        logger.warning("就绪检查数据库不可用", error=str(e))
        checks["database"] = "unavailable"

    # Redis
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.close()
        checks["redis"] = "ok"
    except Exception as e:
        logger.warning("就绪检查 Redis 不可用", error=str(e))
        checks["redis"] = "unavailable"

    # MinIO
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
            "checks": checks,
        },
    )


# ========== 速率限制中间件（基于 Redis 滑动窗口） ==========
from app.core.rate_limit import RateLimitMiddleware

app.add_middleware(RateLimitMiddleware, redis_url=settings.REDIS_URL)

# ========== 注册 API 路由 ==========
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.clustering import router as clustering_router
from app.api.dashboard import router as dashboard_router
from app.api.experiment import router as experiment_router
from app.api.fairness import router as fairness_router
from app.api.flywheel import router as flywheel_router
from app.api.generation import router as generation_router
from app.api.metrics import router as metrics_router
from app.api.prediction import router as prediction_router
from app.api.products import router as product_router
from app.api.review import router as review_router
from app.api.schemes import router as scheme_router
from app.api.supplier import router as supplier_router
from app.api.video import router as video_router
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
# Metrics 写端点使用机器 API Key，读端点在路由内部要求用户认证。
app.include_router(metrics_router)

# 注意: Prometheus 请求计数中间件已移至 core/middleware.py 的
# PrometheusMetricsMiddleware（纯 ASGI 实现），避免 BaseHTTPMiddleware 的
# Content-Length 问题。在 register_middleware() 中注册。
