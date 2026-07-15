"""pytest 共享 fixtures 与测试配置"""

import os
from unittest import mock

import pytest

# ---- 在导入 app 模块之前设置测试环境变量 ----
os.environ["APP_ENV"] = "test"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["ENABLE_AUTH"] = "false"
os.environ["RATE_LIMIT_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def _override_env() -> None:
    """确保测试环境变量不与生产 .env 冲突"""
    os.environ["APP_ENV"] = "test"
    os.environ["REDIS_URL"] = "redis://localhost:6379/15"
    os.environ["ENABLE_AUTH"] = "false"
    os.environ["RATE_LIMIT_ENABLED"] = "false"


@pytest.fixture
def mock_redis():
    """全局 mock redis.asyncio.from_url，避免测试连接真实 Redis"""
    with mock.patch("redis.asyncio.from_url") as mock_from_url:
        mock_client = mock.AsyncMock()
        mock_from_url.return_value = mock_client
        yield mock_client


@pytest.fixture
def client(mock_redis):
    """创建同步 TestClient；应用内部仍按真实 ASGI 生命周期运行。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
