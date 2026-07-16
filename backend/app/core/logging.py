"""
结构化日志，基于 structlog。
开发环境彩色输出，生产环境 JSON（方便接 Loki/ELK）。
"""

import logging

import structlog

from app.config import settings


def configure_logging() -> None:
    """配置 structlog，根据环境切输出格式"""
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.APP_ENV == "production":
        # JSON 格式，优先用 orjson
        try:
            import orjson
            json_serializer = orjson.dumps
        except ImportError:
            import json

            def json_serializer(obj, default=None):
                return json.dumps(obj, default=default or str).encode("utf-8")

        structlog.configure(
            processors=shared_processors
            + [
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(serializer=json_serializer),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    else:
        # 开发环境彩色输出
        structlog.configure(
            processors=shared_processors
            + [
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    # 抑制 uvicorn 双重日志
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.error").handlers = []


logger = structlog.get_logger("shelook")
