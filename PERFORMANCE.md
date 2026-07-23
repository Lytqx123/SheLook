# SheLook 性能与发布验证

> 文档基线：2026-07-23。性能结论只在明确的环境、数据规模和压测场景内成立；不替代生产容量承诺。

## 说明

本文件记录当前仓库提供的性能验证工具、指标口径和发布验证方法。仓库没有发布可泛化的吞吐量、延迟或“可支持多少用户”的实测结论；任何容量判断都必须在目标硬件、目标配置、目标数据规模和真实外部依赖条件下重新测试。

默认压测场景以只读 API 为主，不会创建商品、预测记录或生成任务。预测和生成写入场景必须显式开启，且只应在隔离测试环境中运行。

## 2026-07-23 运行冒烟记录

本机 development Compose 环境已完成部署级冒烟：数据库迁移处于 `018`，13 个 Compose 服务均健康，API 的存活与就绪检查通过，且就绪检查中的 PostgreSQL、Redis、MinIO 均返回 `ok`；Nginx 反向代理下的同一就绪端点也通过。前端生产构建、后端 Ruff/编译检查、79 项后端回归测试、完整性/RLS 门禁和连续 outbox 分发均已通过。这个记录只证明当前代码与本机依赖能够启动、连通和执行基础任务，不能替代本文件所要求的目标环境压测、数据一致性报告和发布门禁。

## 当前验证工具

| 工具 | 位置 | 用途 |
| --- | --- | --- |
| Locust | scripts/locustfile.py | 带认证的读多写少场景；默认覆盖健康检查、看板、商品、实验、审核、审计和模型版本查询。 |
| 轻量并发脚本 | backend/scripts/phase6/run_read_load.py | 无额外压测依赖的只读并发冒烟，可产出 JSON 报告。 |
| 数据一致性脚本 | backend/scripts/phase6/verify_data_integrity.py | 检查租户外键、跨租户关系、配额和 RLS。 |
| 发布门禁聚合 | backend/scripts/phase6/release_gate.py | 汇总 Locust 或轻量压测报告与一致性报告，生成可审计的门禁结论。 |
| 运行监控 | Prometheus、Grafana、Flower | 查看 API 指标、任务队列、容器状态和任务执行状态。 |

## 运行前准备

先通过根目录启动脚本准备环境，并确认基础健康检查通过：

~~~powershell
.\setup.ps1 -Env dev
docker compose ps
Invoke-WebRequest http://localhost:8000/api/health
~~~

Locust 依赖在后端 perf 可选依赖中：

~~~powershell
Set-Location backend
uv sync --extra perf
~~~

开发环境且认证未启用时，Locust 会请求 /api/auth/token 取得开发令牌。企业认证环境必须自行提供有效 JWT：

~~~powershell
Set-Item Env:SHELOOK_TOKEN "<JWT>"
Set-Item Env:SHELOOK_TENANT_ID "<tenant-id>"
~~~

## Locust 场景

从 backend 目录启动：

~~~powershell
uv run locust -f ..\scripts\locustfile.py --host http://127.0.0.1:8000
~~~

默认只读用户会请求：

- /api/health
- /api/dashboard/summary
- /api/dashboard/ctr_trend
- /api/products
- /api/experiments
- /api/review/queue
- /api/audit/logs
- /api/prediction/model-versions

健康检查中的 /api/health/ready 会同步检查数据库、Redis 和 MinIO，不应作为普通高频压测接口。

### 可选写入场景

只有在隔离环境中，且已确认外部模型计费、数据清理和任务队列影响后，才可启用预测或生成：

~~~powershell
Set-Item Env:SHELOOK_ENABLE_MUTATIONS true
Set-Item Env:SHELOOK_IMAGE_ID 123
Set-Item Env:SHELOOK_SCHEME_ID 456
uv run locust -f ..\scripts\locustfile.py --host http://127.0.0.1:8000
~~~

设置 SHELOOK_IMAGE_ID 后会启用预测写入；设置 SHELOOK_SCHEME_ID 后会提交生成任务。429、503 和 504 会被记录为失败，不能被解释为系统成功。

## 轻量只读并发检查

轻量脚本适合本地或 CI 冒烟。它默认访问存活探针、看板摘要和商品列表，并输出请求数、错误率、平均延迟、P95、P99 和 RPS：

~~~powershell
Set-Location backend
uv run python -m scripts.phase6.run_read_load --base-url http://127.0.0.1:8000 --concurrency 10 --duration-seconds 30 --output ..\artifacts\read-load.json
~~~

如需在认证环境运行，可追加 --tenant-id 和 --token 参数。压测报告应与测试时的镜像版本、环境变量、数据规模和外部服务状态一起保存。

## 指标口径

Prometheus 当前采集后端 /metrics。重点指标包括：

| 指标 | 含义 |
| --- | --- |
| shelook_requests_total | 按方法、路由和状态码统计的请求总数。 |
| shelook_request_latency_seconds | 按方法和路由统计的请求延迟直方图。 |
| shelook_active_requests | 当前活跃请求数。 |
| shelook_celery_queue_length | 按队列统计的待处理任务数。 |
| shelook_generation_task_duration_seconds | 按生成提供方和状态统计的生成任务耗时。 |
| shelook_quality_pass_rate | 按审核层级和结论统计的质量通过率。 |
| shelook_model_prediction_drift | 预测 CTR 与实际 CTR 的漂移度量。 |

除 API 指标外，发布评估还应观察容器 CPU/内存、数据库连接池、Redis、对象存储、任务积压、外部服务限流、超时和费用。演示数据与开发模式的占位生成不能作为生产容量证据。

## 发布门禁

发布门禁脚本可以读取 Locust 聚合 CSV 或轻量压测 JSON，并与数据一致性报告合并：

~~~powershell
Set-Location backend
uv run python -m scripts.phase6.verify_data_integrity --output ..\artifacts\integrity.json
uv run python -m scripts.phase6.release_gate --load-report ..\artifacts\read-load.json --integrity-report ..\artifacts\integrity.json --output ..\artifacts\release-gate.json
~~~

脚本默认要求至少 1,000 个请求、错误率不高于 0.5%、P95 不高于 500ms，并且一致性报告通过。这些只是脚本的默认参数，不是已经对外承诺或已经验证的系统 SLO；上线团队应根据业务优先级、环境预算、数据规模和外部依赖调整阈值。

## 当前已知验证限制

`backend/scripts/phase6/verify_data_integrity.py` 以迁移头 `018` 为基线，覆盖既有活动表以及经营事实、真实效果事实、预测快照和反馈标签的租户外键、关联一致性和 RLS 检查。它是发布门禁的一个输入，而不是容量结论：仍需结合目标环境的权限、备份恢复、外部服务限流、告警和原始压测报告判断是否可上线。

生产与预发 Compose 覆盖会关闭 `ALLOW_GENERATION_MOCKS`、移除源码挂载和直接诊断端口，并要求 digest 固定的镜像、C2PA/指标 secret 文件与受控环境配置。压测不得使用演示数据或占位生成来宣称生产容量；写入、生成和第三方通道的场景必须在隔离环境按实际凭据、预算和限额单独验证。

## 结果记录模板

每次正式测试至少保留以下信息：

| 项目 | 必填内容 |
| --- | --- |
| 版本 | Git 提交、镜像标签、数据库迁移版本。 |
| 环境 | CPU、内存、磁盘、网络、Docker/操作系统版本。 |
| 配置 | API Worker、Celery 并发、数据库连接池、限流、认证和外部服务配置。 |
| 数据 | 租户数、商品数、素材数、实验数、指标记录量和对象存储规模。 |
| 场景 | 并发、爬升速率、持续时长、接口比例、是否包含写入任务。 |
| 结果 | RPS、P50/P95/P99、错误率、资源峰值、任务积压与恢复时间。 |
| 异常 | 状态码、错误摘要、外部依赖状态、降级/恢复动作和结论。 |

在没有完整环境说明和原始报告的情况下，不应把单次结果描述为项目的通用性能能力。
