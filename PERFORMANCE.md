# SheLook 性能测试

这边只记录压测方法、采集口径和结果记录要求。QPS 和延迟数据需要在目标环境跑完再填。

> TODO: 等 staging 环境跑完一轮正式压测，把基线数据贴过来

## 当前状态

- 仓库里有 Locust 场景：`scripts/locustfile.py`
- 默认只跑只读请求，不会创建或修改数据
- 预测和生图默认关闭，需要显式开 `SHELOOK_ENABLE_MUTATIONS`
- 目前没有可以作为发布承诺的正式基准结果——容量得在目标硬件和配置下自己测

## 准备环境

先确保所有服务健康：

```bash
docker compose up -d
docker compose ps
```

装性能测试依赖：

```bash
cd backend
uv sync --extra perf
cd ..
```

开发环境 Locust 可以自动调 `/api/auth/token` 拿 token。生产/OIDC 必须通过 `SHELOOK_TOKEN` 传入 token。

PowerShell：

```powershell
$env:SHELOOK_TOKEN = '<JWT>'
backend\.venv\Scripts\locust.exe -f scripts\locustfile.py --host http://127.0.0.1:8000
```

Bash：

```bash
export SHELOOK_TOKEN='<JWT>'
backend/.venv/bin/locust -f scripts/locustfile.py --host http://127.0.0.1:8000
```

打开 Locust 页面后按计划设并发、增长速率和持续时间。

## 场景

### 默认只读

`ReadOnlyUser` 覆盖：

- `/api/health`
- `/api/dashboard/summary`
- `/api/dashboard/ctr_trend`
- `/api/products`
- `/api/experiments`
- `/api/review/queue`
- `/api/audit/logs`
- `/api/prediction/model-versions`

`/api/health/ready` 会同步检查数据库、Redis 和 MinIO，别当普通接口压测——压测前后各调一次就行。

### 可选写入

只在隔离测试环境启用：

```powershell
$env:SHELOOK_ENABLE_MUTATIONS = 'true'
$env:SHELOOK_IMAGE_ID = '123'
$env:SHELOOK_SCHEME_ID = '456'
```

- 设了 `SHELOOK_IMAGE_ID` → 启用预测
- 设了 `SHELOOK_SCHEME_ID` → 启用生图提交
- 429/503/504 统一记失败，不会伪装成成功

## 建议测试顺序

1. **冒烟**：1~2 用户跑 2 分钟，确认没认证/路由/数据错误
2. **基线**：固定并发跑至少 10 分钟，记稳定区间
3. **阶梯**：逐级加并发，每级 5~10 分钟，找延迟和错误率开始恶化的点
4. **稳定性**：目标并发达 1~4 小时，观察内存、连接池、Celery 队列和外部错误
5. **恢复**：停流量后确认队列归零、连接数恢复、服务健康

不要在真实生产数据环境开写入场景，也不要在没确认供应商计费规则的时候压生图或视频接口。

## 监控口径

Locust 记录：
- 请求数、RPS、失败率
- P50/P90/P95/P99 和最大延迟
- 按接口分的状态码和错误原因

Prometheus/Grafana 同期看：
- `shelook_requests_total`
- `shelook_request_latency_seconds`
- `shelook_active_requests`
- `shelook_celery_queue_length`
- `shelook_generation_task_duration_seconds`
- 容器 CPU、内存、重启次数、数据库连接池状态

外部模型/供应商接口单独记录调用次数、限流、超时、失败率和费用。mock 模式的数据不能当真实容量。

## 结果记录模板

每次正式测完至少记这些：

| 项目 | 内容 |
|---|---|
| 日期与版本 | Git commit、镜像版本、配置版本 |
| 环境 | CPU、内存、磁盘、OS、Docker 版本 |
| 服务配置 | Uvicorn/Celery 并发、连接池、限流、模型 |
| 数据规模 | 商品、图片、实验、指标记录数量 |
| Locust 参数 | 用户数、增长速率、持续时间、启用场景 |
| 结果 | RPS、P50/P95/P99、错误率、资源峰值 |
| 异常 | 失败码、日志关键信息、队列积压和恢复时间 |

验收阈值以实际业务 SLO、硬件预算和供应商额度为准。别在没有环境说明的情况下把单次结果写成"项目通用能力"。
