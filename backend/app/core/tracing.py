"""OpenTelemetry 分布式追踪 —— 零代码自动插桩

架构：
  - FastAPI/ASGI：自动捕获 HTTP 请求 Span
  - SQLAlchemy：自动捕获 DB 查询 Span
  - Celery：自动传播 trace context 跨越任务队列
  - Redis：自动捕获 Redis 操作 Span
  - HTTPX/Requests：自动捕获出站 HTTP Span

环境变量驱动（无需改代码）：
  OTEL_SERVICE_NAME=shelook-backend
  OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
  OTEL_TRACES_EXPORTER=otlp
  OTEL_METRICS_EXPORTER=none

启动方式（两种）：
  # 方式 1: opentelemetry-instrument CLI（推荐，零代码改动）
  opentelemetry-instrument uvicorn app.main:app --host 0.0.0.0 --port 8000

  # 方式 2: 代码级初始化（调用 init_tracing()）
  from app.core.tracing import init_tracing
  init_tracing()

手动 Span 示例：
  from opentelemetry import trace
  tracer = trace.get_tracer(__name__)
  with tracer.start_as_current_span("my_operation") as span:
      span.set_attribute("custom.key", "value")
"""

import os

from app.core.logging import logger


def init_tracing() -> bool:
    """初始化 OpenTelemetry 追踪（代码级，兼容无 CLI 环境）

    仅在 OTEL_SERVICE_NAME 环境变量已设置时初始化。
    推荐使用 opentelemetry-instrument CLI 自动插桩，
    此函数作为容器内启动的备选方案。

    Returns:
        True 如果成功初始化，False 如果跳过
    """
    service_name = os.environ.get("OTEL_SERVICE_NAME", "")
    if not service_name:
        logger.debug("OTEL_SERVICE_NAME 未设置，跳过 OpenTelemetry 初始化")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource(attributes={
            SERVICE_NAME: service_name,
            "deployment.environment": os.environ.get("APP_ENV", "development"),
        })

        provider = TracerProvider(resource=resource)

        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTLP Exporter 已配置", endpoint=otlp_endpoint)

        trace.set_tracer_provider(provider)

        # ---- 自动插桩 ----
        _auto_instrument()

        logger.info("OpenTelemetry 追踪已初始化", service_name=service_name)
        return True

    except ImportError:
        logger.debug("OpenTelemetry 包未安装，跳过追踪初始化")
        return False
    except Exception as e:
        logger.warning("OpenTelemetry 初始化失败", error=str(e))
        return False


def _auto_instrument() -> None:
    """自动插桩常用库（按需，避免 ImportError 阻断启动）"""
    instrumentors = [
        ("opentelemetry.instrumentation.fastapi", "FastAPIInstrumentor"),
        ("opentelemetry.instrumentation.asgi", "ASGIInstrumentor"),
        ("opentelemetry.instrumentation.sqlalchemy", "SQLAlchemyInstrumentor"),
        ("opentelemetry.instrumentation.redis", "RedisInstrumentor"),
        ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
        ("opentelemetry.instrumentation.celery", "CeleryInstrumentor"),
    ]

    for module_name, class_name in instrumentors:
        try:
            mod = __import__(module_name, fromlist=[class_name])
            instrumentor = getattr(mod, class_name)
            if class_name == "SQLAlchemyInstrumentor":
                # 传入 async engine 的 sync_engine 以确保异步 DB 查询被追踪
                try:
                    from app.db.session import engine as _engine
                    instrumentor().instrument(engine=_engine.sync_engine)
                except Exception:
                    instrumentor().instrument()  # 降级：自动插桩
            else:
                instrumentor().instrument()
            logger.debug(f"OTel 自动插桩: {class_name}")
        except ImportError:
            logger.debug(f"OTel 插桩库未安装: {module_name}")
        except Exception as e:
            logger.debug(f"OTel 插桩跳过 {class_name}: {e}")
