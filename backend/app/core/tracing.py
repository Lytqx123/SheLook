"""OpenTelemetry 分布式追踪，零代码自动插桩常用库"""

import os

from app.core.logging import logger


def init_tracing() -> bool:
    """初始化 OTel，只在 OTEL_SERVICE_NAME 设了的时候才干活。推荐用 CLI 方式自动插桩，这个函数当备选"""
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
    """逐一尝试插桩常用库，某个库没装就跳过，不影响启动"""
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
                # SQLAlchemy 异步需要传 sync_engine，不然抓不到查询
                try:
                    from app.db.session import engine as _engine
                    instrumentor().instrument(engine=_engine.sync_engine)
                except Exception:
                    instrumentor().instrument()
            else:
                instrumentor().instrument()
            logger.debug(f"OTel 自动插桩: {class_name}")
        except ImportError:
            logger.debug(f"OTel 插桩库未安装: {module_name}")
        except Exception as e:
            logger.debug(f"OTel 插桩跳过 {class_name}: {e}")
