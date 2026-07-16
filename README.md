# SheLook

一个面向电商运营的视觉决策工具。让运营在商品上架前就能大致了解不同视觉方案的潜力，上架后做 AB 对比，积累数据后还能回流优化模型。

## 解决的问题

同一件商品换个主图，点击和转化可能差 30%+。但现在大多数团队选图还是靠经验和直觉。这个项目尝试让流程更可量化——上架前预测效果，审核时有依据，实验中有对比，决策后能积累经验。

> TODO: 等有了足够多的线上数据，把一些典型 case 的效果差异整理出来

## 核心能力

| 模块 | 做什么 |
| --- | --- |
| 发品工作台 | 建档、以图搜图、方案推荐、AI 生图、质检 |
| 预测决策 | 单图预测 + 批量对比，预估 CTR / 爆款概率 / 退货风险 |
| 审核工作台 | 三级自动审核 + 人工决策 |
| A/B 实验 | 方案对比、自动流量分配、显著性检验 |
| 数据飞轮 | 指标回流、样本标注、模型重训和版本管理 |
| 数据看板 | 核心指标、CTR 趋势、市场对比、风格洞察 |
| 聚类分析 | 视觉特征聚类，发现视觉模式和经营效果的关联 |
| 供应商分析 | 供应商素材多维度评分 |
| 公平性分析 | 肤色分布统计、市场基线对比 |
| 指标管理 | 批量写入、Shopee/Amazon 同步 |
| 平台导出 | 适配 Amazon/天猫/TikTok 等平台规格 |
| 审计日志 | 操作记录和请求链路追踪 |

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | Next.js 16、React 19、TypeScript、Ant Design 6、Tailwind CSS 4、TanStack Query、Recharts |
| 后端 | Python 3.13、FastAPI、SQLAlchemy 2 Async、Pydantic 2 |
| AI / 数据 | PyTorch、CLIP、Transformers、scikit-learn、HDBSCAN、pgvector |
| 异步任务 | Celery 5、Redis、Flower |
| 存储 | PostgreSQL 17 + pgvector、MinIO |
| 监控 | Prometheus、Grafana、structlog |
| 部署 | Docker Compose、Nginx |

## 快速开始

### 前置条件

- Docker Desktop（或 Docker Engine + Compose）
- 给 Docker 分至少 10 GB 内存
- 生图和平台同步需要对应的第三方 API 凭据

### Windows

```powershell
.\setup.ps1 -Env dev
```

### Linux / macOS

```bash
chmod +x setup.sh
./setup.sh --env dev
```

上边两个脚本会自动搞定环境检查、构建、迁移、演示数据和全量启动。

### 手动启动

```bash
docker compose up -d
```

### 访问地址

| 服务 | 地址 |
| --- | --- |
| 统一入口 | <http://localhost> |
| 前端 | <http://localhost:3000> |
| 后端 Swagger | <http://localhost:8000/docs> |
| MinIO | <http://localhost:9001> |
| Flower | <http://localhost/flower/> |
| Prometheus | <http://localhost:9090> |
| Grafana | <http://localhost/grafana/> |

## 多环境

```bash
# 开发
docker compose up -d

# Staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d

# Production
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

生产环境启动前记得补齐 `.env.prod` 里的安全配置，不然启动校验会拦。

## 第三方服务

主要外部依赖（未配则降级）：

| 配置 | 用途 | 没配的话 |
| --- | --- | --- |
| `GEMINI_API_KEY` | 生图 + 部分审核 | 试其他通道 |
| `REPLICATE_API_TOKEN` | FLUX 生图 | 试其他通道 |
| `KLING_API_KEY` | 视频生成 | 不可用 |
| `RUNWAY_API_KEY` | 视频生成 | 不可用 |
| `SHOPEE_*` | Shopee 指标同步 | 该平台不可用 |
| `AMAZON_*` | Amazon 指标同步 | 该平台不可用 |
| `OIDC_*` | 企业 OIDC 登录 | 开发环境用简化登录 |

完整配置项见 `.env.example`。

## 开发

### 前端

```bash
cd frontend
npm ci
npm run dev
```

### 后端

```bash
docker compose up -d postgres redis minio
cd backend
uv sync --extra providers --extra observability --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 测试

```bash
cd backend
uv run pytest -v

cd ../frontend
npx tsc --noEmit
npm run lint
```

## 其他文档

- [项目介绍](./项目介绍.md)：产品定位和功能详解
- [前端说明](./前端.md)：页面设计、交互规范
- [后端说明](./后端.md)：AI 能力、数据模型、安全
- [性能测试](./PERFORMANCE.md)：压测方法和监控口径

## 当前边界

- 生图和视频依赖第三方 API，可用性看外部服务状态
- 预测效果取决于积累了多少线上数据，冷启动用降级策略
- 公平性分析是运营工具，不能替代合规和法律审查
