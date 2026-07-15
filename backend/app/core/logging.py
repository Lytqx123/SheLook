"""
结构化日志配置 —— 基于 structlog

输出格式：
  开发环境：彩色控制台
  生产环境：JSON（可直接接入 Loki / ELK / Datadog）

用法：
  from app.core.logging import logger

  logger.info("商品上传成功", sku_code="SKU-001", category="fashion")
  logger.error("生成失败", error=str(e), scheme_id=42)
"""

import logging

import structlog

from app.config import settings


def configure_logging() -> None:
    """配置 structlog 全局实例"""
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.APP_ENV == "production":
        # 生产环境：JSON 格式（orjson 性能更优，不存在则降级为标准 json）
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
        # 开发环境：彩色控制台
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

    # 抑制 uvicorn 的双重日志
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.error").handlers = []


# 全局 logger 实例
logger = structlog.get_logger("shelook")
