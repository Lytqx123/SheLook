"""
全局配置，基于 pydantic-settings 从 .env 加载。
多环境的话 copy 对应的 .env.xxx → .env 就行。
"""

import os
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    APP_VERSION: str = "1.1.0"
    APP_REVISION: str = "unknown"
    DEPLOYMENT_REGION: str = "local"

    # --- 服务 ---
    API_PORT: int = 8000
    API_WORKERS: int = 3

    # --- 安全 ---
    SECRET_KEY: str = "shelook-dev-insecure-key-change-in-production"
    # Bootstrap-only key for credentials saved through the Web integration
    # center. It is never returned by the API and must stay in the runtime
    # secret store; production rejects credential writes when it is absent.
    INTEGRATION_CREDENTIALS_ENCRYPTION_KEY: str = ""

    # --- 数据库 ---
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/shelook"
    )
    DATABASE_URL_SYNC: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/shelook"
    )
    # Only the controlled migration job may receive this owner-capable URL.
    # API and worker pods must use DATABASE_URL for a non-BYPASSRLS role.
    DATABASE_MIGRATION_URL: str = ""
    PGVECTOR_EXTENSION: bool = True
    DATABASE_ECHO: bool = False
    # Per-process limits. Keep the combined API and worker pools below the
    # PostgreSQL connection budget; scale API replicas before raising these.
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 0
    DATABASE_POOL_TIMEOUT_SECONDS: float = 10.0
    DATABASE_POOL_RECYCLE_SECONDS: int = 900
    DATABASE_STATEMENT_TIMEOUT_MS: int = 30_000
    DATABASE_LOCK_TIMEOUT_MS: int = 5_000
    DATABASE_APPLICATION_NAME: str = "shelook-api"
    DASHBOARD_SUMMARY_CACHE_TTL_SECONDS: int = 15
    PRODUCT_LIST_CACHE_TTL_SECONDS: int = 10

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_VISIBILITY_TIMEOUT_SECONDS: int = 3600
    CELERY_RESULT_EXPIRES_SECONDS: int = 86_400
    CELERY_ORCHESTRATION_CONCURRENCY: int = 4
    CELERY_GENERATION_CONCURRENCY: int = 2
    CELERY_ANALYTICS_CONCURRENCY: int = 2

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
    IMAGE_FETCH_ALLOWED_HOSTS: Annotated[list[str], NoDecode] = [
        "placehold.co",
        "replicate.delivery",
        "pbxt.replicate.delivery",
        "storage.googleapis.com",
        "ai.googleusercontent.com",
    ]
    IMAGE_FETCH_TRUSTED_PRIVATE_HOSTS: Annotated[list[str], NoDecode] = []
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
    REPLICATE_TIMEOUT: int = 180
    SD_WEBUI_URL: str = "http://localhost:7860"
    ALLOW_GENERATION_MOCKS: bool = True
    GENERATION_BATCH_CONCURRENCY: int = 4
    IMAGE_GENERATION_RESERVATION_CENTS: int = 8
    VIDEO_GENERATION_RESERVATION_CENTS: int = 30

    # Third-party AI / commerce provider credentials are configured through
    # the administrator Web console, encrypted per tenant in provider_configs.

    # --- CLIP ---
    CLIP_MODEL_NAME: str = "openai/clip-vit-base-patch32"
    VECTOR_DIMENSION: int = 512

    # --- CORS ---
    CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:8000",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            value = v.strip()
            if value.startswith("["):
                import json

                parsed = json.loads(value)
                if not isinstance(parsed, list):
                    raise ValueError("CORS_ORIGINS JSON value must be an array")
                return [str(origin).strip() for origin in parsed if str(origin).strip()]
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return v

    # --- 日志 ---
    LOG_LEVEL: str = "INFO"

    # --- 限流 ---
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 600
    RATE_LIMIT_WINDOW: int = 60
    TRUSTED_PROXY_HOSTS: Annotated[list[str], NoDecode] = ["127.0.0.1", "::1", "nginx"]

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
    # Bound the hot-path session-revocation lookup so a Redis partition cannot
    # exhaust API workers while production correctly fails closed.
    AUTH_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS: float = 1.0
    AUTH_REDIS_SOCKET_TIMEOUT_SECONDS: float = 1.0
    AUTH_REDIS_MAX_CONNECTIONS: int = 32
    AUTH_REDIS_FAILURE_BACKOFF_SECONDS: float = 2.0
    OIDC_ISSUER_URL: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_AUDIENCE: str = ""
    OIDC_REDIRECT_URI: str = "http://localhost:3000/login/callback"
    OIDC_SCOPES: str = "openid profile email"
    OIDC_HTTP_TIMEOUT_SECONDS: float = 10.0
    OIDC_TENANT_CLAIM: str = "tenant_id"
    # Map an IdP tenant/organization claim to a local tenant. Without a map,
    # generic OIDC is intentionally restricted to DEFAULT_TENANT_ID.
    OIDC_TENANT_CLAIM_MAP: dict[str, str] = {}

    # --- 飞书网页登录（OAuth 2.0 授权码模式）---
    # 飞书不是 OIDC Provider；保留 OIDC 配置用于通用企业 SSO。
    # 只允许由受控映射或明确允许的 tenant_key 决定本地租户，不能信任
    # 来自浏览器、回调参数或用户资料中的任意 tenant_id。
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_REDIRECT_URI: str = ""
    FEISHU_SCOPES: str = "auth:user.id:read"
    FEISHU_TENANT_KEY_MAP: dict[str, str] = {}
    FEISHU_ALLOWED_TENANT_KEYS: Annotated[list[str], NoDecode] = []

    # --- 企业租户与权限 ---
    DEFAULT_TENANT_ID: str = "default"
    TENANT_ENFORCEMENT_ENABLED: bool = True
    TENANT_RLS_ENABLED: bool = True

    @field_validator("OIDC_TENANT_CLAIM_MAP", mode="before")
    @classmethod
    def parse_oidc_tenant_claim_map(cls, v: str | dict[str, str]) -> dict[str, str]:
        """Require an explicit JSON map for multi-tenant generic OIDC."""
        if isinstance(v, str):
            import json

            value = v.strip()
            if not value:
                return {}
            parsed = json.loads(value)
        else:
            parsed = v
        if not isinstance(parsed, dict):
            raise ValueError("OIDC_TENANT_CLAIM_MAP must be a JSON object")
        return {
            str(external_tenant_id).strip(): str(tenant_id).strip()
            for external_tenant_id, tenant_id in parsed.items()
            if str(external_tenant_id).strip() and str(tenant_id).strip()
        }

    @field_validator("FEISHU_TENANT_KEY_MAP", mode="before")
    @classmethod
    def parse_feishu_tenant_key_map(cls, v: str | dict[str, str]) -> dict[str, str]:
        """Accept a JSON environment value while keeping tenant mappings explicit."""
        if isinstance(v, str):
            import json

            value = v.strip()
            if not value:
                return {}
            parsed = json.loads(value)
        else:
            parsed = v
        if not isinstance(parsed, dict):
            raise ValueError("FEISHU_TENANT_KEY_MAP must be a JSON object")
        return {
            str(feishu_tenant_key).strip(): str(tenant_id).strip()
            for feishu_tenant_key, tenant_id in parsed.items()
            if str(feishu_tenant_key).strip() and str(tenant_id).strip()
        }

    @field_validator("FEISHU_ALLOWED_TENANT_KEYS", mode="before")
    @classmethod
    def parse_feishu_tenant_key_allowlist(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            value = v.strip()
            if not value:
                return []
            if value.startswith("["):
                import json

                return [
                    str(tenant_key).strip()
                    for tenant_key in json.loads(value)
                    if str(tenant_key).strip()
                ]
            return [tenant_key.strip() for tenant_key in value.split(",") if tenant_key.strip()]
        return [str(tenant_key).strip() for tenant_key in v if str(tenant_key).strip()]

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
    # 这些基线属于法律、数据治理与市场政策共同确认的部署级规则，不能和
    # 普通运营阈值一样直接开放给租户自行修改。若要 Web 化，必须先增加审批、
    # 证据来源和版本回滚流程。
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

    # --- Amazon SP-API transport controls (credentials live in provider_configs) ---
    AMAZON_REPORT_POLL_SECONDS: float = 5.0
    AMAZON_REPORT_TIMEOUT_SECONDS: float = 180.0
    AMAZON_SYNC_MAX_DAYS: int = 3

    # --- OpenTelemetry ---
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "shelook-backend"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""


settings = Settings()
