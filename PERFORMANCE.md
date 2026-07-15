# SheLook 性能测试说明

本文只描述当前项目的压测方法、采集口径和结果记录要求，不提供未经执行验证的 QPS 或延迟结论。

## 当前状态

- 仓库提供 Locust 场景：`scripts/locustfile.py`。
- 默认场景只执行已认证的只读请求，不创建或修改业务数据。
- 预测和生图场景默认关闭，只有显式允许写入并提供有效资源 ID 后才启用。
- 当前仓库没有可作为发布承诺的正式基准结果；实际容量需要在目标硬件、目标模型和目标外部供应商配置下重新测试。

## 准备环境

启动完整服务并确认依赖健康：

```bash
docker compose up -d
docker compose ps
```

安装后端性能测试依赖：

```bash
cd backend
uv sync --extra perf
cd ..
```

开发环境可以让 Locust 自动调用 `/api/auth/token` 获取本地 token。生产或 OIDC 环境必须通过 `SHELOOK_TOKEN` 提供有效 token。

PowerShell 示例：

```powershell
$env:SHELOOK_TOKEN = '<有效 JWT>'
backend\.venv\Scripts\locust.exe -f scripts\locustfile.py --host http://127.0.0.1:8000
```

Bash 示例：

```bash
export SHELOOK_TOKEN='<有效 JWT>'
backend/.venv/bin/locust -f scripts/locustfile.py --host http://127.0.0.1:8000
```

打开 Locust 页面后，按测试计划设置并发用户数、增长速率和持续时间。

## 场景说明

### 默认只读场景

`ReadOnlyUser` 覆盖：

- `/api/health`
- `/api/dashboard/summary`
- `/api/dashboard/ctr_trend`
- `/api/products`
- `/api/experiments`
- `/api/review/queue`
- `/api/audit/logs`
- `/api/prediction/model-versions`

`/api/health/ready` 会同步检查数据库、Redis 和 MinIO，因此不放入高频请求权重；应在压测前后各调用一次，而不是把它当作普通业务接口压测。

### 可选写入场景

只有在隔离的测试数据环境中才启用：

```powershell
$env:SHELOOK_ENABLE_MUTATIONS = 'true'
$env:SHELOOK_IMAGE_ID = '123'
$env:SHELOOK_SCHEME_ID = '456'
```

- 设置 `SHELOOK_IMAGE_ID` 后启用预测场景。
- 设置 `SHELOOK_SCHEME_ID` 后启用生图提交场景。
- `429`、`503`、`504` 等容量或依赖错误统一计为失败，不会被伪装成成功请求。

## 建议测试阶段

1. 冒烟：1～2 个用户运行 2 分钟，确认无认证、路由或数据错误。
2. 基线：固定并发运行至少 10 分钟，记录稳定区间。
3. 阶梯：逐级增加并发，每级保持 5～10 分钟，找到延迟和错误率开始明显恶化的位置。
4. 稳定性：使用目标并发持续运行 1～4 小时，观察内存、连接池、Celery 队列和外部供应商错误。
5. 恢复：停止流量后确认队列归零、连接数恢复且服务继续健康。

不要在包含真实生产数据的环境启用写入场景，也不要在未确认供应商计费规则时压测图片或视频生成接口。

## 监控口径

Locust 至少记录：

- 请求数、RPS、失败率；
- P50、P90、P95、P99 和最大响应时间；
- 按接口区分的状态码与错误原因。

Prometheus/Grafana 同期记录：

- `shelook_requests_total`；
- `shelook_request_latency_seconds`；
- `shelook_active_requests`；
- `shelook_celery_queue_length`；
- `shelook_generation_task_duration_seconds`；
- 容器 CPU、内存、重启次数和数据库连接池状态。

外部模型或供应商接口还要单独记录调用次数、限流、超时、失败率和费用。不能把 mock 模式的成绩当作真实供应商容量。

## 结果记录模板

每次正式测试至少保存以下信息：

| 项目 | 内容 |
|---|---|
| 日期与版本 | Git commit、镜像版本、配置版本 |
| 环境 | CPU、内存、磁盘、操作系统、Docker 版本 |
| 服务配置 | Uvicorn/Celery 并发、连接池、限流、模型与供应商 |
| 数据规模 | 商品、图片、实验、指标记录数量 |
| Locust 参数 | 用户数、增长速率、持续时间、启用场景 |
| 结果 | RPS、P50/P95/P99、错误率、资源峰值 |
| 异常 | 失败状态码、日志摘要、队列积压和恢复时间 |

验收阈值应由实际业务 SLO、硬件预算和供应商额度确定，并在测试前写入测试记录；不要在没有环境和样本说明的情况下把单次结果写成项目通用能力。
