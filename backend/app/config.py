"""
全局配置，基于 pydantic-settings 从 .env 加载。
多环境的话 copy 对应的 .env.xxx → .env 就行。
"""

import os

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = os.getenv("ENV_FILE", ".env")


class Settings(BaseSettings):
    """SheLook 配置，新增字段会自动从 .env 读取"""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 运行环境 ---
    APP_ENV: str = "development"
    DEBUG: bool = False

    # --- 服务 ---
    API_PORT: int = 8000

    # --- 安全 ---
    SECRET_KEY: str = "shelook-dev-insecure-key-change-in-production"

    # --- 数据库 ---
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/shelook"
    )
    DATABASE_URL_SYNC: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/shelook"
    )
    PGVECTOR_EXTENSION: bool = True

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # --- MinIO ---
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "shelook-dev"
    MINIO_SECRET_KEY: str = "shelook-dev-secret"
    MINIO_BUCKET: str = "product-images"
    MINIO_PRIVATE_BUCKET: str = "product-images-private"
    MINIO_PUBLIC_BASE_URL: str = "http://localhost:9000"
    MINIO_REGION: str = "us-east-1"
    MINIO_SECURE: bool = False
    MINIO_PRESIGNED_URL_EXPIRY_SECONDS: int = 3600

    # --- 远程图片下载 ---
    IMAGE_FETCH_ALLOWED_HOSTS: list[str] = [
        "placehold.co",
        "replicate.delivery",
        "pbxt.replicate.delivery",
        "storage.googleapis.com",
        "ai.googleusercontent.com",
    ]
    IMAGE_FETCH_TRUSTED_PRIVATE_HOSTS: list[str] = []
    IMAGE_FETCH_MAX_BYTES: int = 25 * 1024 * 1024
    IMAGE_FETCH_TIMEOUT_SECONDS: float = 30.0
    IMAGE_FETCH_MAX_REDIRECTS: int = 3

    @field_validator("IMAGE_FETCH_ALLOWED_HOSTS", "IMAGE_FETCH_TRUSTED_PRIVATE_HOSTS", mode="before")
    @classmethod
    def parse_host_lists(cls, v: str | list[str]) -> list[str]:
        """兼容 JSON 数组或逗号分隔字符串"""
        if isinstance(v, str):
            value = v.strip()
            if value.startswith("["):
                import json
                return [str(host).strip().lower() for host in json.loads(value) if str(host).strip()]
            return [host.strip().lower() for host in value.split(",") if host.strip()]
        return [str(host).strip().lower() for host in v if str(host).strip()]

    # --- AIGC 生图 ---
    REPLICATE_API_TOKEN: str = ""
    REPLICATE_MODEL: str = ""
    REPLICATE_TIMEOUT: int = 180
    GEMINI_API_KEY: str = ""
    GEMINI_BASE_URL: str = ""
    SD_WEBUI_URL: str = "http://localhost:7860"
    ALLOW_GENERATION_MOCKS: bool = True

    # --- AI 视频 ---
    KLING_API_KEY: str = ""
    KLING_API_BASE_URL: str = ""
    KLING_ACCESS_KEY: str = ""
    KLING_SECRET_KEY: str = ""
    RUNWAY_API_KEY: str = ""

    # --- CLIP ---
    CLIP_MODEL_NAME: str = "openai/clip-vit-base-patch32"
    VECTOR_DIMENSION: int = 512

    # --- CORS ---
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # --- 日志 ---
    LOG_LEVEL: str = "INFO"

    # --- 限流 ---
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 600
    RATE_LIMIT_WINDOW: int = 60
    TRUSTED_PROXY_HOSTS: list[str] = ["127.0.0.1", "::1", "nginx"]

    @field_validator("TRUSTED_PROXY_HOSTS", mode="before")
    @classmethod
    def parse_trusted_proxies(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [host.strip() for host in v.split(",") if host.strip()]
        return v

    # --- 认证 ---
    ENABLE_AUTH: bool = False
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    OIDC_ISSUER_URL: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_AUDIENCE: str = ""
    OIDC_REDIRECT_URI: str = "http://localhost:3000/login/callback"
    OIDC_SCOPES: str = "openid profile email"
    OIDC_ROLE_CLAIM: str = "roles"
    OIDC_ADMIN_ROLES: list[str] = ["admin", "shelook-admin"]
    OIDC_HTTP_TIMEOUT_SECONDS: float = 10.0

    @field_validator("OIDC_ADMIN_ROLES", mode="before")
    @classmethod
    def parse_oidc_roles(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [role.strip() for role in v.split(",") if role.strip()]
        return v

    @property
    def JWT_SECRET(self) -> str:
        return self.SECRET_KEY

    # --- 图文匹配 ---
    IMAGE_TEXT_MATCH_THRESHOLD: float = 0.25

    # --- 模型未训练时的兜底值 ---
    FALLBACK_CTR: float = 0.025
    FALLBACK_HIT_PROBABILITY: float = 0.3

    # --- 指标 API ---
    METRICS_API_KEY: str = ""

    # --- C2PA Content Credentials ---
    C2PA_ENABLED: bool = False
    C2PA_REQUIRED: bool = False
    C2PA_CERT_PATH: str = ""
    C2PA_PRIVATE_KEY_PATH: str = ""
    C2PA_SIGNING_ALGORITHM: str = "ES256"
    C2PA_TIMESTAMP_AUTHORITY_URL: str = ""

    # --- 公平性看板 ---
    # TODO: 这些基线值后面可能要让运营同学在管理后台自己配
    FAIRNESS_BASELINE_SOURCE: str = "operator-configured baseline; validate with local legal/data owners"
    FAIRNESS_MARKET_BASELINES: dict[str, dict[str, float]] = {
        "us": {"light": 0.55, "medium": 0.25, "dark": 0.15, "no_person": 0.05},
        "eu": {"light": 0.65, "medium": 0.20, "dark": 0.10, "no_person": 0.05},
        "me": {"light": 0.30, "medium": 0.50, "dark": 0.15, "no_person": 0.05},
        "seasia": {"light": 0.10, "medium": 0.60, "dark": 0.25, "no_person": 0.05},
        "default": {"light": 0.40, "medium": 0.35, "dark": 0.20, "no_person": 0.05},
    }
    FAIRNESS_DEVIATION_THRESHOLD: float = 0.30
    FAIRNESS_MAX_CLASSIFICATIONS_PER_REQUEST: int = 50
    DASHBOARD_CTR_BASELINE: float = 0.02
    EXPERIMENT_COMPLETION_IMPRESSIONS: int = 10000

    # --- 电商平台 API ---
    # Shopee
    SHOPEE_PARTNER_ID: str = ""
    SHOPEE_PARTNER_KEY: str = ""
    SHOPEE_SHOP_ID: str = ""
    SHOPEE_ACCESS_TOKEN: str = ""

    # Amazon SP-API
    AMAZON_CLIENT_ID: str = ""
    AMAZON_CLIENT_SECRET: str = ""
    AMAZON_REFRESH_TOKEN: str = ""
    AMAZON_MARKETPLACE_ID: str = "ATVPDKIKX0DER"
    AMAZON_REPORT_POLL_SECONDS: float = 5.0
    AMAZON_REPORT_TIMEOUT_SECONDS: float = 180.0
    AMAZON_SYNC_MAX_DAYS: int = 3

    # --- OpenTelemetry ---
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "shelook-backend"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""


settings = Settings()
