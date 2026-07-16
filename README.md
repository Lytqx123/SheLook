# SheLook

一个面向电商运营的视觉决策工具。帮助运营团队在商品上架前了解不同视觉方案的潜在效果，在上架后对比实际表现，并通过数据回流持续优化决策。

## 解决的问题

同一件商品，不同的主图可能带来 30% 以上的点击和转化差异。但目前大多数团队选图还是靠经验和直觉。SheLook 尝试让这个过程变得更可量化：在上架前预测效果、在审核时有据可依、在实验中有数据对比、在决策后能积累经验。

## 核心能力

| 模块 | 做什么 |
| --- | --- |
| 发品工作台 | 商品建档、以图搜图、方案推荐、AI 图片生成、生成后质检 |
| 预测决策 | 单图预测和批量方案对比，输出预估 CTR、爆款概率和退货风险 |
| 审核工作台 | 三级自动审核（合规 → 质量 → 审美）+ 人工决策 |
| A/B 实验 | 对比不同方案的线上表现，自动流量分配和显著性检验 |
| 数据飞轮 | 经营指标回流、样本标注、模型重训与版本管理 |
| 数据看板 | 核心指标、CTR 趋势、市场对比、风格洞察 |
| 聚类分析 | 视觉特征聚类，发现视觉模式与经营效果的关联 |
| 供应商分析 | 供应商素材多维度评分和与品类基准的对比 |
| 公平性分析 | 肤色分布统计、市场基线和方案偏差检查 |
| 指标管理 | 批量指标写入、Shopee/Amazon 平台同步 |
| 平台导出 | 适配 Amazon、天猫、TikTok Shop 等平台的图片规格 |
| 审计日志 | 操作记录、详情和请求链路追溯 |

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | Next.js 16、React 19、TypeScript、Ant Design 6、Tailwind CSS 4、TanStack Query、Recharts |
| 后端 | Python 3.13、FastAPI、SQLAlchemy 2 Async、Pydantic 2 |
| AI / 数据 | PyTorch、CLIP、Transformers、scikit-learn、HDBSCAN、pgvector |
| 异步任务 | Celery 5、Redis、Flower |
| 存储 | PostgreSQL 17 + pgvector 向量扩展、MinIO |
| 监控 | Prometheus、Grafana、structlog |
| 部署 | Docker Compose、Nginx |

## 快速开始

### 前置条件

- Docker Desktop 或 Docker Engine + Docker Compose
- 建议为 Docker 分配至少 10 GB 内存
- 真实图片生成和平台同步需要配置对应的第三方 API 凭据

### Windows

```powershell
.\setup.ps1 -Env dev
```

### Linux / macOS

```bash
chmod +x setup.sh
./setup.sh --env dev
```

部署脚本会自动完成环境检查、镜像构建、数据库迁移、演示数据填充和服务启动。

### 手动启动

```bash
docker compose up -d
```

### 访问地址

| 服务 | 地址 |
| --- | --- |
| 统一入口 | <http://localhost> |
| 前端直连 | <http://localhost:3000> |
| 后端直连 | <http://localhost:8000> |
| MinIO 控制台 | <http://localhost:9001> |
| Flower | <http://localhost/flower/> |
| Prometheus | <http://localhost:9090> |
| Grafana | <http://localhost/grafana/> |

## 多环境部署

```bash
# 开发环境
docker compose up -d

# Staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d

# Production
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

生产环境启动前需要补齐 `.env.prod` 中的安全配置，并通过启动校验。

## 第三方服务配置

主要外部能力依赖，未配置时对应功能降级：

| 配置 | 用途 | 未配置时 |
| --- | --- | --- |
| `GEMINI_API_KEY` | 图片生成与部分审核能力 | 尝试其他通道或使用本地能力 |
| `REPLICATE_API_TOKEN` | FLUX 图片生成 | 尝试其他通道 |
| `KLING_API_KEY` | Kling 视频生成 | Kling 不可用 |
| `RUNWAY_API_KEY` | Runway 视频生成 | Runway 不可用 |
| `SHOPEE_*` | Shopee 指标同步 | 该平台同步不可用 |
| `AMAZON_*` | Amazon 指标同步 | 该平台同步不可用 |
| `OIDC_*` | 企业 OIDC 登录 | 开发环境使用简化登录 |

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

## 详细文档

- [项目介绍](./项目介绍.md)：产品定位、设计理念、功能模块详解
- [前端说明](./前端.md)：页面设计、交互规范、视觉体系
- [后端说明](./后端.md)：AI 能力架构、数据模型、安全设计
- [性能测试](./PERFORMANCE.md)：压测方法和监控口径

## 当前边界

- 图片生成和视频生成依赖第三方 API，可用性取决于外部服务状态。
- 效果预测的质量与积累的线上数据正相关，冷启动阶段使用降级策略。
- 公平性分析是运营工具，不替代合规和法律审查。
