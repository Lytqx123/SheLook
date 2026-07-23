# 第七章：异步任务体系 —— Celery 四队列与 Outbox 可靠性模式

> 维护说明（2026-07-23）：第三方同步同样运行在受租户上下文约束的 Worker 中；缺少供应商契约时必须显式失败或等待，不能返回伪成功。

> 更新说明（2026-07-22）：Celery 任务现在统一在 fork 后重置异步连接池，并在每次同步任务的异步循环关闭前释放连接，修复了 asyncpg 跨事件循环复用问题。实际容器中连续 Outbox 分发和 Beat 周期已通过；该结果不等同于所有外部提供方已可用。

---

## 一、为什么需要异步任务？—— 从"等得起"到"等不起"

### 1.1 同步方式的结构性缺陷

在前端点击"生成商品图"之后，如果用最直接的方式（同步 HTTP 请求）处理：

```
用户点击"生成"
  │
  ├── 构建提示词            10ms
  ├── 调用 FLUX API         30-60 秒  ← 这段时间浏览器一直转圈
  ├── 下载生成的图片         5-10 秒   ← 还在转圈
  ├── 图片质检（CLIP + 像素） 300ms
  ├── 生成 C2PA 签名         200ms
  ├── 存入 MinIO             500ms
  └── 返回结果给前端          ← 总共 40-70 秒后，用户终于看到结果

同步方式的致命问题：
  1. HTTP 连接保持 60 秒 → 浏览器/Nginx/负载均衡器的超时阈值通常是 30-60 秒，
     在用户真正看到结果之前连接就可能被断开，前端收到的是"网络错误"而非生图结果
  2. 用户只能干等着，不能做其他操作 → 对于一个需要批量生成几十张图的运营来说，
     这意味着连续等几个小时
  3. 服务端占着一个线程/协程 60 秒 → FastAPI 的工作线程是有限的，
     如果 10 个用户同时点击生成，10 个线程全部被占用 60 秒，
     其他 API 请求（如查询商品列表）需要排队等待——整个系统被生图请求卡死
  4. 如果中间任何一步失败 → 整个请求 HTTP 500 → 
     用户只看到一个错误页面，不知道"生图到底成功了没有"
```

问题的根源在于：**HTTP 请求-响应模型是为"几百毫秒"的操作设计的，而生图和生视频属于"几十秒到几分钟"的操作。** 把后者的生命周期强行塞入前者的框架中，就像一个只能载重 1 吨的卡车试图运输 50 吨的货物——不是货物有问题，是运输方式选错了。

### 1.2 异步方式的解决思路：把"等待"从 HTTP 请求中剥离

**异步任务**的核心思想是：把耗时的操作从 HTTP 请求的生命周期中"拆出来"，放到一个独立的、长期运行的 Worker 进程中执行。HTTP 请求只负责"接收指令"和"快速返回确认"，不负责"执行指令"。

```
异步方式：

用户点击"生成"
  │
  ├── API 写入数据库（GeneratedImage，status=pending）    10ms
  ├── 在同一事务中写入 OutboxEvent（status=pending）       1ms
  ├── 数据库事务提交                                      5ms
  └── 返回 { "status": "queued" }                         ← 50ms 内返回给前端

前端收到 50ms 的即时响应后：
  ✗ 不需要等 60 秒
  ✗ 不会超时
  ✗ 用户可以立即做其他操作（继续浏览、创建另一个方案）
  ✗ 前端通过 WebSocket 或轮询，在后台任务完成时收到通知

后台（Celery Worker，和 API 进程完全独立）：
  ├── 从 Redis 拉取到任务
  ├── 调用 FLUX API（30-60 秒）
  ├── 下载图片（5-10 秒）
  ├── 质检 + C2PA 签名 + 存储
  └── 完成后 → 更新数据库 + Redis Pub/Sub 推送通知

API 进程和 Worker 进程完全解耦：
  API 可以重启而不影响正在运行的任务（任务在 Redis 中持久化）
  Worker 可以独立扩缩容（高峰期多启动几个 Worker 实例）
  即使 API 挂掉，Worker 继续处理队列中的任务不受影响
```

这背后是一个更通用的分布式系统设计原则：**同步请求-响应适合短操作（决策型 API），异步消息队列适合长操作（执行型任务）。** 决策型 API 告诉系统"要做一件什么事"并立刻得到"已收到，正在处理"的确认，而执行型任务在后台默默完成具体的操作。这种分离让两种不同性质的操作各自使用最适合的通信模式和资源分配策略。

---

## 二、Celery 是什么？—— 分布式任务队列的三角色模型

Celery 是 Python 生态中最成熟的分布式任务队列框架，它的核心设计基于经典的**生产者-消费者模型**：

```
Producer（生产者）     → 把任务"投进"消息队列
  │                     SheLook 的 FastAPI 后端
  │                     告诉系统"帮我做这件事"
  ▼
Broker（消息中间件）    → 暂存待处理的任务
  │                     SheLook 使用 Redis
  │                     相当于任务的"待办清单"
  ▼
Consumer（消费者）      → 从队列取出任务并执行
                        SheLook 的 Celery Worker 进程
                        按照"先到先服务"的规则逐个消化任务
```

三角色的分工让系统的每一部分都专注于自己的职责。生产者（API）只管"下达指令"——它不需要知道有没有 Worker 在线、Worker 在哪个服务器上运行、何时开始处理。消费者（Worker）只管"执行指令"——它不需要知道任务是谁发出的、在什么 HTTP 请求的上下文中。两者通过 Broker（消息队列）做异步通信——这是计算机科学中最古老也最可靠的解耦模式之一。

SheLook 选择 Redis 作为 Broker 而不是 RabbitMQ，主要是为了简化部署拓扑。RabbitMQ 在功能和可靠性上更强大（支持更复杂的路由、死信队列、消息持久化的强保证），但它需要独立部署和运维一个 RabbitMQ 服务。SheLook 已经在用 Redis 做缓存、限流、Pub/Sub——选择 Redis 同时也做 Celery Broker，将"一个基础设施组件解决多个问题"贯彻到底。代价是 Redis 作为 Broker 的消息持久化保证不如 RabbitMQ 强（Redis 的 AOF/RDB 持久化有数据丢失窗口），但在 SheLook 的场景下，这个代价是完全可以接受的——因为有 Outbox 模式兜底（后面详述）。

---

## 三、四队列设计：不同任务走不同的优先级通道

### 3.1 单队列的问题：快任务被慢任务堵死

如果所有任务都在一个队列里等待，就会出现经典的"头等舱旅客被经济舱登机堵在廊桥"的情况：

```
单队列（灾难）：
[生图60秒] [生图60秒] [生图60秒] [生视频300秒] [质检300ms] [数据回流2秒]
                                        ↑
                              这个质检任务只需要 300ms，
                              但要等前面 4 个任务共计 8 分钟才能被执行
                              而数据回流（2 秒的轻量任务）更是遥遥无期
```

SheLook 的解决方案是把任务按照耗时和资源特性分成四个独立的队列，每个队列有各自专属的 Worker 进程消费：

```python
# celery_app.py 中的队列定义

Queue("orchestration", routing_key="orchestration")   # 编排队列
Queue("generation",   routing_key="generation")       # 生图队列
Queue("model",        routing_key="model")            # 模型队列
Queue("analytics",    routing_key="analytics")        # 分析队列
```

### 3.2 四种队列的分工与资源配置

```
orchestration（编排队列）
  ├── 任务：dispatch_outbox_events（每 10 秒）
  ├── 特点：极其轻量（查询 Outbox 表 + 投递 Celery 任务，通常 < 100ms）
  ├── 并发：1 个 Worker 足够（多了反而可能造成 Outbox 事件重复投递）
  └── 为什么需要独立队列：这是整个异步系统的"发动机"——如果它被其他任务
      堵住，所有新创建的 Outbox 事件都无法被投递，整个系统卡死

generation（生图队列）
  ├── 任务：generate_single_image, generate_video
  ├── 特点：重量级（30-300 秒/任务），调用外部 AI API，网络等待为主
  ├── 并发：受外部 API 配额和月度预算限制，不是"越多越好"
  └── 瓶颈：在外部 API 端（Replicate 的速率限制、Gemini 的并发限制），
      不在 SheLook 服务器端。Worker 大部分时间在等 HTTP 响应，CPU 空闲

model（模型队列）
  ├── 任务：evaluate_image_quality, index_product_embedding,
  │         compute_clip_zero_shot
  ├── 特点：中等重量（200ms-5 秒），本地 CPU 密集型（CLIP 推理）
  ├── 并发：取决于 CPU 核心数——N 个核心最多同时跑 N 个 CLIP 推理，
  │         超过 N 的只能排队等 CPU
  └── 瓶颈：CPU 使用率。生图队列在等待网络，model 队列在烧 CPU——
           两类任务不争抢资源，这正是分队列设计的价值

analytics（分析队列）
  ├── 任务：sync_daily_metrics, retrain_models,
  │         auto_create_experiments, update_traffic_allocation
  ├── 特点：定时任务（凌晨 2:00-6:00），数据量大但计算不密集
  ├── 并发：1-2 个 Worker
  └── 瓶颈：数据库查询效率（大量数据聚合操作）
```

### 3.3 路由规则

```python
task_routes={
    "dispatch_outbox_events":        → Queue("orchestration"),
    "generate_single_image":         → Queue("generation"),
    "evaluate_image_quality":        → Queue("model"),
    "index_product_embedding":       → Queue("model"),
    "sync_daily_metrics":            → Queue("analytics"),
    "retrain_models":                → Queue("analytics"),
    "auto_create_experiments_task":  → Queue("analytics"),
    "update_traffic_allocation_task":→ Queue("analytics"),
}
```

**设计原则**：耗时和资源类型相近的任务放在同一队列。让 300ms 的 CLIP 质检和 5 秒的 CLIP 向量索引在同一条路上是合理的（它们的瓶颈都是本地 CPU，不会互相阻塞太久）。但让 60 秒的网络等待型生图和 300ms 的 CPU 密集型质检放在一起就是对两者的浪费。

### 3.4 关键配置项详解

```python
task_time_limit = 600          # 硬超时：10 分钟后直接 SIGKILL
task_soft_time_limit = 540     # 软超时：9 分钟后抛出异常（给 1 分钟缓冲做清理）
worker_prefetch_multiplier = 1 # 每次只取 1 个任务
task_acks_late = True          # 执行完再确认（而非取到就确认）
task_reject_on_worker_lost = True # Worker 宕机后任务重回队列
```

**prefetch_multiplier = 1（四个配置中最关键的一个）**

Celery 的默认行为是每个 Worker 预取 4 个任务到本地内存中。这在任务耗时均匀的场景下是合理的优化（减少 Worker 和 Broker 之间的网络往返）。但在任务耗时极度不均匀的场景下（SheLook 的 generation 队列：有些任务 30 秒、有些 120 秒），这会导致灾难性的"任务囤积"：

```
prefetch=4 的灾难：
  Worker A：预取了 4 个生图任务（4 × 平均 60 秒 = 240 秒的工作量）
  Worker B：刚刚完成了自己的任务，空闲了——但它拿不到排队中的任务，
            因为那些任务已经被 Worker A 预取走了（锁定在 A 的内存中）
  
  结果：3 个 Worker 空闲着，1 个 Worker 的任务排到 4 分钟后。
        总吞吐量被限制在 1 个 Worker 的水平上，其他 Worker 白白浪费。
```

`prefetch_multiplier=1` 意味着"每次只拿 1 个任务，干完再拿下一个"。这确保了任务始终被分配给下一个空闲的 Worker，而不是被预取到某个忙碌 Worker 的内存中排队。代价是增加了 Worker 和 Redis Broker 之间的网络通信次数，但这个代价在任务本身耗时 30-120 秒的场景下完全可以忽略。

**task_acks_late = True**

Celery 默认在 Worker 从 Broker 拿到任务的那一刻就发送确认（ACK）。此时任务内容被放在 Worker 的内存中。如果 Worker 在接下来的处理过程中崩溃，ACK 已经发送了——Broker 以为任务已被成功接收并处理中，但实际上是丢在了一个死掉的 Worker 的内存里。`task_acks_late=True` 改为"任务执行完成后才发送 ACK"——如果 Worker 在处理过程中崩溃，Broker 在超时后会将该任务重新投递给另一个健康的 Worker。

**task_reject_on_worker_lost = True**

和 `task_acks_late` 配合使用。如果 Worker 进程被操作系统杀死（OOM killer、Docker 重启、宿主机断电），这个配置让 Broker 将该 Worker 上所有未完成的任务自动重新分配给其他 Worker。

**task_time_limit = 600 和 task_soft_time_limit = 540**

双层超时设计：软超时在 540 秒时抛出一个可以被捕获的异常（`SoftTimeLimitExceeded`）——Worker 有 60 秒的时间来做清理工作（记录错误日志、持久化失败状态、释放资源）。硬超时在 600 秒时直接发送 `SIGKILL`（不可捕获、不可忽略）——如果 60 秒还不够做清理，证明清理逻辑本身也卡死了，必须暴力杀死。

---

## 四、Outbox 模式：解决分布式系统的头号难题

### 4.1 双写问题的本质

这是每一个使用消息队列的系统都会遇到的问题。它被称为"双写问题"不是因为需要写两次，而是因为两个独立的存储系统无法在同一个事务中原子地写入：

```
API 处理函数中的"天真"写法：

  # 第一步：写数据库
  async with db.begin():
      image = GeneratedImage(status="pending")
      db.add(image)
      await db.flush()
      # 数据库事务在这里 COMMIT ✓
      image_id = image.id

  # 第二步：投递 Celery 任务（事务外部）
  generate_single_image.delay(image_id=image_id)

---- 危险窗口开始 ----
如果在这一刻（数据库已 COMMIT，但 Celery 投递还未执行）：Redis 连接断开、
网络抖动、或 delay() 抛出了异常...
---- 危险窗口结束 ----

  结果：数据库中有一条 status="pending" 的记录，image_id 是合法的，
        但 Celery 任务从未被投递。这条记录永远停在 pending 状态，
        没有任何 Worker 会来处理它——"幽灵任务"

反过来也不行：
  generate_single_image.delay(image_id=image_id)  ← 先投递任务
  # 如果 Worker 此时已经开始执行（在事务提交前就拉取到了任务）
  # Worker 查询数据库 → image_id 不存在 → 报错 → 重试 3 次 → 失败
  
  async with db.begin():
      db.add(image)  ← 再写数据库（可能失败）
```

问题的本质不是"两个操作有先后顺序"——而是**没有一种让两个操作原子地同时成功或同时失败的机制。** 数据库事务只保证数据库内多个操作的一致性，它无法跨越到 Redis（Celery Broker）这个独立的存储系统。

### 4.2 Outbox 模式的解决方案：信任数据库，不信任消息队列

Outbox 模式的思想直击本质：放弃直接写消息队列。改为在同一个数据库事务中，同时写入业务数据和一条"待处理事件"记录——然后让一个独立的定时任务从数据库读取这些事件记录，逐条投递到 Celery：

```
步骤 1：在同一个数据库事务中写入两样东西：
  - 业务数据（GeneratedImage，status = "pending"）
  - Outbox 事件（OutboxEvent，status = "pending", event_type = "generation.requested"）

步骤 2：数据库事务提交（ACID 保证：两样要么都成功，要么都失败）
        如果事务提交成功 → 业务数据和事件记录同时持久化
        如果事务提交失败 → 两者都回滚（image 不存在，也没有事件记录）

步骤 3：一个独立的定时任务（dispatch_outbox_events，每 10 秒一次）
  扫描 OutboxEvent 表中 status="pending" 的记录
  逐条调用 generate_single_image.delay(...) 投递到 Celery
  投递成功 → 更新 event.status = "published"
  投递失败 → 更新 event.available_at（指数退避）
```

这个方案的关键洞察是：**不再依赖"数据库 + Redis"的跨系统原子性（不存在这种机制），改为依赖"纯数据库"的 ACID 原子性。** 只要数据库事务提交了，Outbox 事件就在那里——即使发布器宕机、Redis 故障、网络分区——恢复后发布器会从数据库中重新读取未处理的事件，继续投递。这是一种系统设计中的常见智慧：当两个系统无法原子化时，让其中一个系统（数据库）扮演"唯一真相来源"（Single Source of Truth）的角色，其他系统（Redis/Celery）从中同步状态。

### 4.3 OutboxEvent 数据模型与幂等键

```python
class OutboxEvent(TenantScopedMixin, Base):
    __tablename__ = "outbox_events"

    id              # 自增主键
    event_key       # 幂等键：{event_type}:{aggregate_id}:{hash(payload)}
    event_type      # 事件类型（"generation.requested"）
    aggregate_type  # 聚合类型（"workflow_task"）
    aggregate_id    # 聚合 ID（即 workflow_task_id）
    payload         # JSON 负载（Celery 任务的 kwargs）
    status          # pending → published → failed
    attempt_count   # 已重试次数（初始 0，最大 9）
    available_at    # 下次可投递时间（失败后指数退避）
    published_at    # 成功投递时间
    last_error      # 上次失败的错误信息（用于调试）
```

`event_key` 是幂等的关键。它的格式是：

```
event_key = f"{event_type}:{aggregate_id}:{hash(payload)}"
# 示例："generation.requested:task-123:a1b2c3d4e5f6..."
```

数据库层面在 `event_key` 上设置了唯一约束（unique constraint）。如果同一个用户对同一个 workflow_task 发起了两次完全相同的生图请求（payload 哈希相同），第二次写入会被唯一约束阻止——不会创建两条 Outbox 事件、不会生成两张重复的图。这是一种数据库层面的幂等保证——不需要在应用层写复杂的"检查是否已存在"逻辑。

### 4.4 分布式安全的发布逻辑

```python
@shared_task(name="dispatch_outbox_events")
def dispatch_outbox_events(limit=50):
    # 核心查询：用 FOR UPDATE SKIP LOCKED 保证分布式安全
    events = SELECT * FROM outbox_events
      WHERE status = 'pending'
        AND available_at <= now()
      ORDER BY created_at
      LIMIT 50
      FOR UPDATE SKIP LOCKED   ← 关键中的关键

    for event in events:
        if event.attempt_count >= 10:
            event.status = FAILED  # 10 次重试后放弃
            continue

        try:
            generate_single_image.apply_async(kwargs=payload)
            event.status = PUBLISHED
            event.published_at = now()
        except Exception as e:
            event.last_error = str(e)
            event.attempt_count += 1
            event.available_at = now() + delay  # 指数退避
            # 继续处理下一条（不因一条失败而中断整个批次）
```

**`FOR UPDATE SKIP LOCKED` 的三重作用：**

1. `FOR UPDATE`：对读取的这些行加排他锁，防止其他事务同时处理同一批事件。只有当前事务提交后，锁才释放。
2. `SKIP LOCKED`：如果某行已经被其他事务锁定（另一个 Publisher Worker 正在处理），直接跳过——不等待、不阻塞。这保证了多个 Publisher Worker 并发运行时不会互相踩脚，每个 Worker 拿到的都是互不重叠的一批事件。
3. `LIMIT 50`：每次最多处理 50 条事件，防止一个批次太大导致数据库事务过长、行锁持有时间过久。

### 4.5 指数退避：给故障留出恢复时间

```python
delay = min(300, 2 ** event.attempt_count)
# 第 1 次失败 → 2^1 = 2 秒后重试
# 第 2 次失败 → 2^2 = 4 秒后重试
# 第 3 次失败 → 2^3 = 8 秒后重试
# 第 4 次失败 → 16 秒
# 第 5 次失败 → 32 秒
# 第 6 次失败 → 64 秒
# 第 7 次失败 → 128 秒
# 第 8 次失败 → 256 秒
# 第 9 次失败 → 300 秒（ceiling 封顶）
# 第 10 次失败 → 标记 FAILED，不再重试
```

不是固定间隔重试，而是逐渐增加间隔——给外部故障（如 Redis 重启、网络恢复）留出逐渐放宽的恢复时间窗口。如果故障是瞬时的（如毫秒级的网络抖动），前几次短间隔的重试就能消化。如果故障是持续的（如 Redis 宕机 5 分钟），指数增长的重试间隔避免了 10 秒一次地反复撞墙——在 Redis 恢复之前，重试只会浪费资源。

---

## 五、生图任务的完整生命周期：一条任务从摇篮到坟墓

### 5.1 状态流转

```
created → queued → running → succeeded
                  ↘ running → retrying → queued → running → succeeded
                  ↘ running → retrying → ... → failed（3 次 Celery 重试后）
                  ↘ running → failed（不可重试的错误，如 422 参数校验失败）
                  或 cancelled（用户在任务 running 前手动取消）
```

### 5.2 生图任务的顶层结构

```python
def generate_single_image(image_id, scheme_id, ..., tenant_id):
    with tenant_context(tenant_id, source="celery"):  # ① 设置租户上下文
        try:
            _run()  # ② 执行异步主逻辑
        except Retry:
            raise  # ③ Celery 重试（直接透传，不吞掉）
        except Exception as e:
            if retries >= max_retries:
                _persist_failure(e)  # ④ 最终失败 → 写数据库 status=failed
                raise  # 不再重试
            _persist_retrying(e)     # ⑤ 中间失败 → 写数据库 status=retrying
            raise self.retry(exc=e)  # ⑥ 触发 Celery 重试（30 秒后）
```

六个步骤的设计含义：

| 步骤 | 含义 | 如果跳过会怎样 |
|------|------|--------------|
| ① 设置租户上下文 | 后台任务知道自己属于哪个租户 | ORM 层读不到 tenant_id → 数据写入错误的租户或查询失败 |
| ② 异步主逻辑 | 执行 12 步生图流水线 | 这个任务没有存在的意义 |
| ③ Retry 透传 | Celery 的 `Retry` 异常不能吞掉 | 被 `except Exception` 捕获 → 当成通用异常"持久化失败" → 错误的状态更新 |
| ④ 最终失败持久化 | 写数据库 status=failed + 失败原因 | 前端看到永远的 "running"，用户不知道任务失败了 |
| ⑤ 中间重试持久化 | 写数据库 status=retrying + 重试计数 | 前端看到永远的 "running"，不知道任务已经失败了一次正在重试 |
| ⑥ 触发 Celery 重试 | 30 秒后重新放入队列 | 一次性失败就放弃 → 本来换个时间或网络环境就能成功 |

注意第 3 步的设计细节：`except Retry: raise` 必须在 `except Exception` 之前。因为 `Retry` 类继承自 `Exception`——如果顺序反过来，`Retry` 会被通用的 `except Exception` 捕获，导致 `celery.exceptions.Retry` 被当成普通异常"持久化失败"，但实际上它应该被 Celery 框架底层捕获来触发实际的重试机制。这个异常顺序的处理在项目中曾引起过 bug（项目 memory 中有记录）。

### 5.3 _run() 内部的 12 个步骤

```
1. 幂等性检查：WorkflowTask 是否已是终态（cancelled / succeeded / running）
   → 是 → return（防止重复执行）
   
2. 读取 GeneratedImage → 状态改为 queued / processing
   → 让前端立即看到状态变化

3. 读取 ImageScheme → 获取生图方案的详细配置
   → 方案包含：风格标签、模特姿势、背景类型、光线描述等

4. 读取 Product → 获取品类（决定用 FLUX 还是 Gemini）
   → 品类路由逻辑（第三章详述）

5. 构建生图提示词（方案名 + 风格标签 + 商品描述 + 平台约束）
   → 如："{scheme_name}, {style_tags}, {product_description}, 
          white background, e-commerce photography, high quality"

6. 调用 GenerationService.generate() → 三级降级生图
   → FLUX.2 Pro（主力）→ Gemini Flash Image（促销图通道）
   → SD WebUI（本地备份）→ Mock（仅开发环境）

7. 更新 GeneratedImage（图片 URL + C2PA 溯源数据 + MinIO 存储位置）
   → 图片 URL 变体生成 + C2PA Manifest 嵌入

8. 调用 evaluate_quality() → CLIP 质检 + 像素分析（L1+L2）
   → try/except 包裹：质检失败不影响任务成功！

9. 更新 GeneratedImage（质量评分 + 审核状态）
   → quality_score + review_status（AUTO_APPROVED / PENDING_REVIEW / AUTO_REJECTED）

10. 写审计日志（成功 + prompt SHA-256 哈希 + 模型名称 + 总耗时）
    → try/except 包裹：审计日志写入失败不影响任务成功！

11. Redis Pub/Sub 通知前端（"channel:generation:{image_id}"）
    → try/except 包裹：通知失败用户可以通过轮询来查询状态

12. 更新 WorkflowTask + AIUsageRecord（用量统计）
    → 记录 AI API 调用次数和 token 用量，用于计费和配额管理
```

第 8、10、11 步被 `try/except` 包裹的原因是一个关键的工程原则：**次要功能失败不能阻塞主要功能的成功。** 图片已经生成好了、已经存到 MinIO 了——这就是主要功能完成了。质检打不上分、审计日志没写入、前端没收到通知——这些是次要功能，它们出问题不该导致任务整体被标记为失败。用户看到的是"图片生成成功"，只是质量评分显示"待评估"、审计日志少了一条记录——比起"生图失败了请重试"来说好太多了。

### 5.4 失败时的降级策略

```
生图成功 + 质检失败 → 任务标记为 succeeded（质量评分留空，菜单里显示"待评估"）
生图成功 + 审计失败 → 任务标记为 succeeded（审计日志缺失，但图片本身没问题）
生图失败           → 所有后续步骤跳过，进入 retry 或 failed 流程
外部 API 返回 429   → 等 30 秒重试（通常是触发配额限制，等一下就能恢复）
外部 API 返回 5xx   → 等 30 秒重试（临时服务端错误）
外部 API 返回 4xx   → 不重试，标记 failed（请求本身有问题，重试没有意义）
```

---

## 六、Redis Pub/Sub：实时通知前端

### 6.1 轮询 vs Pub/Sub —— 两种等待模式的对比

```
轮询方式：前端每 3 秒发一次 GET /api/tasks/{task_id}/status
  优点：实现极其简单（一个 setInterval + 一个 REST API 调用）
  缺点：3 秒延迟（用户多等 3 秒看到结果）
        大量无效请求（任务在 60 秒后才完成，前 57 秒的 19 次轮询都是浪费）
        服务端压力大（1000 个等待中的用户 × 每 3 秒一次 = 每秒 333 个无效请求）

Pub/Sub 方式：前端建立 WebSocket 连接，Celery 完成后主动推送消息
  优点：零延迟（任务完成的那一刻就收到通知）
        零浪费（只在有结果时才推送，没有无效轮询）
  缺点：需要 WebSocket + Redis Pub/Sub 基础设施
        如果 WebSocket 连接断开，需要重新建立
```

SheLook 的实践是两种都支持——**Pub/Sub 优先，超时降级为轮询**。这不只是"两种方式都实现一下"，而是一个精心设计的双通道冗余策略：

### 6.2 推送流程

```
Celery Worker 完成生图（第 12 步执行完）
    │
    ▼
notify_generation_completed(generation_id, result_data)
    │
    ▼
Redis PUBLISH channel="generation:42" message='{"status":"completed","url":"..."}'
    │
    │  channel 格式：generation:{image_id}
    │  每个生图任务有自己独立的 channel
    │
    ▼
FastAPI WebSocket Handler（在 API 进程中，订阅了 channel="generation:42"）
    │
    ▼
WebSocket → 前端浏览器（"你的图好了！点击查看 → https://minio.shelook.com/images/xxx.png"）
```

### 6.3 订阅超时与降级

```python
# WebSocket handler 中
await asyncio.wait_for(_listen_for_pubsub(channel), timeout=300.0)
# 最多等 5 分钟  如果 5 分钟内没收到 Pub/Sub 通知 → 超时
# → 关闭 WebSocket → 前端自动切换到轮询模式
```

5 分钟是考虑了最坏情况的超时。生视频可能 3-5 分钟，生图一般在 2 分钟内——5 分钟覆盖了几乎所有正常场景。如果超过 5 分钟还没有 Pub/Sub 消息，说明：要么任务在队列中卡住了（Worker 全忙），要么 Pub/Sub 通道本身出问题了。此时降级到轮询，用户仍然能通过不断查询数据库中的任务状态来感知进度。

这个双通道设计体现了工程中的经典原则：**不要完全信任任何单一的消息传递机制。** WebSocket 可能因为代理超时断开（Nginx 默认 60 秒），Redis Pub/Sub 不保证消息送达（没有持久化，订阅者离线就会丢失消息）。把轮询作为永久性的兜底方案，确保"无论什么情况，用户最终都能看到结果"。

---

## 七、Celery Beat：定时任务的指挥家

### 7.1 五个定时任务及其时序编排

```
时间线（每天）：
                                                       凌晨 2:00      凌晨 3:00      凌晨 4:00      凌晨 6:00
                                                           │              │              │              │
                                                           ▼              ▼              ▼              ▼
每 10 秒 ────────────────────────────────────────────────────────────────────────────────────────────────────→
dispatch_outbox_events（持续运行）

02:00 ── sync_daily_metrics         按租户汇总每日指标
          ├── 从平台拉取过去 24 小时的图片级表现数据
          ├── 计算每张图的曝光/点击/CTR/CVR/退货率
          └── 写入 daily_metrics 表（upsert：同一天的同张图只保留最新数据）

03:00 ── retrain_models            （仅周日）按租户重训 GBDT 预测模型
          ├── 从 daily_metrics 获取标注样本（P75 正样本 / P25 负样本）
          ├── 提取每张图的 79 维特征
          ├── 训练 HistGradientBoostingRegressor（CTR）+ Classifier（爆款、退货）
          └── 保存新版模型文件 + 更新活跃版本指针

04:00 ── auto_create_experiments    扫描已审核图片，自动创建 A/B 实验
          ├── 按商品分组
          ├── 按预测 CTR 排序
          └── 找相邻且 CTR 差距 ≤ 2% 的图片对 → 创建实验

06:00 ── update_traffic_allocation  更新实验中各版本的流量分配
          └── 对每个 RUNNING 状态的实验，运行 UCB 算法更新 ratio
```

### 7.2 时间顺序为什么不能颠倒

这四个定时的时序安排是经过深思熟虑的。如果顺序不对，会出现一系列连锁问题：

```
如果先重训（03:00）再回流（04:00）：
  → 重训用的是昨天的旧数据（少了一天的反馈）
  → 新模型的预测值没有反映最新的 CTR 趋势
  → 之后创建的实验用的是基于旧模型的不够准确的预测

如果先创建实验（02:00）再重训（03:00）：
  → 实验用旧模型的预测值判断"哪两张图值得比"
  → 如果新模型预测更准，实验可能选了一对不那么有悬念的图片

正确顺序（当前）：
  先回流（02:00）→ 确保所有数据都是最新的
  再重训（03:00）→ 用最新数据训练最优模型
  再建实验（04:00）→ 用最新模型选最值得比的图片对
  再调流量（06:00）→ 给新实验最优的流量分配
```

这个编排体现了第四章和第五章的配合——数据飞轮（回流→标注→重训）的输出是 A/B 实验系统的输入（预测值→实验配对→UCB 流量分配）。

---

## 八、任务的重试与幂等性：分布式系统的基本素养

### 8.1 Celery 重试策略

```python
@shared_task(
    bind=True,
    max_retries=3,             # 最多重试 3 次
    default_retry_delay=30,    # 每次重试间隔 30 秒
)
def generate_single_image(self, ...):
```

总共 4 次尝试机会（1 次原始执行 + 3 次重试），每次间隔 30 秒。从用户体验的角度，这意味着一个任务如果第一次就失败了，最多需要 2 分钟（4 次尝试 × 30 秒间隔，不算执行时间本身）才知道最终结果。对于生图这种操作来说，2 分钟的等待是可接受的——用户不需要重新点击"生成"按钮，系统自动重试。

### 8.2 幂等性：为什么同一个操作执行多次结果不变

在分布式系统中，**至少一次投递**（At-Least-Once Delivery）是消息队列的标准语义。这不等于"只执行一次"——它意味着"任务可能被执行多次，但你的代码必须保证执行多次的结果和执行一次相同"。

幂等性在 SheLook 中的实现：

```python
# generation_task.py 中的幂等性检查
workflow_task = await db.scalar(
    select(WorkflowTask).where(WorkflowTask.id == workflow_task_id)
)
if workflow_task and workflow_task.status in {
    "cancelled", "succeeded", "running"
}:
    # 已经是终态或在执行中了 → 直接返回，不重复执行
    return {"status": str(workflow_task.status)}
```

### 8.3 为什么"至少一次投递"需要幂等性？

```
场景 1：Worker 崩溃
  任务执行到第 8 步（CLIP 质检）时 Worker 进程收到了 SIGKILL
  Celery late ack → 任务在 Broker 中仍然处于"未确认"状态
  → Broker 超时后重新投递给另一个 Worker
  → 同一个 image_id 的任务被执行第二次
  → 幂等性检查：WorkflowTask.status == "running"？
    （在第二步时已经被设置为 "running"）→ 跳过！

场景 2：网络分区
  任务执行成功，Worker 发送 ACK 给 Broker
  但 ACK 在网络传输中丢失（UDP 丢包或 TCP 连接恰好断开）
  → Broker 没收到 ACK → 认为任务未完成 → 重新投递
  → 幂等性检查发现 status == "succeeded" → 跳过！

场景 3：Outbox 重复投递
  dispatch_outbox_events 处理到一半崩溃
  event 的状态还是 pending（已锁定但还未更新为 published）
  → 10 秒后重跑 dispatch_outbox_events
  → 同一个 event 被投递两次（两次 delay() 调用）
  → 幂等性检查发现 status 已存在 → 跳过
```

三种场景的共同点：**外部不可靠（网络、进程、服务器）导致消息被重复投递。** 幂等性是应用层的最后一道防线——它不阻止重复投递的发生（这不是应用层能控制的），但它保证重复投递不会造成重复执行（这是应用层能控制的）。

### 8.4 幂等性的三层实现

SheLook 实际上使用了三个独立的幂等性机制：

1. **OutboxEvent.event_key 唯一约束**（数据库层）：防止同一个事件被写入两次。即使 API 端重复提交了完全相同的请求，Outbox 表中也只会有一条记录。

2. **WorkflowTask 终态检查**（应用层）：防止同一个任务被执行两次。即使 Celery 重复投递了同一个任务，Worker 发现任务已经是终态就会跳过。

3. **daily_metrics 的 upsert 语义**（数据库层）：`INSERT ... ON CONFLICT (image_id, date) DO UPDATE ...`，确保同一天同一张图的指标不会被重复插入。

---

## 九、WorkflowTask：任务的可观测性支柱

### 9.1 状态机设计

```python
class WorkflowTaskStatus(StrEnum):
    CREATED          = "created"          # API 写入，Outbox 未处理
    QUEUED           = "queued"           # Outbox 已投递到 Celery 队列
    RUNNING          = "running"          # Worker 开始执行
    WAITING_EXTERNAL = "waiting_external" # 等待外部 API 返回（视频生成场景）
    WAITING_HUMAN    = "waiting_human"    # 等待人工操作（审核场景，预留）
    RETRYING         = "retrying"         # 失败，等待重试
    SUCCEEDED        = "succeeded"        # 全部完成
    FAILED           = "failed"           # 最终失败（重试耗尽）
    CANCELLED        = "cancelled"        # 人工取消
```

### 9.2 为什么需要状态机？

前端的任务进度展示完全依赖 WorkflowTask 的状态：

```
CREATED  → 显示"等待投递"（骨架屏，尚无 Celery Task ID）
QUEUED   → 显示"排队中，前面还有 X 个任务"
RUNNING  → 显示进度条动画 + "预计还需要 X 秒"
WAITING_EXTERNAL → 显示"正在等待 AI 处理..."（视频生成专用）
RETRYING → 显示"正在重试第 X 次..."（带警告图标）
SUCCEEDED→ 显示生成的图片 + 下载按钮 + C2PA 溯源
FAILED   → 显示错误信息 + "重新生成"按钮
CANCELLED→ 显示"已取消"
```

状态切换不是在 Celery 内部靠返回值驱动的，而是在每个关键节点主动写数据库 (`UPDATE workflow_tasks SET status = ?`)。这确保：即使 Worker 崩溃，前端也能通过查询数据库中的状态得知任务已经走到了哪一步（"没有通知用户不等于没有进展"）。

---

## 十、架构全景图：从 API 到 Worker 到前端通知

```
                    FastAPI（生产者）
                         │
        ┌────────────────┼────────────────┐
        │                 │                │
        ▼                 ▼                ▼
   POST /schemes    POST /generate   其他业务 API
        │                 │
        │                 ▼
        │          在同一数据库事务中写入
        │          ├── GeneratedImage（status="pending"）
        │          └── OutboxEvent（status="pending"）
        │                 │
        ▼                 │（事务 COMMIT）
   Celery Beat              │
        │                   ▼
        │          dispatch_outbox_events（每 10 秒）
        │              │
        │              ├── SELECT ... FOR UPDATE SKIP LOCKED
        │              ├── generate_single_image.apply_async()
        │              └── UPDATE outbox_events SET status='published'
        │                   │
        │                   ▼
        │             Redis（Broker + Pub/Sub）
        │              │    │    │    │
        ├── 02:00 ────┐    │    │    │
        │   sync_     │    │    │    │
        │   daily_    │    │    │    │
        │   metrics   │    │    │    │
        │             │    │    │    │
        ├── 03:00 ────┤    │    │    │
        │   retrain_  │    │    │    │
        │   models    │    │    │    │
        │             │    │    │    └────── analytics Worker（定时任务）
        │             │    │    │
        ├── 04:00 ────┤    │    └─────────── model Worker（质检+索引）
        │   auto_     │    │                 CLIP 推理（CPU 密集）
        │   create_   │    │
        │   exps      │    │
        │             │    │
        └── 06:00 ────┘    │
             update_       │
             traffic_      │
             allocation    │
                           │
                    ┌──────┴──────────────┐
                    │                     │
               generation Worker    orchestration Worker
               调用外部 AI API        投递 Outbox 事件
               (Replicate/Gemini    查询+投递
                /Kling)             每个 task < 100ms
                    │
                    ▼
              生成结果 + 质检 + 存储
                    │
                    ▼
              Redis Pub/Sub
                    │
                    ▼
              FastAPI WebSocket → 前端通知
```

---

## 十一、本章小结

1. **异步任务体系**解决了 HTTP 短连接与 AI 长操作的矛盾——API 负责"决策"（50ms 返回），Worker 负责"执行"（60 秒-5 分钟完成），两者通过 Redis Broker 解耦。

2. **四队列设计**按任务耗时和资源类型分组：orchestration（轻量 <100ms）、generation（网络等待 30-300s）、model（CPU 密集 200ms-5s）、analytics（定时大批量）。`prefetch_multiplier=1` 防止慢任务囤积在单个 Worker 内存中。

3. **late ack + reject_on_worker_lost** 组合保证任务不会因为 Worker 崩溃而永久丢失——Broker 超时后自动重新投递给健康的 Worker。

4. **Outbox 模式**是本章最重要的设计——通过"数据库事务内同时写入业务数据和事件记录"，将"数据库+Redis"的跨系统双写问题转化为"纯数据库"的 ACID 原子操作。发布器每 10 秒扫描 Outbox 表投递到 Celery，即使发布器或 Redis 宕机，恢复后也不丢事件。

5. **指数退避 + event_key 唯一约束**组合防止无限重试和重复执行。退避间隔从 2 秒增长到 300 秒封顶，10 次失败后标记 FAILED。

6. **Pub/Sub 优先 + 轮询永久兜底**的双通道策略保证前端无论什么情况都能拿到任务结果——哪怕 WebSocket 断开、Redis Pub/Sub 丢失消息，轮询始终在等着。

7. **定时任务的编排顺序**（先回流→再重训→再实验→再流量）确保每一步用的都是最新数据，体现了数据飞轮（第四章）和 A/B 实验（第五章）的时序协同。

8. **WorkflowTask 状态机**让任务从创建到完成的每一个环节都对前端可观测——不是"黑盒等待 60 秒"，而是"CREATED → QUEUED → RUNNING → SUCCEEDED"的逐步推进。

下一章预告：**数据存储与文件系统**——pgvector 向量索引如何实现 O(log N) 的以图搜图、MinIO 的公私桶分离策略、Redis 在三种不同角色下的统一使用。
