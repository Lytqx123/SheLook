# ============================================================
# SheLook FastAPI 后端
# Python 3.13 + Uvicorn + uv 包管理
# ============================================================
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.5.11
FROM python:3.13-slim-bookworm

ARG APT_MIRROR=deb.debian.org
ARG UV_IMAGE
ARG UV_DEFAULT_INDEX=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    APP_HOME=/app

WORKDIR $APP_HOME

# 系统依赖（psycopg2、Pillow C 扩展及运维探针）
RUN sed -i "s#deb.debian.org#${APT_MIRROR}#g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libjpeg-dev \
        zlib1g-dev \
        curl \
        procps \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# API、Celery Worker/Beat 与 Flower 共用同一 uv 版本和依赖镜像。
COPY --from=${UV_IMAGE} /uv /usr/local/bin/uv

# pyproject.toml 声明依赖，uv.lock 锁定完整解析结果。
# 只同步第三方依赖以复用 Docker 缓存；运行时直接从 /app 导入项目源码。
ARG PYTHON_EXTRAS=providers,observability
COPY pyproject.toml uv.lock ./
RUN set -eu; \
    extra_args=""; \
    old_ifs="$IFS"; \
    IFS=','; \
    for extra in $PYTHON_EXTRAS; do extra_args="$extra_args --extra $extra"; done; \
    IFS="$old_ifs"; \
    sync_args="--locked"; \
    if [ -n "$UV_DEFAULT_INDEX" ]; then sync_args=""; export UV_DEFAULT_INDEX; fi; \
    uv sync $sync_args --no-install-project --no-dev $extra_args

COPY . .

ENV PATH="/opt/venv/bin:$PATH"

# 非 root 运行。
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser $APP_HOME
USER appuser

# 数据库迁移由受控的 migrate Job/Compose service 单独执行。API 容器只提供
# 应用进程，避免运行账号获得 schema-owner 权限或在多副本启动时竞争迁移。
# 启用 OTEL 时可改用：opentelemetry-instrument uvicorn app.main:app --host 0.0.0.0 --port 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers=${API_WORKERS:-3}"]
