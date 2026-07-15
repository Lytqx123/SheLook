# SheLook

SheLook 是一个面向电商商品视觉运营的 AI 决策系统。系统把商品建档、视觉方案推荐、图片生成、质量审核、效果预测、A/B 实验、经营指标回流和模型迭代组织成一条可运行的业务链路。

当前仓库同时包含前端应用、后端 API、异步任务、数据库迁移、对象存储、反向代理和监控配置，可通过 Docker Compose 在本地或服务器环境部署。

## 当前功能

| 业务模块 | 当前能力 |
| --- | --- |
| 发品工作台 | 创建商品、以图搜图、视觉方案推荐、生成任务与进度跟踪 |
| 商品管理 | 商品查询、编辑、删除、发布及详情查看 |
| 预测决策 | 按图片或方案预测 CTR、爆款概率和退货风险，查看预测结果 |
| 审核工作台 | 自动审核、人工通过/驳回、审核队列与质量详情 |
| 公平性分析 | 肤色分布统计、市场基线对比、方案级偏差检查 |
| 供应商分析 | 供应商图片质量分析、维度评分、标杆对比和历史报告 |
| A/B 实验 | 实验创建、停止、分维度结果、自动建实验和流量调整 |
| 数据飞轮 | 指标回流、样本标注、模型重训、模型版本查看与回滚 |
| 数据看板 | 经营概览、CTR 趋势、市场表现和风格标签洞察 |
| 聚类分析 | K-Means/HDBSCAN 聚类与 t-SNE 降维结果展示 |
| 指标数据 | 手工批量写入、Shopee/Amazon 同步、外部商品映射和统计 |
| 平台导出 | Amazon、天猫、TikTok Shop、TikTok 方图和 Shopify 图片规格 |
| 视频生成 | Kling 与 Runway 提供方状态检查和视频生成入口 |
| 审计与监控 | 操作日志、请求链路、Prometheus 指标、Grafana 和 Flower |

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | Next.js 16、React 19、TypeScript 6、Ant Design 6、Tailwind CSS 4、TanStack Query 5、Zustand 5、Recharts 3 |
| 后端 | Python 3.13、FastAPI 0.139、Pydantic 2、SQLAlchemy 2 Async、Alembic |
| AI/数据 | PyTorch、Transformers、CLIP、scikit-learn、HDBSCAN、pgvector |
| 异步任务 | Celery 5、Redis 8、Flower |
| 持久化 | PostgreSQL 17 + pgvector、MinIO |
| 可观测性 | structlog、Prometheus、Grafana、可选 OpenTelemetry |
| 部署 | Docker Compose、Nginx |

## 系统拓扑

```text
Browser
   │
   ▼
Nginx :80
   ├── /              → Next.js :3000
   ├── /api/*         → FastAPI :8000
   ├── /images/*      → MinIO :9000
   ├── /flower/*      → Flower :5555
   └── /grafana/*     → Grafana :3000

FastAPI / Celery
   ├── PostgreSQL + pgvector
   ├── Redis
   ├── MinIO
   └── 外部 AI / 电商平台 API（按配置启用）
```

默认编排包含 11 个核心服务：`postgres`、`redis`、`minio`、`backend`、`celery-worker`、`celery-beat`、`flower`、`frontend`、`nginx`、`prometheus`、`grafana`。

可选服务：

- `pgbouncer`：PostgreSQL 连接池。
- `sd-webui`：本地图片生成降级通道，需要 NVIDIA GPU。

## 快速启动

### 前置条件

- Docker Desktop，或 Docker Engine + Docker Compose。
- 建议为 Docker 分配至少 10 GB 内存；加载 CLIP 和运行 Celery Worker 时需要较多内存。
- 如需真实图片/视频生成或平台指标同步，请准备相应的第三方凭据。

### Windows

```powershell
.\setup.ps1 -Env dev
```

### Linux / macOS

```bash
chmod +x setup.sh
./setup.sh --env dev
```

部署脚本会完成环境检查、生成/加载 `.env`、构建镜像、启动基础服务、执行数据库迁移、初始化 MinIO、填充演示数据并启动全部服务。

常用参数：

```powershell
.\setup.ps1 -SkipBuild             # 复用现有镜像
.\setup.ps1 -SkipSeed              # 不填充演示数据
.\setup.ps1 -NoCache               # 无缓存构建
.\setup.ps1 -WithPgbouncer         # 启用连接池
.\setup.ps1 -WithSDWebUI           # 启用本地生图通道
.\setup.ps1 -Status                # 查看服务状态
.\setup.ps1 -Logs backend          # 跟踪后端日志
.\setup.ps1 -Restart               # 重启全部服务
.\setup.ps1 -Stop                  # 停止全部服务
```

Linux/macOS 参数使用同名短横线形式，例如 `--skip-build`、`--with-pgbouncer`、`--logs backend`。

## 访问地址

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 统一入口 | <http://localhost> | 推荐入口，由 Nginx 分发前端、API、图片和监控页面 |
| 前端直连 | <http://localhost:3000> | 开发/基础编排下的 Next.js 地址 |
| 后端直连 | <http://localhost:8000> | 开发/基础编排下的 FastAPI 地址 |
| API 文档 | <http://localhost/docs> | 仅在后端 `DEBUG=true` 时启用 |
| MinIO 控制台 | <http://localhost:9001> | 凭据读取 `.env` |
| Flower | <http://localhost/flower/> | Celery 任务监控 |
| Prometheus | <http://localhost:9090> | 指标查询 |
| Grafana | <http://localhost/grafana/> | 可视化监控看板 |

健康检查：

```text
GET /api/health
GET /api/health/ready
```

## 环境配置

完整、可提交的配置模板位于 [`.env.example`](./.env.example)。`.env`、`.env.dev`、`.env.staging` 和 `.env.prod` 都是本机私有文件并由 Git 忽略；可从 `.env.example` 复制后按目标环境填写。

主要外部能力配置：

| 配置 | 用途 | 未配置时 |
| --- | --- | --- |
| `REPLICATE_API_TOKEN` | FLUX 图片生成 | 尝试其他已配置图片通道 |
| `GEMINI_API_KEY` | Google 图片生成、标签与部分审核能力 | 使用其他通道或本地能力 |
| `KLING_API_KEY` / Kling AK/SK | Kling 视频生成 | Kling 不可用 |
| `RUNWAY_API_KEY` | Runway 视频生成 | Runway 不可用 |
| `SHOPEE_*` | Shopee 指标同步 | 该平台同步不可用 |
| `AMAZON_*` | Amazon SP-API 指标同步 | 该平台同步不可用 |
| `METRICS_API_KEY` | 指标写接口鉴权 | 开发环境可为空；生产环境禁止为空 |
| `OIDC_*` | 企业 OIDC 登录 | `ENABLE_AUTH=false` 时使用开发登录流程 |
| `C2PA_*` | AI 内容签名与验证 | 开发环境可关闭；生产环境必须配置 |
| `OTEL_*` | OpenTelemetry 导出 | 关闭分布式追踪，不影响基础指标 |

开发环境允许 `ALLOW_GENERATION_MOCKS=true`，用于验证完整任务链路。生产环境启动检查要求：启用 OIDC、关闭生成 Mock、配置指标 API Key、启用并强制 C2PA、提供签名证书和私钥，并使用非默认安全凭据。

## 多环境部署

```bash
# 开发/默认编排
docker compose up -d

# 或使用部署脚本选择开发环境
./setup.sh --env dev

# Staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d
# 部署脚本：./setup.sh --env staging

# Production
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# 部署脚本：./setup.sh --env prod
```

Windows 对应使用 `setup.ps1 -Env dev|staging|prod`。如果 staging 或 production 的私有环境文件不存在，脚本会从 `.env.example` 创建文件并停止，待补齐密钥后再次执行。

生产覆盖配置使用 Compose `!reset` 清除前端、后端和 Flower 的宿主机端口，业务流量统一经过 Nginx。生产启动前需先补齐 `.env.prod` 和 `secrets/` 下的 C2PA 文件。

## 开发与验证

### 前端

```bash
cd frontend
npm ci
npm run dev
npm run lint
npx tsc --noEmit
npm run build
```

### 后端

```bash
cd backend
uv sync --extra providers --extra observability --extra dev
uv run pytest -v
uv run ruff check app tests
```

### 数据库迁移

```bash
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend alembic current
```

### API 冒烟与性能测试

只读冒烟脚本会先取得开发 token；生产/OIDC 环境通过 `-Token` 或 `SHELOOK_TOKEN` 传入有效 token：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\api_test.ps1
```

Locust 默认只执行已认证的只读请求，写入型预测和生图场景需显式启用。完整方法见 [PERFORMANCE.md](./PERFORMANCE.md)。

### 服务管理

```bash
docker compose ps
docker compose logs -f backend
docker compose restart backend
docker compose down
```

## 目录结构

```text
shelook/
├── frontend/                    # Next.js 前端
├── backend/                     # FastAPI、Celery、模型与迁移
│   ├── app/models/              # SQLAlchemy ORM 源码
│   └── models/                  # 预测模型与回滚版本（运行时生成）
├── nginx/                       # 统一入口与反向代理
├── grafana/                     # 数据源和看板配置
├── scripts/                     # Locust 等项目级脚本
├── docker-compose.yml           # 基础服务编排
├── docker-compose.staging.yml   # Staging 覆盖配置
├── docker-compose.prod.yml      # Production 覆盖配置
├── setup.ps1                    # Windows 部署脚本
├── setup.sh                     # Linux/macOS 部署脚本
└── .env.example                 # 完整环境变量模板
```

## 详细文档

- [项目介绍](./项目介绍.md)：产品定位、功能边界、业务闭环和整体架构。
- [前端说明](./前端.md)：页面、组件、状态管理、样式规范和前端开发方式。
- [后端说明](./后端.md)：API、服务层、数据模型、异步任务、安全与运维。
- [性能说明](./PERFORMANCE.md)：性能相关配置和压测方式。

## 当前边界

- 第三方图片生成、视频生成和电商平台同步是否可用，取决于环境变量、账号权限和外部服务状态。
- 开发 Mock 只用于验证任务流程，不代表真实 AI 生成质量。
- 公平性基线来自运营配置，正式使用前应由当地数据、合规和法务负责人确认。
- Swagger/ReDoc 由 `DEBUG` 控制；生产环境默认关闭。
