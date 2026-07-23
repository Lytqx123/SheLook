# 第八章：数据存储与文件系统 —— PostgreSQL + MinIO + Redis 三位一体

> 维护说明（2026-07-23）：除原有业务表外，迁移 `018` 新增统一经营事实、效果事实、预测快照和反馈标签；Redis 不承担业务事实来源。

> 更新说明（2026-07-22）：development 环境的 PostgreSQL、Redis 与 MinIO 已通过 API 就绪检查，MinIO 业务桶也已初始化。本文的存储设计说明不替代备份恢复、对象生命周期或高负载容量验证。

---

## 一、SheLook 的三层存储架构：为什么要三套系统？

### 1.1 存储不是一种需求，而是三种完全不同的事情

任何一个 Web 应用最终都要回答一个问题：数据存在哪？但这个问题本身就有问题——"数据"不是一个同质的东西。一张 5MB 的商品图片、一条 200 字节的数据库记录、一个存活 15 秒的缓存值——它们在物理形态和访问模式上毫无共同点，指望用一套存储系统解决所有问题是"用一个锤子敲所有钉子"。

SheLook 用了三套存储系统：

```
                    SheLook 存储层
                         │
        ┌────────────────┼────────────────┐
        │                 │                │
   PostgreSQL           MinIO            Redis
   (关系型+向量)       (对象存储)       (缓存+消息)
        │                 │                │
   结构化数据         图片/视频         缓存/队列/通知
   向量嵌入           C2PA 元数据       速率限制
   租户隔离           SSRF 防护         Celery Broker
   RLS 策略           签名 URL          Pub/Sub
```

### 1.2 为什么不用一套系统解决所有问题？

这个问题可以反过来问：为什么汽车不也当船用？因为水上和陆地上的物理规律完全不同。同理：

| 需求 | 物理特征 | 最佳方案 | 如果用 PostgreSQL 替代 | 如果用 MinIO 替代 |
|------|----------|----------|----------------------|-----------------|
| 存储 10 万张商品图 | 大文件（0.5-10MB），顺序读写为主 | MinIO | pg_largeobject 将文件切成 2KB 块存入数据库——随机 I/O 退化、文件越大越慢、备份膨胀几十倍 | 本职工作 |
| 以图搜图（512 维向量检索） | 高维向量，近似最近邻查询 | pgvector + HNSW | 本职工作 | 无法做向量距离计算 |
| 商品/方案 CRUD | 小记录、多关联、事务 ACID | PostgreSQL | 本职工作 | 无法做 JOIN、WHERE、GROUP BY |
| 缓存热点数据 | 极小记录、极高频读写、允许短暂不一致 | Redis | PG 没有内置 TTL 过期策略，频繁更新的缓存会产生大量死元组（dead tuples）需要 VACUUM | 不适合 |
| 消息队列 | 暂时性、先进先出 | Redis List/Stream | PG NOTIFY/LISTEN 是通知机制而非队列——没有消息持久化、无重试 | 不适合 |
| 实时通知 | 广播、推模式 | Redis Pub/Sub | PG NOTIFY 可以但 weight 太重（每个通知需要数据库连接和事务） | 不适合 |

**SheLook 的选择哲学是：不要试图在一个存储系统上建立所有功能，而是在每个功能上用最合适的存储系统。**

---

## 二、PostgreSQL + pgvector：向量检索引擎 —— 以图搜图的数学基础

### 2.1 向量是什么？存什么？

回顾第二章：CLIP 把图片编码成 512 个 float（每个 float 是一个介于约 -1 到 1 之间的实数）。这个 512 维向量就是图片在 CLIP 空间中的"数学指纹"——相似的图片有相似的向量，不相似的图片有差异很大的向量。

```python
# product_embedding 表：给每张商品图存储 CLIP 编码
class ProductEmbedding(TenantScopedMixin, Base):
    __tablename__ = "product_embeddings"

    product_id: Mapped[int]      # 关联商品
    embedding: Mapped[str]       # Text 类型：存 '[0.12, -0.34, 0.56, ...]'
    embedding_model: Mapped[str] # "CLIP-ViT-B/32"
```

注意 `embedding` 字段的类型是 `Text` 而非 PostgreSQL 原生的 `vector(512)` 类型。代码注释说明了原因：

```
# embedding 存Text再通过::vector(512)强转，因为SQLAlchemy vector类型不太好用
```

这是一个务实的工程决策。SQLAlchemy 的 pgvector 扩展在不同版本中映射行为不一致——有时 `vector(512)` 被映射为字符串、有时被映射为自定义类型、有时在迁移脚本中生成错误的 DDL。用纯 Text 存储、查询时 `::vector(512)` 做运行时强转，完全规避了 ORM 层的类型兼容性问题。代价是每次查询都做一次文本→向量的解析（PostgreSQL 内置的 CAST 操作，微秒级开销），换来零维护成本的类型安全。

### 2.2 以图搜图的完整流程：从图片到结果

```python
# image_search.py 的 search_by_image 函数

# 步骤 1：CLIP 编码（图片 → 512 维向量）
image = Image.open(BytesIO(image_data)).convert("RGB")
query_embedding = await asyncio.to_thread(get_clip_embedding, image)
# → [0.12, -0.34, 0.56, ...]  （512 个 L2 归一化后的 float）

# 步骤 2：构造 SQL，pgvector HNSW 检索
base_sql = f"""
    SELECT pe.product_id,
           CAST(pe.embedding AS vector(512)) <=> 
           CAST('{vec}' AS vector(512)) AS distance,
           p.title, p.category, p.image_raw_url
    FROM product_embeddings pe
    JOIN products p ON p.id = pe.product_id
    WHERE p.status = 'published'
      AND pe.tenant_id = :tenant_id
      AND p.tenant_id = :tenant_id
    ORDER BY distance ASC
    LIMIT :top_k
"""

# 步骤 3：查询关联方案
# JOIN image_schemes 表，返回每个相似商品的可选视觉方案

# 步骤 4：计算相似度（距离 → 相似度的简单转换）
similarity = round(1.0 - row.distance, 4)
```

整个流程中，步骤 1（CLIP 编码 ~200ms）和步骤 2（pgvector 检索 ~10ms）之间的耗时分配很有趣：200ms 的 CPU 密集计算 + 10ms 的数据库查询。如果去掉 CLIP 编码只留下 pgvector 检索，以图搜图只需要 10ms——这已经接近实时交互的下限。真正的瓶颈不在数据库，而在 AI 模型推理。这也是为什么 product_embedding 表需要预先计算并存储向量——如果每次搜索都实时调用 CLIP，需要 200ms × N（N=数据库中所有图片数量），那就是几分钟的等待时间。

### 2.3 `<=>` 运算符：余弦距离

```sql
CAST(pe.embedding AS vector(512)) <=> CAST('[0.12,-0.34,...]' AS vector(512))
```

`<=>` 是 pgvector 扩展定义的**余弦距离运算符**。它不是 SQL 标准的一部分——你只能在安装了 pgvector 扩展的 PostgreSQL 实例上使用它。

```
余弦距离 = 1 - 余弦相似度

余弦相似度 = (A · B) / (|A| × |B|)
           = 两个向量夹角的余弦值
           = 0°（完全相同方向）→ 相似度=1 → 距离=0
           = 90°（完全无关）→ 相似度=0 → 距离=1
           = 180°（完全相反）→ 相似度=-1 → 距离=2

对于 CLIP 中已经过 L2 归一化的向量（|A| = |B| = 1）：
  余弦距离 = 1 - (A · B) = 1 - 点积
  不需要再除以模长（因为模长已经是 1），直接点积就是余弦相似度
```

**为什么用余弦距离而不是欧氏距离？**

这是向量检索中最关键的设计决策之一。两种距离度量在高维空间中有完全不同的几何解释：

```
欧氏距离：sqrt((a₁-b₁)² + (a₂-b₂)² + ... + (a₅₁₂-b₅₁₂)²)
  衡量两个点在空间中的绝对距离
  问题：CLIP 空间中，图片的"整体强度"可能变化。
        同一张图片，亮一点和暗一点，在 CLIP 编码中意味着向量的"长度"不同，
        欧氏距离会很大。但这两张图从语义上来说是几乎一样的。

余弦距离：1 - (A·B)/(|A||B|)
  只关心方向，不关心长度
  优势：两张内容相同但色调不同的图片，CLIP 向量方向几乎一样，
        余弦距离接近 0，正确反映了"语义相同"。
        只要 L2 归一化后，等于 1 - 点积，计算极其简单。
```

从信息检索的角度，余弦距离更适合"语义相似度"的场景——我们关心的不是两张图像素级别的差异（欧氏距离能捕捉到），而是它们在 CLIP 语义空间中的"概念接近程度"。两张不同的连衣裙图片，即使在像素级别上完全不同（颜色、背景、模特的姿势），只要它们都是"优雅的白色连衣裙"这个概念的实例，CLIP 向量就应该指向相似的方向——余弦距离能捕捉到这个方向相似性，欧氏距离会因像素级别的差异而给出较大的距离值。

### 2.4 HNSW 索引：O(log N) 的近似最近邻搜索

pgvector 支持两种近似最近邻（ANN）索引。注意这里的关键词是"近似"——它们不用和所有向量做精确的距离计算，而是快速地找到"大概率是最近的"几个结果：

| 索引类型 | 算法思想 | 构建时间 | 查询速度 | 召回率 | 内存占用 |
|----------|----------|----------|----------|--------|----------|
| IVFFlat | K-means 聚类 + 倒排列表：先把所有向量聚成 K 个簇，查询时只在最近的几个簇中搜索 | 快（O(N×K)，K=N/1000） | 中等（需要扫描 1-10% 的数据） | 中等（75-90%） | 低 |
| HNSW | 多层小世界图：构造一个"高速公路+普通道路"的跳表式图结构，查询时沿边快速逼近 | 慢（O(N log N)，需要构建多层图） | 极快（只需访问 ~100-500 个节点） | 高（通常 > 99%） | 高（存储图的边需要额外内存） |

SheLook 选择 HNSW 而不是 IVFFlat，基于三个考虑：

1. **查询性能更重要**：以图搜图是实时交互——用户上传图、等 200ms 的 CLIP 编码已经有点耐心消耗了，数据库检索再等 2 秒用户就放弃了。HNSW 的 10ms 和 IVFFlat 的 200ms 在实时体验上差别巨大。

2. **数据规模适中**：每个租户几千到几万张图片，10 万张图的 HNSW 索引内存占用在 500MB-1GB 之间——对于现代服务器的 8-16GB 内存配置来说完全可控。如果数据量达到千万级别，HNSW 的内存开销会变得危险（可能需要 50GB+ 的内存），那时需要换成 IVFFlat 或者考虑专门的向量数据库（如 Milvus）。

3. **召回率要求高**：以图搜图的第一个结果"是最相似的那张图"远比"搜出了 10 张有点像的图"重要。"最相似的图没搜出来"给用户的体验是"这个搜索功能不行"——而且用户不会知道是近似算法的损失，只会觉得产品做得差。HNSW > 99% 的召回率保证了几乎不会丢最优结果。

**HNSW 的核心直觉**——"跳表 + 图搜索"的结合：

```
想象你要在 100 层楼里找一个人，每层有 100 个房间：

暴力搜索：挨个房间开门看 → 最多 10000 次（O(N)）

HNSW：
  顶层（最稀疏）：只有 100 个"地标节点" → 找到最近的 → 下到下一层
  中层（中等稠密）：有 1000 个节点，和邻居之间有短边相连 → 沿边走几步
  底层（最稠密）：所有 10000 个节点都有 → 在最近的候选附近做精细搜索

总访问次数：大约 100-500 次 → O(log N) 而不是 O(N)

HNSW 构造了一个"小世界图"：
  - 顶层：长距离边（高速公路）→ 快速跨越到目标区域
  - 底层：短距离边（普通道路）→ 精细定位到最近点
  - 从任意起点出发，沿着多层图的边贪心地走到距离最近的终点
```

HNSW 的精妙之处在于它利用了小世界图的"六度分隔"理论——任何两个节点之间平均只需要很少的跳数就能到达。在 HNSW 图中，这个性质被显式地构造出来：顶层图的每个节点度（degree）很高（连接很多其他节点），提供全局导航能力；底层图的每个节点度较低（只连接真正的近邻），提供局部精细搜索能力。

### 2.5 为什么存 Text 而不是 pgvector 的 vector 类型？

数据模型的注释中有一个重要的工程决策：

```
# embedding 存Text再通过::vector(512)强转，因为SQLAlchemy vector类型不太好用
```

这不只是一个"ORM 不好用所以绕开"的问题，而是一个"开发者体验（DX）与运维体验（Ops）之间的权衡"：

```python
# SQL 中的类型转换
safe_vec = "[" + ",".join(repr(float(v)) for v in query_embedding) + "]"
# → '[0.12,-0.34,0.56,...]'  ← pgvector 接受这种文本格式

# 查询时用 PostgreSQL 的类型系统做转换
CAST(pe.embedding AS vector(512)) <=> CAST('{vec}' AS vector(512))
```

选择 Text 的三个好处：

1. **ORM 兼容性**：SQLAlchemy pgvector 扩展的 `Vector` 类型在不同版本中行为不稳定（在 0.2.x 到 0.3.x 之间发生过 API 变更）。使用纯 Text 绕开了"升级 pgvector 扩展后模型定义可能需要修改"的问题。

2. **迁移脚本简化**：Alembic 的自动迁移生成在遇到自定义类型时可能生成错误的 DDL（比如删掉并重建 `vector` 类型的列——这会把现有数据全部丢失）。Text 类型是 SQLAlchemy 内置的标准类型，Alembic 处理它没有任何特殊行为。

3. **备份恢复友好**：`pg_dump` 导出的 SQL 文件中，`vector` 类型会被写成 `'[0.12,-0.34,...]'::vector` 的语法——和你存入 Text 时的字符串一模一样。但如果在不同的数据库版本之间迁移（比如从 pgvector 0.4.x 升级到 0.7.x），`vector` 类型的二进制表示可能有变化，恢复会报错。纯 Text 不会有这个问题。

代价：每次查询时需要做一次 `::vector` 强转——但这在 PostgreSQL 内部是微秒级的 CPU 操作，在 10ms 的 HNSW 查询延迟中完全可以忽略。

---

## 三、MinIO：对象存储 —— 从草稿到发布的图片生命周期

### 3.1 为什么用 MinIO 而不是直接存本地磁盘？

```
本地磁盘方案（Docker 容器内 /data/images/）：
  优势：零额外部署、零配置、开发环境最简单
  问题：
    1. 容器重启 = 数据丢失（除非手动挂载 volume，但单机 volume 无法水平扩展）
    2. 多 Worker 需要共享文件系统 → NFS/GlusterFS → 复杂且不可靠
    3. API 服务直接处理大文件流 → 占用 FastAPI Worker 的 CPU 和带宽
    4. 没有内置的文件过期机制（需要 Cron 脚本定时清理）
    5. 没有访问控制（任何人拿到文件路径就能访问）

MinIO 方案：
  独立的 S3 兼容对象存储服务
  优势：
    1. S3 兼容 API → 所有云存储工具（awscli、boto3、mc）无缝连接
    2. 独立于 API 服务 → Worker 扩容不影响存储
    3. 预签名 URL → 时间限制的访问控制，天然适合商业数据保护
    4. 内置生命周期管理 → 私有桶 30 天自动清理（ILM 策略）
    5. 分布式模式 → 水平扩展到多块磁盘、多台服务器
```

选择 MinIO 而不是 AWS S3 本身，是因为 SheLook 需要自托管（数据留在租户可控的区域内、不经过第三方云服务商）。MinIO 是开源的 S3 兼容实现，可以在任何 Linux 服务器上运行，完全兼容 boto3 库的 API。

### 3.2 公私桶分离模式：同一张图片的两个生命周期阶段

```python
# config.py 中的两个桶
MINIO_BUCKET = "product-images"             # 公开桶：已发布的商品图
MINIO_PRIVATE_BUCKET = "product-images-private"  # 私有桶：草稿/生成中
```

**设计理念**：一张图片从生成到发布，经历了两个不同的安全等级：

```
1. AI 生图完成 → 存入私有桶（product-images-private）
         │
         只有通过预签名 URL（签名中包含 token + 过期时间参数）才能访问
         有效期 60 分钟
         即使有人截获了这个 URL，60 分钟后也无法再访问
         │
2. 运营审核通过 → 图片发布
         │
         publish_object() 被调用
         从私有桶复制到公开桶（product-images）
         注意：复制（copy），不是移动（move）——下面会解释为什么
         │
3. 公开访问
         任何人都能通过公开 URL 直接访问
         URL 格式：https://cdn.shelook.com/product-images/xxx.webp
         走 CDN 加速，全球分发
```

**为什么要分桶？——三个独立的需求**

```
需求 1：安全隔离
  如果所有图片都在一个桶 → 草稿图也能通过枚举或猜测 URL 被访问
  竞争对手可能通过爬虫枚举你的图片 URL → 看到你的产品策略、定价信息
  公私桶分离 → 没发布的图片不暴露在任何公开 URL 中

需求 2：访问模式不同
  私有桶：低频访问（审核阶段），不需要 CDN，以安全为主
  公开桶：高频访问（消费者浏览），需要 CDN 加速，以性能和全球分发为主
  如果混在同一个桶 → 要么为所有图片支付 CDN 成本（包括永远不会被客户看到的草稿），
  要么无法为公开图片提供 CDN 加速

需求 3：生命周期策略不同
  私有桶：30 天自动清理（已发布的不留草稿、过期的不保留）
  公开桶：永久保留（或按租户自己的策略）
```

### 3.3 预签名 URL：存储不存"这个链接是否有效"，而是把有效期编入链接本身

```python
# 私有图片的访问方式
client.presigned_get_object(
    bucket="product-images-private",
    object_key="shelook/2026/07/19/uuid-abc123.jpg",
    expires=timedelta(seconds=3600),  # 60 分钟过期
)
# → http://minio:9000/product-images-private/uuid-abc123.jpg?
#     X-Amz-Algorithm=AWS4-HMAC-SHA256&
#     X-Amz-Credential=shelook-minio-admin%2F20260719%2Fus-east-1%2Fs3%2Faws4_request&
#     X-Amz-Date=20260719T120000Z&
#     X-Amz-Expires=3600&
#     X-Amz-Signature=8f3a2c1b9d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f
```

预签名 URL 的核心安全机制：

```
URL 中包含的所有参数（bucket、object_key、过期时间、签名日期）
  被 MinIO 的 Access Key + Secret Key 做了 HMAC-SHA256 签名
  → 签名成为 URL 参数 X-Amz-Signature

当用户拿着这个 URL 访问 MinIO 时，MinIO 服务端做：
  1. 解析 URL 中的所有参数
  2. 用自己存储的 Secret Key 重新计算 HMAC-SHA256
  3. 比较自己计算的和 URL 中的 X-Amz-Signature
  4. 如果签名匹配 → 验证通过 → 返回文件
  5. 如果签名不匹配 → 403 Forbidden（有人篡改了 URL 参数）
  6. 如果过期时间已过 → 403 Forbidden

关键：MinIO 不需要维护"这个 URL 是否有效"的状态。任何微服务、任何无状态的 API 进程
都可以签发 URL——只要它们共享同一个 Secret Key。URL 的有效性完全编码在 URL 自身中。
```

**过期后的处理**：数据库里存的 `image_url` 可能在几小时后过期。但 `storage_bucket` + `storage_object_key` 是永久唯一的。API 在返回图片列表时自动调用：

```python
async def resolve_image_url(image):
    """根据永久字段动态签发新的有效期 URL"""
    bucket = image.storage_bucket     # "product-images-private"
    object_key = image.storage_object_key  # "shelook/northstar/dress/2026/07/uuid.webp"
    url = await presign_object(bucket, object_key)  # 新生成 60 分钟有效签名
    image.image_url = url  # 更新数据库缓存
    return url
```

这种"存永久标识 + 动态签发临时 URL"的模式，避免了数据库中充满过期的无效 URL。

### 3.4 存储路径设计

```python
object_key = f"shelook/{tenant_id}/{category}/{date:%Y/%m}/{uuid}.webp"
# 示例："shelook/northstar/dress/2026/07/a1b2c3d4.webp"
```

这个路径设计的每一层都有独立的用途：

- `shelook`：全局前缀，防止多项目共用同一个 MinIO 实例时覆盖
- `{tenant_id}`：租户隔离的第一道物理屏障（不同租户的文件在不同的目录下）
- `{category}`：便于人工审查（"看下 northstar 的连衣裙品类近期输出的图"）
- `{date:%Y/%m}`：按年月分目录——支持批量删除（"清理 2026/06 之前的草稿"）和按天归档
- `{uuid}.webp`：唯一文件名防止冲突，.webp 格式（比 JPG 小 25-35%，比 PNG 小 5-10 倍）

### 3.5 发布操作的幂等性设计

```python
async def publish_object(bucket, object_key):
    """幂等地把私有对象复制到公开桶"""
    if bucket != settings.MINIO_BUCKET:  # 已经是公开桶 → 跳过
        client.copy_object(
            settings.MINIO_BUCKET,        # 目标：公开桶
            object_key,                    # 相同 key
            CopySource(bucket, object_key),# 源：私有桶
        )
    # 关键：不删除私有桶的源文件！
    # 注释："私有源对象由调用方在数据库事务提交成功后清理，
    #        避免'对象已移动、事务却回滚'导致文件丢失"
```

两个设计细节体现了工程中对"操作顺序"的深刻理解：

1. **已经是公开桶的图跳过**：这是幂等性的直接实现——多次调用 `publish_object` 不会产生副作用。如果第二次调用时桶已经是公开桶了，`if bucket != MINIO_BUCKET` 条件为 False，整个函数跳过。

2. **不删除私有源文件**：这是"先操作、后确认"的模式。在 MinIO 复制完成后，后续的数据库事务（更新 status='published'）可能失败并回滚。如果已经删除了私有文件，回滚后就找不到源文件了。正确的做法是：数据库事务提交成功后再清理由调用方异步删除私有源文件。

---

## 四、Redis：一个服务，三种角色 —— 把 Redis 的能力用到极致

### 4.1 三个数据库编号：逻辑隔离而非物理隔离

```python
REDIS_URL = "redis://localhost:6379/0"         # DB 0：通用缓存 + 限流 + Pub/Sub
CELERY_BROKER_URL = "redis://localhost:6379/1" # DB 1：Celery 消息 Broker
CELERY_RESULT_BACKEND = "redis://localhost:6379/2" # DB 2：Celery 结果后端
```

Redis 的 database（编号 0-15，默认 16 个）是逻辑命名空间——不是物理隔离。同一个 Redis 实例的所有 database 共享同一块内存和同一个 CPU。这意味着 DB 0 的缓存数据膨胀到 8GB 时，DB 1 的 Celery Broker 也会因内存不足而变慢（即使 DB 1 自己的数据只有 50MB）。

在开发和测试环境中，用一个 Redis 实例的三个 database 编号是最简单的部署方式（docker-compose 中只需要一个 Redis 容器）。生产环境应该改为三个完全独立的 Redis URL（可能是三个独立的 Redis 实例或一个 Redis Cluster 的三个 shard），确保角色之间资源完全隔离——缓存的 OOM 不会影响 Celery 消息队列的正常运行。

### 4.2 角色 1：缓存 —— 15 秒也是缓存

```python
DASHBOARD_SUMMARY_CACHE_TTL_SECONDS = 15   # 仪表盘：15 秒过期
PRODUCT_LIST_CACHE_TTL_SECONDS = 10         # 商品列表：10 秒过期
```

10-15 秒的缓存 TTL 在"缓存"这个领域属于极其保守的策略。对比一下：
- Twitter 的时间线缓存：5 分钟
- YouTube 的推荐缓存：15-30 分钟
- 电商平台的商品详情缓存：1-5 分钟

SheLook 的 TTL 为什么这么短？

```
15 秒的考量：
  - 数据实时性要求高：运营刚生成一张图，仪表盘应该在 15 秒内反映
    （用户刷新页面的自然频率通常是 10-30 秒）
  - 缓存只是"减轻数据库重复查询"而非"避免查询"
  - PostgreSQL 单次查询只要 10-50ms → 即使有 100 个人同时看仪表盘，
    只要不是同一秒刷新，缓存就能有效减轻数据库压力
  - 瓶颈在外部的 AI API（生图 60 秒），不在数据库（查询 10ms）
    花大力气优化 10ms → 5ms 没有意义
```

"轻度缓存"策略——缓存不是为了解决严重的性能瓶颈，而是作为一种"低成本优化"来减少数据库中完全相同的重复查询。与传统高并发 Web 应用的"缓存是一切"哲学不同，SheLook 的数据实时性需求让重度缓存不适用。

### 4.3 角色 2：Celery 消息队列 —— 用 Redis List 做 Broker

```python
CELERY_BROKER_URL = "redis://localhost:6379/1"
```

Redis 作为 Celery Broker 的原理是用 Redis List 数据结构：

```
Redis List（RPUSH + BLPOP）

Producer：RPUSH "generation" '{"task_id": "abc-123", "kwargs": {...}}'
          把任务的 JSON 序列化后推到 "generation" 列表的尾部
          "generation" 就是队列名

Worker：  BLPOP "generation" timeout=1
          阻塞等待（blocking list pop）
          如果队列中有数据 → 弹出并解析 JSON → 执行任务
          如果队列为空 → 阻塞等待 1 秒后返回 None（避免永久阻塞）
          循环继续 BLPOP
```

Redis 作为 Broker 的优势和劣势：

| 优势 | 劣势 |
|------|------|
| 部署极其简单（Docker Compose 中一个服务解决缓存+Broker+结果后端） | 没有原生 ACK 机制——Celery 用 `visibility_timeout` 模拟 |
| 性能最高（全部在内存中操作，任务投递 < 1ms） | 断电/重启可能丢失未投递的消息 |
| 运维成本最低（不需要单独部署 RabbitMQ） | 大量消息时带来显著的内存压力 |

`visibility_timeout = 3600`（1 小时）是 Celery 在 Redis 上模拟 ACK 的核心机制：

```
1. Worker 从 Broker 拉取到任务 → 任务从 "generation" 列表弹出
2. Celery 自动把任务放入一个不可见的 "unacked" 列表（visibility_timeout 控制此列表的 TTL）
3. Worker 正常完成 → 发送 ACK → 任务从 unacked 列表中移除 → 完成
4. Worker 崩溃（没有 ACK） → visibility_timeout 过期（1 小时）→
   任务自动从 unacked 列表回到 "generation" 列表 → 被下一个 Worker 拉取
```

这就是为什么崩溃的 Worker 上的任务最终会"复活"并被重新处理——不是真复活，而是 visibility_timeout 的到期使任务自动回到队列。

### 4.4 角色 3：Pub/Sub 实时通知

第七章已经详述了 Pub/Sub 在通知前端中的作用。这里补充一个架构层面的洞见：

Redis Pub/Sub 有两个根本性的设计限制：

1. **不持久化**：消息发布的那一刻，如果没有任何订阅者在线——消息丢失。不像 RabbitMQ 那样可以把消息存下来等订阅者上线。
2. **不保证投递**：订阅者收到消息后，如果处理过程中崩溃——消息已经消费了，无法恢复。

SheLook 的应对策略是典型的"双通道冗余"：Pub/Sub 是主通道（快但不可靠），轮询是兜底通道（慢但可靠）。WebSocket 在 5 分钟内超时就关闭，前端自动切换到轮询——即使 Pub/Sub 消息因为网络抖动而丢失，轮询最终会发现任务状态已经变化。

---

## 五、SSRF 安全的图片获取 —— 不是防一个漏洞，是防五种攻击路径

### 5.1 SSRF 是什么？为什么对 SheLook 特别危险？

SSRF（Server-Side Request Forgery，服务端请求伪造）是一种经典的 Web 安全漏洞。攻击者提交一个精心构造的 URL，让服务器代替他去访问一个不该访问的内部资源：

```
攻击者提交图片 URL：http://169.254.169.254/latest/meta-data/iam/security-credentials/admin
（169.254.169.254 是 AWS/阿里云/腾讯云等所有云平台通用的元数据服务 IP）
如果 SheLook 不做校验直接下载 → 泄漏了云服务器的 IAM 凭证 → 攻击者获得服务器权限

攻击者提交：http://localhost:5432/
如果服务器不校验 → 攻击者可以通过服务器访问内网的 PostgreSQL，绕过防火墙

攻击者提交：http://redis:6379/
如果内网中 Redis 没有设密码 → 攻击者可以执行 Redis 命令 → 数据被篡改或删除
```

SheLook 特别危险的原因：用户在 API 参数中提交"图片来源 URL"是很常见的操作（例如"把这张参考图上传，以图搜相似风格的图片"）。如果系统不做校验就根据用户提供的 URL 去下载图片，服务器就成了攻击者的"代理"——攻击者通过服务器来探视和攻击内网资源。

### 5.2 五道防线：纵深防御，层层过滤

```python
def validate_remote_image_url(url: str) -> str:
    # 防线 1：只允许 http/https scheme
    # 拒绝 file:///etc/passwd, ftp://evil.com, gopher://..., ssh://...
    if parsed.scheme not in {"http", "https"}:
        raise ImageFetchError(...)

    # 防线 2：拒绝 URL 中的凭据
    # 拒绝 http://user:pass@evil.com/  → 防止攻击者注入认证凭据
    # 也拒绝 http://evil.com:443@internal-service/  → 防止端口混淆攻击
    if parsed.username or parsed.password:
        raise ImageFetchError(...)

    # 防线 3：白名单校验主机名
    # 只允许已知的图片托管平台
    host = parsed.hostname.lower()
    if not _is_allowed_host(host):
        raise ImageFetchError(...)

    # 防线 4：DNS 解析
    # 把主机名解析为 IP 地址
    addresses = socket.getaddrinfo(host, port)

    # 防线 5：IP 地址校验
    # 拒绝内网 IP（10.x.x.x, 172.16-31.x.x, 192.168.x.x）
    # 拒绝环回 IP（127.x.x.x, ::1）
    # 拒绝链路本地 IP（169.254.x.x）
    for addr in addresses:
        ip = ipaddress.ip_address(addr[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            if not _is_trusted_private_host(host):
                raise ImageFetchError(...)
```

五道防线各自防御不同类型的攻击：

| 防线 | 防御的攻击 |
|------|-----------|
| 1. Scheme 检查 | file:// 读本地文件、gopher:// 攻击 MySQL/Redis 协议 |
| 2. 凭据拒绝 | 通过 URL 注入认证凭据进行钓鱼或权限提升 |
| 3. 主机白名单 | 所有不在白名单中的域名 → 根本不允许发起连接 |
| 4. DNS 解析 | 将域名转换为 IP，为防线 5 做准备 |
| 5. IP 检查 | DNS Rebinding 攻击（域名指向了内网 IP）+ 裸 IP 直接攻击 |

**DNS Rebinding 攻击**是最精妙的 SSRF 变体：攻击者注册一个域名（如 `evil.com`），第一次 DNS 解析时返回合法的外部 IP（如 1.2.3.4，不在内网范围）——此时防线 4+5 检查通过。第二次 DNS 解析时（利用 TTL 很短的 DNS 记录，或攻击者控制 DNS 服务器的行为），返回内网 IP（如 127.0.0.1）——如果服务器在这个时间点重新解析 DNS 并发起连接，就穿透了 IP 检查。

SheLook 的防御方式是：在发起 HTTP 连接之前，显式地 resolve 主机名并检查所有返回的 IP 地址。不依赖 HTTP 客户端的 DNS 解析行为（可能会在连接时重新做 DNS 查询），而是在校验阶段就锁定结果。

### 5.3 白名单机制与 AI API 的 CDN 迁移

```python
IMAGE_FETCH_ALLOWED_HOSTS = [
    "placehold.co",              # 占位图服务（开发/测试）
    "replicate.delivery",        # Replicate 模型输出
    "pbxt.replicate.delivery",   # Replicate 的备用 CDN 域名
    "storage.googleapis.com",    # Google Cloud Storage（Kling API 输出）
    "ai.googleusercontent.com",  # Gemini 生成的图片托管
]
```

AI 模型 API 返回的图片通常托管在 CDN 上。这些 CDN 域名会随 API 提供商的 CDN 架构调整而变化。如果某天 Kling 把输出图片从 `storage.googleapis.com` 迁移到 `cloud.kling.com`，SheLook 的 `image_fetcher` 会拒绝这个新域名——不是安全问题，而是白名单没更新。这就是白名单机制的一个运维代价：它不是"配置一次永久生效"，而是需要随外部 API 的变化而更新。

### 5.4 MinIO 直连优化：识别自己的 URL，不走 HTTP 下载

```python
def _configured_minio_location(url: str) -> tuple[str, str] | None:
    """如果是 SheLook 自己 MinIO 的公开 URL，直接解析桶名和对象 key"""
    # 不走 HTTP 请求-响应的完整往返
    # 直接用 MinIO Python SDK 的 get_object → 零网络开销
    # （MinIO 服务端和 API 服务在同一 Docker 网络中）
```

如果 URL 指向 SheLook 自己的 MinIO，走 HTTP 下载是多余的——自己下载自己的文件，相当于把数据从 A 网络接口搬到 B 网络接口，再写回磁盘。直接使用 MinIO SDK 的对象读接口，省去一次网络往返。

### 5.5 流式大小限制：边下载边检查，不等到最后

```python
IMAGE_FETCH_MAX_BYTES = 25 * 1024 * 1024  # 25 MB，合理的安全上限

# 实现方式：流式读取（response.aiter_bytes()），
# 而不是先下载完再检查 → 防止一个 5GB 的文件先耗尽服务器内存
# 累积大小一旦超过 25MB → 立即终止下载 → 返回错误
```

---

## 六、三套存储协同工作：一次以图搜图请求的完整物理路径

以一次以图搜图请求为例，展示三层存储如何配合：

```
用户上传一张连衣裙图片 → POST /api/search/image
  │
  ▼
FastAPI 接收请求（内存中的 bytes）
  │
  ├── 1. 从请求体读取图片 bytes（在内存中，不存盘）
  │
  ├── 2. CLIP 编码（embedding_service.py）
  │      PIL Image → CLIP ViT-B/32 → [0.12, -0.34, 0.56, ...]（512 维向量）
  │      耗时 ~200ms，发生在 FastAPI 进程中，CPU 密集
  │
  ├── 3. PostgreSQL + pgvector HNSW 检索
  │      SELECT ... ORDER BY embedding <=> query_vec LIMIT 10
  │      HNSW 图遍历 ~10ms，返回 Top-10 相似商品 ID
  │      （可能在 Redis 缓存中找到热门查询 → 跳过这一步，直接返回缓存结果）
  │
  ├── 4. PostgreSQL JOIN 查询
  │      关联 product_embeddings → products → image_schemes
  │      获取商品详情 + 可选方案 + 当前主图 URL
  │      ~15ms，3 个表 JOIN
  │
  ├── 5. MinIO 动态签发预签名 URL
  │      对每张私有图片 → resolve_image_url(referenced_image)
  │      读取 storage_bucket + storage_object_key
  │      生成新的 60 分钟有效签名 URL
  │      ~5ms/图，Secret Key 已在内存中
  │
  └── 6. 返回给前端
         包含：相似商品列表 + 方案集合 + 图片签名 URL + 相似度分数
         总耗时 ~230ms（200ms CLIP + 10ms 检索 + 15ms JOIN + 5ms 签名）
```

每一步用的存储系统恰好匹配该步骤的物理特征：CLIP 推理用 CPU（在 API 进程中、不需要存储）、向量检索用 PostgreSQL pgvector（数据量数千条、查询 O(log N)）、结构化数据 JOIN 用 PostgreSQL 关系引擎、图片访问用 MinIO 预签名 URL。没有"用 Redis 存向量"（Redis 没有向量检索能力）或"用 MinIO 存商品列表"（无法做复杂查询）。

---

## 七、本章小结

1. **三种物理需求决定了三种存储系统**：大文件 → MinIO 对象存储、小记录+事务 → PostgreSQL 关系型、高频+临时 → Redis 内存缓存。没有一套系统能同时做好这三件不同的事。

2. **pgvector + HNSW 实现了 O(log N) 的以图搜图**：CLIP 编码（200ms）→ 余弦距离查询 `<=>`（10ms）→ HNSW 多层图贪心逼近。余弦距离衡量方向而非长度，更适合语义相似度场景。HNSW 以内存换时间，在 SheLook 的万级数据量下是正确选择。

3. **嵌入向量存 Text 而非 vector 类型**：规避 SQLAlchemy 扩展的 ORM 兼容性风险。查询时 `::vector(512)` 做 PostgreSQL 内置强转，微秒级开销换取零维护成本的类型安全。

4. **MinIO 公私桶分离模拟了图片从"草稿"到"发布"的安全升级**：私有桶只通过签名 URL（60 分钟过期）访问，发布后复制到公开桶走 CDN。预签名 URL 的有效性编码在 HMAC-SHA256 签名中，不需要 MinIO 维护 URL 状态。

5. **动态签发 URL**（`resolve_image_url`）保证返回给前端的链接始终有效——数据库存永久标识（bucket + object_key），API 层在返回时动态生成新的 60 分钟签名。

6. **Redis 一个实例承担三种角色**（缓存、消息队列、Pub/Sub），通过 database 编号做逻辑隔离。开发环境共享实例，生产环境应分离为独立的 Redis URL。`visibility_timeout` 模拟了 Celery 在 Redis 上的 ACK 机制。

7. **五道 SSRF 防线层层递进**：Scheme → 凭据 → 域名白名单 → DNS 解析 → IP 检查。DNS Rebinding 是其中最精妙的攻击变体——SheLook 通过显式解析并检查所有 IP 来防御。

8. **"轻度缓存"策略**（10-15 秒 TTL）是在"数据实时性"和"减轻数据库重复查询"之间的折中——瓶颈在 AI API（60 秒），不在数据库（10ms），不需要重度缓存。

下一章预告：**前端架构**——Next.js 16 + React 19 的 17 页面布局、page.tsx/Content.tsx 分离模式、React Query v5 智能轮询、Zustand 极简全局状态、Ant Design 6 企业级组件体系。
