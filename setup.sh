#!/usr/bin/env bash
# SheLook 的安全部署入口（Linux / macOS）。
#
# 所有 Compose 调用显式使用 .env.<environment>。默认不会写入演示数据；只有
# `--env dev --seed-demo` 且经过二次确认时，才会调用 scripts.seed_data。

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SKIP_BUILD=false
SKIP_SEED=false
SEED_DEMO=false
CONFIRM_SEED_DEMO=false
NO_CACHE=false
WITH_SDWEBUI=false
WITH_PGBOUNCER=false
WITH_OPS=false
CLEAN=false
STOP=false
RESTART=false
STATUS=false
UPDATE=false
LOGS_SVC=""
ENV_CHOICE="dev"
ENV_FILE=""
COMPOSE_OPTIONS=()

usage() {
    cat <<'EOF'
SheLook 部署脚本

  ./setup.sh                               开发环境部署（默认，不填充演示数据）
  ./setup.sh --env staging --update        使用不可变镜像更新预发环境
  ./setup.sh --env prod --status           查看生产环境服务状态
  ./setup.sh --seed-demo                   仅开发环境：填充演示数据，并要求二次确认
  ./setup.sh --seed-demo --confirm-seed-demo
                                           非交互式二次确认

常用参数：
  --skip-build --no-cache --with-sdwebui --with-pgbouncer --with-ops --clean --stop --restart
  --logs <service> --status --update --env <dev|staging|prod>

环境文件：
  使用 .env.dev / .env.staging / .env.prod；缺失时仅从对应的
  .env.<environment>.example（或 .env.example）创建一次，绝不覆盖 .env。
EOF
}

step() { printf '\n\033[36m>>> %s\033[0m\n' "$1"; }
ok() { printf '  \033[32m[OK]\033[0m   %s\n' "$1"; }
warn() { printf '  \033[33m[WARN]\033[0m %s\n' "$1"; }
err() { printf '  \033[31m[ERROR]\033[0m %s\n' "$1" >&2; }
info() { printf '  \033[90m[INFO]\033[0m %s\n' "$1"; }

on_error() {
    local exit_code=$?
    err "命令失败（退出码 ${exit_code}，第 ${BASH_LINENO[0]} 行）：${BASH_COMMAND}"
    exit "$exit_code"
}
trap on_error ERR

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-build) SKIP_BUILD=true; shift ;;
        --skip-seed) SKIP_SEED=true; shift ;;
        --seed-demo) SEED_DEMO=true; shift ;;
        --confirm-seed-demo) CONFIRM_SEED_DEMO=true; shift ;;
        --no-cache) NO_CACHE=true; shift ;;
        --with-sdwebui) WITH_SDWEBUI=true; shift ;;
        --with-pgbouncer) WITH_PGBOUNCER=true; shift ;;
        --with-ops) WITH_OPS=true; shift ;;
        --clean) CLEAN=true; shift ;;
        --stop) STOP=true; shift ;;
        --restart) RESTART=true; shift ;;
        --status) STATUS=true; shift ;;
        --update) UPDATE=true; shift ;;
        --logs)
            [[ $# -ge 2 ]] || { err "--logs 需要服务名"; exit 1; }
            LOGS_SVC="$2"; shift 2 ;;
        --env)
            [[ $# -ge 2 ]] || { err "--env 需要 dev、staging 或 prod"; exit 1; }
            ENV_CHOICE="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) err "未知参数：$1"; usage; exit 1 ;;
    esac
done

case "$ENV_CHOICE" in
    dev|staging|prod) ;;
    *) err "无效环境：$ENV_CHOICE（仅支持 dev、staging、prod）"; exit 1 ;;
esac

get_env_value() {
    local name="$1"
    local path="$2"
    local line value
    line=$(grep -E "^[[:space:]]*${name}[[:space:]]*=" "$path" | tail -n 1 || true)
    value="${line#*=}"
    value="${value%$'\r'}"
    if [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]] || [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
        value="${value:1:${#value}-2}"
    fi
    printf '%s' "$value"
}

set_env_value() {
    local name="$1"
    local value="$2"
    local path="$3"
    local temp_file
    temp_file="$(mktemp "${path}.tmp.XXXXXX")"
    awk -v key="$name" -v replacement="${name}=${value}" '
        BEGIN { updated = 0 }
        $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
            print replacement
            updated = 1
            next
        }
        { print }
        END {
            if (!updated) print replacement
        }
    ' "$path" > "$temp_file"
    mv "$temp_file" "$path"
}

new_secret_key() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
    fi
}

is_unsafe_secret_value() {
    local value="${1:-}"
    local normalized
    normalized="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]' | xargs)"
    case "$normalized" in
        ""|shelook|shelook-dev|shelook123|shelook-dev-minio|shelook-dev-secret|shelook-dev-insecure-key-change-in-production|password|secret|changeme|change-me|replace-me|example|test|demo|admin|your-secret)
            return 0
            ;;
    esac
    [[ "$normalized" =~ ^\<.*\>$ || "$normalized" =~ ^\$\{.*\}$ || "$normalized" =~ ^your[-_].* || "$normalized" =~ (todo|placeholder) ]]
}

validate_non_development_environment() {
    local errors=()
    local name value expected actual normalized_actual

    for name in BACKEND_IMAGE FRONTEND_IMAGE; do
        value="$(get_env_value "$name" "$ENV_FILE")"
        if [[ ! "$value" =~ @sha256:[[:xdigit:]]{64}$ ]]; then
            errors+=("${name} must be digest-pinned (image@sha256:<64 hex characters>)")
        fi
    done

    for name in SECRET_KEY INTEGRATION_CREDENTIALS_ENCRYPTION_KEY POSTGRES_PASSWORD REDIS_PASSWORD MINIO_ROOT_PASSWORD MINIO_SECRET_KEY METRICS_API_KEY GRAFANA_ADMIN_PASSWORD; do
        value="$(get_env_value "$name" "$ENV_FILE")"
        if is_unsafe_secret_value "$value"; then
            errors+=("${name} must be set and must not use a development placeholder")
        fi
    done

    value="$(get_env_value CORS_ORIGINS "$ENV_FILE")"
    if [[ -z "$value" || "$value" =~ (localhost|127\.0\.0\.1|example\.com|your[-_]) ]]; then
        errors+=("CORS_ORIGINS must contain non-development origins")
    fi

    value="$(get_env_value GRAFANA_ROOT_URL "$ENV_FILE")"
    if [[ ! "$value" =~ ^https:// || "$value" =~ (localhost|127\.0\.0\.1|example\.com|your[-_]) ]]; then
        errors+=("GRAFANA_ROOT_URL must be a non-development HTTPS URL ending in /grafana/")
    elif [[ ! "$value" =~ /grafana/$ ]]; then
        errors+=("GRAFANA_ROOT_URL must end in /grafana/")
    fi

    for expected in ENABLE_AUTH:true ALLOW_GENERATION_MOCKS:false C2PA_ENABLED:true C2PA_REQUIRED:true; do
        name="${expected%%:*}"
        value="${expected#*:}"
        actual="$(get_env_value "$name" "$ENV_FILE")"
        normalized_actual="$(printf '%s' "$actual" | tr '[:upper:]' '[:lower:]' | xargs)"
        if [[ "$normalized_actual" != "$value" ]]; then
            errors+=("${name} must be ${value}")
        fi
    done

    if [[ -z "$(get_env_value DATABASE_MIGRATION_URL "$ENV_FILE")" ]]; then
        errors+=("DATABASE_MIGRATION_URL must be set")
    fi
    for name in METRICS_API_KEY_FILE C2PA_CERT_FILE C2PA_PRIVATE_KEY_FILE; do
        value="$(get_env_value "$name" "$ENV_FILE")"
        if [[ -z "$value" ]]; then
            errors+=("${name} must be set")
        elif [[ ! -f "$value" ]]; then
            errors+=("${name} must reference an existing regular file")
        fi
    done

    if [[ ${#errors[@]} -gt 0 ]]; then
        err "Staging/production preflight failed. No secret values were printed:"
        for value in "${errors[@]}"; do
            err "  - ${value}"
        done
        exit 1
    fi
}

initialize_environment_file() {
    ENV_FILE=".env.${ENV_CHOICE}"
    local specific_template=".env.${ENV_CHOICE}.example"
    local template=""

    if [[ ! -f "$ENV_FILE" ]]; then
        if [[ -f "$specific_template" ]]; then
            template="$specific_template"
        elif [[ -f ".env.example" ]]; then
            template=".env.example"
        else
            err "未找到 ${specific_template} 或 .env.example，无法创建环境文件。"
            exit 1
        fi
        cp "$template" "$ENV_FILE"
        warn "已从 ${template} 创建 ${ENV_FILE}；请审阅其中的环境变量和密钥。"
    fi

    local secret
    secret="$(get_env_value SECRET_KEY "$ENV_FILE")"
    if [[ -z "$secret" ]]; then
        if [[ "$ENV_CHOICE" != "dev" ]]; then
            err "${ENV_FILE} 的 SECRET_KEY 不能为空。请通过密钥管理系统生成并写入后重试。"
            exit 1
        fi
        set_env_value SECRET_KEY "$(new_secret_key)" "$ENV_FILE"
        ok "已仅在 ${ENV_FILE} 中生成开发环境 SECRET_KEY"
    fi

    if [[ "$ENV_CHOICE" == "staging" || "$ENV_CHOICE" == "prod" ]]; then
        local overlay
        overlay="docker-compose.${ENV_CHOICE}.yml"
        [[ -f "$overlay" ]] || { err "缺少 Compose 覆盖文件：${overlay}"; exit 1; }
        validate_non_development_environment
    fi

    COMPOSE_OPTIONS=(--env-file "$ENV_FILE" -f docker-compose.yml)
    if [[ "$ENV_CHOICE" == "staging" || "$ENV_CHOICE" == "prod" ]]; then
        COMPOSE_OPTIONS+=(-f "docker-compose.${ENV_CHOICE}.yml")
    fi
    info "环境：${ENV_CHOICE}；Compose 使用：${ENV_FILE}（不会修改 .env）"
}

profile_args=()
get_profile_args() {
    profile_args=()
    if "$WITH_SDWEBUI"; then
        profile_args+=(--profile sd-webui)
    fi
    if "$WITH_PGBOUNCER"; then
        profile_args+=(--profile pgbouncer)
    fi
    if "$WITH_OPS"; then
        profile_args+=(--profile ops)
    fi
}

compose() {
    docker compose "${COMPOSE_OPTIONS[@]}" "$@"
}

service_state() {
    local service="$1"
    local container_id state
    container_id="$(docker compose "${COMPOSE_OPTIONS[@]}" ps -q "$service" 2>/dev/null | head -n 1 || true)"
    if [[ -z "$container_id" ]]; then
        printf 'not-started'
        return
    fi
    state="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
    printf '%s' "${state:-unknown}"
}

wait_for_services() {
    local timeout="$1"
    local interval="$2"
    shift 2
    local services=("$@")
    local start now elapsed service state
    start="$(date +%s)"

    while true; do
        local unready=()
        for service in "${services[@]}"; do
            state="$(service_state "$service")"
            if [[ "$state" != "healthy" && "$state" != "running" ]]; then
                unready+=("${service} (${state})")
            fi
        done
        if [[ ${#unready[@]} -eq 0 ]]; then
            return 0
        fi
        now="$(date +%s)"
        elapsed=$((now - start))
        if (( elapsed >= timeout )); then
            err "服务未在 ${timeout} 秒内就绪：${unready[*]}"
            return 1
        fi
        sleep "$interval"
    done
}

test_docker() {
    command -v docker >/dev/null 2>&1 || { err "未找到 Docker CLI。"; exit 1; }
    docker info >/dev/null 2>&1 || { err "Docker 未运行或当前用户无访问权限。"; exit 1; }
    docker compose version >/dev/null 2>&1 || { err "docker compose v2 不可用。"; exit 1; }
}

BUILD_SERVICES=(
    backend
    migrate
    celery-worker
    celery-worker-generation
    celery-worker-analytics
    celery-beat
    flower
    frontend
)
CORE_SERVICES=(postgres redis minio)
CRITICAL_APPLICATION_SERVICES=(
    backend
    frontend
    nginx
    celery-worker
    celery-worker-generation
    celery-worker-analytics
    celery-beat
)

prepare_images() {
    if "$SKIP_BUILD"; then
        info "跳过镜像准备（--skip-build）。将使用本机已存在的镜像。"
        return
    fi

    if [[ "$ENV_CHOICE" == "dev" ]]; then
        local build_args=(build --build-arg BUILDKIT_INLINE_CACHE=1)
        "$NO_CACHE" && build_args+=(--no-cache)
        build_args+=("${BUILD_SERVICES[@]}")
        step "构建开发镜像（API、迁移、全部 Worker 与前端）"
        compose "${build_args[@]}"
        return
    fi

    "$NO_CACHE" && warn "--no-cache 仅适用于开发环境构建，${ENV_CHOICE} 环境将忽略该参数。"
    step "拉取 ${ENV_CHOICE} 不可变镜像（API、迁移、全部 Worker 与前端）"
    compose pull "${BUILD_SERVICES[@]}"
}

run_migrations() {
    step "执行数据库迁移（独立 migrate 服务）"
    compose --profile migration run --rm migrate
    ok "数据库迁移已完成（alembic head）"
}

initialize_object_storage() {
    step "初始化对象存储"
    compose run --rm --no-deps backend python scripts/init_minio.py
    ok "MinIO 存储桶已就绪"
}

confirm_demo_seed() {
    if ! "$SEED_DEMO"; then
        info "默认不写入演示数据。需要演示数据时，请在开发环境执行 --seed-demo。"
        return 1
    fi
    if [[ "$ENV_CHOICE" != "dev" ]]; then
        warn "${ENV_CHOICE} 环境禁止填充演示数据；已强制跳过。"
        return 1
    fi
    if "$SKIP_SEED"; then
        err "--seed-demo 与 --skip-seed 不能同时使用。"
        exit 1
    fi
    if "$CONFIRM_SEED_DEMO"; then
        return 0
    fi

    warn "演示数据会写入当前开发数据库，不能用于已有业务数据。"
    local confirmation
    read -r -p "请输入 SEED-DEMO 确认填充演示数据: " confirmation
    [[ "$confirmation" == "SEED-DEMO" ]] || { err "未完成演示数据二次确认，已取消。"; exit 1; }
}

seed_demo_data() {
    if ! confirm_demo_seed; then
        return
    fi
    step "填充开发演示数据"
    compose run --rm --no-deps backend python -m scripts.seed_data
    ok "开发演示数据已填充"
}

start_platform() {
    local force_recreate="${1:-false}"
    local up_args=()

    step "启动基础服务"
    compose up -d "${CORE_SERVICES[@]}"
    wait_for_services 120 3 "${CORE_SERVICES[@]}"
    ok "PostgreSQL、Redis 与 MinIO 已就绪"

    run_migrations
    initialize_object_storage
    seed_demo_data

    step "启动应用服务"
    get_profile_args
    up_args=("${profile_args[@]}" up -d --remove-orphans)
    [[ "$force_recreate" == "true" ]] && up_args+=(--force-recreate)
    compose "${up_args[@]}"
    wait_for_services 240 5 "${CRITICAL_APPLICATION_SERVICES[@]}"
    ok "关键应用服务已就绪"
}

show_summary() {
    step "部署状态"
    compose ps
    local default_port nginx_port health_url
    default_port="80"
    [[ "$ENV_CHOICE" == "staging" ]] && default_port="8080"
    nginx_port="$(get_env_value NGINX_PORT "$ENV_FILE")"
    nginx_port="${nginx_port:-$default_port}"
    if [[ "$nginx_port" == "80" ]]; then
        health_url="http://localhost/api/health"
    else
        health_url="http://localhost:${nginx_port}/api/health"
    fi
    if curl -fsS --max-time 10 "$health_url" >/dev/null 2>&1; then
        ok "健康检查通过：${health_url}"
    else
        warn "本机反向代理健康检查未通过；请使用 --logs nginx 或 --logs backend 查看原因。"
    fi
    printf '\n常用操作：\n  ./setup.sh --env %s --status\n  ./setup.sh --env %s --logs backend\n  ./setup.sh --env %s --stop\n' "$ENV_CHOICE" "$ENV_CHOICE" "$ENV_CHOICE"
}

initialize_environment_file
test_docker

if "$STATUS"; then
    get_profile_args
    compose "${profile_args[@]}" ps
    exit 0
fi
if [[ -n "$LOGS_SVC" ]]; then
    compose logs -f "$LOGS_SVC"
    exit 0
fi
if "$STOP"; then
    step "停止 ${ENV_CHOICE} 环境服务"
    get_profile_args
    compose "${profile_args[@]}" down || true
    ok "服务已停止（数据卷保留）"
    exit 0
fi
if "$CLEAN"; then
    warn "--clean 会删除 ${ENV_CHOICE} 环境对应 Compose 项目的数据卷。"
    get_profile_args
    compose "${profile_args[@]}" down -v --remove-orphans || true
    ok "容器与数据卷已清理"
fi
if "$RESTART"; then
    step "重启 ${ENV_CHOICE} 环境（先迁移，后重建应用容器）"
    start_platform true
    show_summary
    exit 0
fi

prepare_images
if "$UPDATE"; then
    info "--update 会部署当前工作区或仓库中已拉取的镜像；不会自动执行 git pull。"
fi
start_platform false
show_summary
