#!/usr/bin/env bash
# SheLook 一键部署 —— Linux/macOS
#
# 也就干这些事：检查环境、配 .env、build 镜像、起基础服务、
# 跑迁移、初始化 MinIO、塞演示数据、全量启动
#
# 懒人用法:
#   ./setup.sh                    # 全新部署
#   ./setup.sh --skip-build       # 跳过构建
#   ./setup.sh --clean --no-cache # 清干净重来
#   ./setup.sh --with-sdwebui     # 开本地 SD 生图（要 GPU）
#   ./setup.sh --stop / --restart # 停 / 重启
#   ./setup.sh --logs backend     # 看日志
#   ./setup.sh --status           # 看状态
#   ./setup.sh --update           # git pull + rebuild
#   ./setup.sh --env staging      # 指定环境

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 参数解析
SKIP_BUILD=false
SKIP_SEED=false
NO_CACHE=false
WITH_SDWEBUI=false
WITH_PGBOUNCER=false
CLEAN=false
STOP=false
RESTART=false
STATUS=false
UPDATE=false
LOGS_SVC=""
ENV_CHOICE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-build)    SKIP_BUILD=true; shift ;;
        --skip-seed)     SKIP_SEED=true; shift ;;
        --no-cache)      NO_CACHE=true; shift ;;
        --with-sdwebui)  WITH_SDWEBUI=true; shift ;;
        --with-pgbouncer) WITH_PGBOUNCER=true; shift ;;
        --env)           ENV_CHOICE="${2:-}"; shift 2 ;;
        --clean)         CLEAN=true; shift ;;
        --stop)          STOP=true; shift ;;
        --restart)       RESTART=true; shift ;;
        --status)        STATUS=true; shift ;;
        --update)        UPDATE=true; shift ;;
        --logs)          LOGS_SVC="${2:-}"; shift 2 ;;
        -h|--help)
            head -15 "$0"
            exit 0 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

# Compose 文件始终显式指定；staging / prod 追加环境覆盖文件
COMPOSE_FILES=(-f docker-compose.yml)

# 多环境配置：选择私有环境文件
if [ -n "$ENV_CHOICE" ]; then
    case "$ENV_CHOICE" in
        dev|staging|prod)
            env_file=".env.${ENV_CHOICE}"
            if [ ! -f "$env_file" ]; then
                if [ ! -f ".env.example" ]; then
                    echo -e "  \033[31m[ERROR]\033[0m .env.example 不存在"
                    exit 1
                fi
                cp .env.example "$env_file"
                if [ "$ENV_CHOICE" != "dev" ]; then
                    echo -e "  \033[33m[ENV]\033[0m 已创建 $env_file，请补齐该环境的密钥后重新执行"
                    exit 1
                fi
                echo -e "  \033[33m[ENV]\033[0m 已从 .env.example 创建 $env_file"
            fi
            cp "$env_file" .env
            echo -e "  \033[36m[ENV]\033[0m 已从 $env_file 复制到 .env"

            if [ "$ENV_CHOICE" = "staging" ] || [ "$ENV_CHOICE" = "prod" ]; then
                overlay="docker-compose.${ENV_CHOICE}.yml"
                if [ ! -f "$overlay" ]; then
                    echo -e "  \033[31m[ERROR]\033[0m Compose 覆盖文件 $overlay 不存在"
                    exit 1
                fi
                COMPOSE_FILES+=(-f "$overlay")
            fi
            ;;
        *)
            echo "无效环境: $ENV_CHOICE (可选: dev, staging, prod)"
            exit 1
            ;;
    esac
fi

# 输出辅助 —— 懒得每次写颜色
step()  { echo -e "\n\033[36m>>> $1\033[0m"; }
ok()    { echo -e "  \033[32m[OK]\033[0m   $1"; }
warn()  { echo -e "  \033[33m[WARN]\033[0m $1"; }
err()   { echo -e "  \033[31m[ERROR]\033[0m $1"; }
info()  { echo -e "  \033[90m[INFO]\033[0m $1"; }
dot()   { echo -e "  \033[90m..\033[0m     $1"; }

# Profile 参数拼接
PROFILE_ARGS=()
get_profile_args() {
    PROFILE_ARGS=()
    if $WITH_SDWEBUI;   then PROFILE_ARGS+=(--profile sd-webui); fi
    if $WITH_PGBOUNCER; then PROFILE_ARGS+=(--profile pgbouncer); fi
}

compose() {
    docker compose "${COMPOSE_FILES[@]}" "$@"
}

# 等健康 —— 轮询 docker inspect
wait_healthy() {
    local max_wait=${1:-180}
    local interval=${2:-5}
    shift 2
    local services=("$@")
    local start=$(date +%s)
    local all_healthy=false

    while true; do
        sleep "$interval"
        all_healthy=true
        local unhealthy=()
        for svc in "${services[@]}"; do
            local status
            status=$(docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "missing")
            if [ "$status" != "healthy" ]; then
                all_healthy=false
                unhealthy+=("$svc($status)")
            fi
        done
        if $all_healthy; then break; fi
        local elapsed=$(( $(date +%s) - start ))
        if [ "$elapsed" -ge "$max_wait" ]; then
            echo "${unhealthy[*]}"
            return 1
        fi
        dot "等待健康检查... (${elapsed}s / ${max_wait}s)"
    done
    return 0
}

# ---- 子命令模式 ----
# --status
if $STATUS; then
    step "服务运行状态"
    get_profile_args
    compose "${PROFILE_ARGS[@]}" ps 2>/dev/null || compose ps
    exit 0
fi

# --logs
if [ -n "$LOGS_SVC" ]; then
    echo -e "\n\033[36m>>> 跟踪 $LOGS_SVC 日志 (Ctrl+C 退出)\033[0m\n"
    compose logs -f "$LOGS_SVC"
    exit 0
fi

# --stop
if $STOP; then
    step "停止所有 SheLook 服务..."
    get_profile_args
    compose "${PROFILE_ARGS[@]}" down 2>/dev/null || true
    ok "所有服务已停止"
    exit 0
fi

# --restart
if $RESTART; then
    step "重启全部服务..."
    get_profile_args
    compose down 2>/dev/null || true
    compose "${PROFILE_ARGS[@]}" up -d
    ok "服务已重启"
    compose ps
    exit 0
fi

# --update
if $UPDATE; then
    step "更新部署 (保留数据)"

    info "重新构建镜像..."
    local_build_args=(build)
    $NO_CACHE && local_build_args+=(--no-cache)
    local_build_args+=(backend celery-worker frontend)
    compose "${local_build_args[@]}"
    ok "镜像构建完成"

    get_profile_args
    compose "${PROFILE_ARGS[@]}" up -d
    ok "服务已启动"

    info "执行数据库迁移..."
    compose run --rm backend alembic upgrade head 2>/dev/null
    ok "数据库迁移完成"

    ok "更新部署完成"
    compose ps
    exit 0
fi

# ==== 1/9  环境检查 ====
step "1/9  环境检查"

# Docker
if ! docker info >/dev/null 2>&1; then
    err "Docker 未运行或未安装"
    info "请先安装并启动 Docker: https://docs.docker.com/get-docker/"
    exit 1
fi
DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
ok "Docker 引擎运行正常 (v$DOCKER_VERSION)"

# docker compose
if ! docker compose version >/dev/null 2>&1; then
    err "docker compose 不可用"
    info "请安装 Docker Compose V2: https://docs.docker.com/compose/install/"
    exit 1
fi
COMPOSE_VER=$(docker compose version --short 2>/dev/null || echo "unknown")
ok "docker compose v$COMPOSE_VER"

# 磁盘空间 (至少 10GB)
FREE_KB=$(df -k "$SCRIPT_DIR" 2>/dev/null | awk 'NR==2{print $4}')
if [ -n "$FREE_KB" ] && [ "$FREE_KB" -lt 10485760 ]; then
    FREE_GB=$(echo "scale=1; $FREE_KB / 1048576" | bc 2>/dev/null || echo "?")
    warn "磁盘剩余空间不足: ${FREE_GB}GB (建议 >= 10GB)"
    info "构建镜像 + CLIP 模型 + 演示数据约需 8GB"
elif [ -n "$FREE_KB" ]; then
    FREE_GB=$(echo "scale=1; $FREE_KB / 1048576" | bc 2>/dev/null || echo "?")
    ok "磁盘空间充足 (${FREE_GB}GB 可用)"
fi

# 端口占用检测
PORTS=(80 3000 8000 5432 6379 9000 9001 5555)
PORT_CONFLICTS=()
for port in "${PORTS[@]}"; do
    if command -v ss >/dev/null 2>&1; then
        if ss -tlnp 2>/dev/null | grep -q ":${port} " ; then
            PORT_CONFLICTS+=("$port")
        fi
    elif command -v lsof >/dev/null 2>&1; then
        if lsof -i :"$port" -sTCP:LISTEN >/dev/null 2>&1; then
            PORT_CONFLICTS+=("$port")
        fi
    fi
done
if [ ${#PORT_CONFLICTS[@]} -gt 0 ]; then
    warn "检测到端口被占用: ${PORT_CONFLICTS[*]}"
    info "如为 SheLook 自身容器可忽略；如为其他进程请先释放端口"
else
    ok "所需端口均无冲突"
fi

# --Clean 模式
if $CLEAN; then
    step "清理现有部署..."
    get_profile_args
    compose "${PROFILE_ARGS[@]}" down -v 2>/dev/null || true
    ok "已清理所有容器和数据卷"
fi

# ==== 2/9  .env 配置 ====
step "2/9  .env 配置"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        ok "已从 .env.example 创建 .env"
    else
        err ".env.example 不存在"
        exit 1
    fi
else
    ok ".env 文件已存在"
fi

# 自动生成 SECRET_KEY
if grep -qE '^SECRET_KEY=\s*$' .env; then
    SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p)
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s/^SECRET_KEY=\s*$/SECRET_KEY=$SECRET_KEY/" .env
    else
        sed -i "s/^SECRET_KEY=\s*$/SECRET_KEY=$SECRET_KEY/" .env
    fi
    ok "SECRET_KEY 已自动生成 (64 位 hex)"
elif grep -qE '^SECRET_KEY=\S+' .env; then
    KEY_LEN=$(grep -oE '^SECRET_KEY=\S+' .env | head -1 | sed 's/^SECRET_KEY=//' | wc -c)
    if [ "$KEY_LEN" -lt 17 ]; then
        warn "SECRET_KEY 过短 ($((KEY_LEN-1)) 字符)，建议 >= 32 字符"
    else
        ok "SECRET_KEY 已配置 ($((KEY_LEN-1)) 字符)"
    fi
else
    SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p)
    echo "SECRET_KEY=$SECRET_KEY" >> .env
    ok "SECRET_KEY 已自动生成并追加到 .env"
fi

# 检查 API Key
if grep -qE '^GEMINI_API_KEY=\s*$' .env; then
    warn "[GEMINI_API_KEY] Gemini (标签提取 / AI 审核 / 促销图生成) 未配置"
fi
if grep -qE '^REPLICATE_API_TOKEN=\s*$' .env; then
    warn "[REPLICATE_API_TOKEN] Replicate (FLUX.2 Pro 生图) 未配置"
fi
if ! grep -qE '^GEMINI_API_KEY=\s*$' .env && ! grep -qE '^REPLICATE_API_TOKEN=\s*$' .env; then
    ok "推荐 API Key 已配置"
fi

# 可选视频 Key
for key in KLING_API_KEY RUNWAY_API_KEY; do
    if grep -qE "^${key}=\s*$" .env; then
        dot "可选: [$key] 未配置"
    fi
done

# ==== 3/9  构建 Docker 镜像 ====
step "3/9  构建 Docker 镜像"

if $SKIP_BUILD; then
    ok "跳过镜像构建 (--skip-build)"
else
    BUILD_ARGS=(build --build-arg BUILDKIT_INLINE_CACHE=1)
    $NO_CACHE && BUILD_ARGS+=(--no-cache)
    BUILD_ARGS+=(backend celery-worker frontend)
    info "正在构建镜像 (backend / celery / frontend)..."
    $NO_CACHE && dot "使用 --no-cache，构建时间较长"
    START_TS=$(date +%s)
    compose "${BUILD_ARGS[@]}"
    END_TS=$(date +%s)
    BUILD_SEC=$(( END_TS - START_TS ))
    BUILD_MIN=$(( BUILD_SEC / 60 ))
    BUILD_REM=$(( BUILD_SEC % 60 ))
    ok "镜像构建完成 (耗时 ${BUILD_MIN}m ${BUILD_REM}s)"
fi

# ==== 4/9  启动基础服务 (PostgreSQL / Redis / MinIO) ====
step "4/9  启动基础服务 (PostgreSQL / Redis / MinIO)"

compose up -d postgres redis minio
ok "基础服务容器已创建"

info "等待基础服务健康检查..."
if ! UNHEALTHY=$(wait_healthy 90 3 "shelook-postgres" "shelook-redis" "shelook-minio"); then
    err "基础服务未就绪: $UNHEALTHY"
    info "排查: docker compose logs postgres redis minio"
    exit 1
fi
ok "PostgreSQL / Redis / MinIO 全部健康"

# ==== 5/9  数据库迁移 ====
step "5/9  数据库迁移 (Alembic)"

info "执行 alembic upgrade head..."
compose run --rm backend alembic upgrade head 2>&1 | while read -r line; do
    case "$line" in
        INFO*|Running*|Revision*) dot "$line" ;;
        ERROR*) err "$line" ;;
    esac
done
ok "数据库迁移完成 (6 个版本已应用)"

# ==== 6/9  MinIO 初始化 ====
step "6/9  MinIO 存储初始化"

compose run --rm backend python scripts/init_minio.py 2>&1 | while read -r line; do
    case "$line" in
        *Bucket*|*policy*|*created*|*success*) dot "$line" ;;
    esac
done
ok "MinIO 存储桶已就绪 (product-images)"

# ==== 7/9  演示数据 ====
step "7/9  演示数据填充"

if $SKIP_SEED; then
    ok "跳过演示数据填充 (--skip-seed)"
else
    info "正在填充 Mock 演示数据..."
    compose run --rm backend python scripts/seed_data.py 2>&1 | while read -r line; do
        case "$line" in
            *Created*|*Inserted*|*Seed*|*Done*|*success*) dot "$line" ;;
        esac
    done
    ok "Mock 演示数据已填充"
fi

# ==== 8/9  启动全部应用服务 ====
step "8/9  启动全部应用服务"

get_profile_args
if [ ${#PROFILE_ARGS[@]} -gt 0 ]; then
    info "Profile: ${PROFILE_ARGS[*]}"
fi

compose "${PROFILE_ARGS[@]}" up -d
ok "应用服务容器已创建"

# 等待应用健康
info "等待应用服务健康就绪..."
APP_SERVICES=(
    "shelook-backend"
    "shelook-frontend"
    "shelook-nginx"
    "shelook-celery-worker"
    "shelook-celery-beat"
    "shelook-flower"
    "shelook-prometheus"
    "shelook-grafana"
)
if ! UNHEALTHY=$(wait_healthy 180 5 "${APP_SERVICES[@]}"); then
    warn "部分服务未就绪: $UNHEALTHY"
    info "可能原因: CLIP 模型首次下载较慢 / Celery worker 启动中"
    info "排查: docker compose ps ; docker compose logs <服务名>"
else
    ok "全部应用服务健康就绪"
fi

# ==== 9/9  验证 & 汇总 ====
step "9/9  验证与汇总"

# 后端 API
if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
    HEALTH=$(curl -sf http://localhost:8000/api/health 2>/dev/null)
    ok "后端 API 响应正常: $HEALTH"
else
    warn "后端 API 暂未响应"
    info "可能仍在初始化，稍后重试: curl http://localhost:8000/api/health"
fi

# 前端
if curl -sf -o /dev/null -w '%{http_code}' http://localhost:3000 2>/dev/null | grep -q 200; then
    ok "前端应用响应正常"
else
    warn "前端应用暂未响应"
fi

# Nginx
if curl -sf -o /dev/null -w '%{http_code}' http://localhost 2>/dev/null | grep -q 200; then
    ok "Nginx 反向代理正常"
else
    warn "Nginx 暂未响应"
fi

# 服务状态表
echo ""
echo -e "  \033[37m服务状态一览:\033[0m"
SERVICES=(
    "PostgreSQL|shelook-postgres|5432|"
    "Redis|shelook-redis|6379|"
    "MinIO|shelook-minio|9000|http://localhost:9001"
    "Backend (FastAPI)|shelook-backend|8000|http://localhost:8000/docs"
    "Celery Worker|shelook-celery-worker||"
    "Celery Beat|shelook-celery-beat||"
    "Flower|shelook-flower|5555|http://localhost:5555/flower"
    "Frontend (Next.js)|shelook-frontend|3000|http://localhost:3000"
    "Nginx|shelook-nginx|80|http://localhost"
    "Prometheus|shelook-prometheus|9090|http://localhost:9090"
    "Grafana|shelook-grafana|3001|http://localhost/grafana/"
)
for svc in "${SERVICES[@]}"; do
    IFS='|' read -r name container port url <<< "$svc"
    status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || \
             docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || echo "missing")
    if [ "$status" = "healthy" ] || [ "$status" = "running" ]; then
        COLOR="\033[32m"
    else
        COLOR="\033[33m"
    fi
    printf "  ${COLOR}[%s]\033[0m %-22s :%-5s \033[36m%s\033[0m\n" "$status" "$name" "$port" "$url"
done

# ==== 部署完成 ====
echo ""
echo -e "\033[32m============================================================\033[0m"
echo -e "\033[32m  SheLook 部署完成!\033[0m"
echo -e "\033[32m============================================================\033[0m"
echo ""
echo -e "  \033[37m访问地址:\033[0m"
echo -e "    \033[36m统一入口 (Nginx)     http://localhost\033[0m"
echo -e "    \033[36m前端应用              http://localhost:3000\033[0m"
echo -e "    \033[36m后端 Swagger          http://localhost:8000/docs\033[0m"
echo -e "    \033[36mMinIO 控制台          http://localhost:9001\033[0m"
echo -e "    \033[36mFlower 任务监控       http://localhost:5555/flower\033[0m"
echo -e "    \033[36mPrometheus            http://localhost:9090\033[0m"
echo -e "    \033[36mGrafana               http://localhost/grafana/\033[0m"
echo ""
echo -e "  \033[37m常用命令:\033[0m"
echo -e "    \033[90m查看状态    ./setup.sh --status\033[0m"
echo -e "    \033[90m查看日志    ./setup.sh --logs backend\033[0m"
echo -e "    \033[90m重启服务    ./setup.sh --restart\033[0m"
echo -e "    \033[90m停止服务    ./setup.sh --stop\033[0m"
echo -e "    \033[90m更新部署    ./setup.sh --update\033[0m"
echo ""
