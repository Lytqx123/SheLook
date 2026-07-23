# SheLook Kubernetes 部署基线

> 文档基线：2026-07-23。Kubernetes 清单是部署基线，不取代目标云环境的证书、入口、备份和密钥治理方案。

此目录提供 SheLook 后端在 Kubernetes 上的生产部署基线：API、编排/生成/分析队列 Worker、单实例 Celery Beat 调度器、模型工件共享卷、弹性与可用性策略，以及受控的迁移和租户引导 Job。它**不**部署前端、Ingress、PostgreSQL、Redis、MinIO 或外部身份提供方；这些依赖应由组织的受管服务与基础设施层负责。

> 文档状态（2026-07-22）：已用 `kubectl kustomize deploy/kubernetes/base` 验证清单可渲染。本文是部署基线而非已在特定集群完成的上线证明；镜像、Secret、入口、备份和告警仍必须由目标环境提供。

## 基线内容

| 文件 | 当前作用 |
| --- | --- |
| `base/kustomization.yaml` | 声明命名空间、运行配置、PVC、API、Worker 与弹性资源；镜像默认示例标签为 `1.1.0`。 |
| `base/api.yaml` | 3 副本 API、滚动更新、只读根文件系统、健康检查与共享模型目录。 |
| `base/workers.yaml` | 分离 `orchestration`、`generation`、`model,analytics` 队列，分别独立扩容与限额。 |
| `base/beat.yaml` | 单副本、Recreate 策略的 Celery Beat；调度 Outbox、指标、实验和训练等周期任务，避免滚动更新时重复调度。 |
| `base/resilience.yaml` | API PodDisruptionBudget（最少 2 个可用）和 HPA（3–20 副本，按 CPU/内存）。 |
| `base/migration-job.yaml` | 仅迁移时使用 schema-owner 连接的手工 Job。 |
| `base/tenant-provision-job.example.yaml` | 不自动执行、默认不写入的首位管理员引导模板。 |

## 部署前检查

1. 构建并推送不可变后端镜像，将 `base/kustomization.yaml` 中的 `newName`、`newTag` 替换为本次发布镜像。
2. 准备 `shelook-runtime` Secret：运行时非 owner 的 `DATABASE_URL`、Redis/MinIO 凭据、`SECRET_KEY`、独立的 `INTEGRATION_CREDENTIALS_ENCRYPTION_KEY`、生成提供方凭据和外部身份配置。集成根密钥用于加密 Web 中保存的店小秘凭据，不能与会话密钥复用或进入 ConfigMap。API、Worker 与租户引导 Job 绝不能挂载 schema-owner 凭据。
3. 准备 `shelook-c2pa` Secret，其中必须包含键名为 `certificate.pem` 和 `private-key.pem` 的 C2PA 证书及私钥。只有 API（用于启动时校验）和 generation Worker（用于签名）会以只读方式挂载它；不要把私钥加入 `shelook-runtime` 或其他 Worker。
4. 准备单独的 `shelook-migration` Secret，仅保存 `DATABASE_MIGRATION_URL`，供迁移 Job 使用。
5. 提供支持 `ReadWriteMany` 的 `shelook-model-artifacts` PVC；API 与分析 Worker 通过它共享模型版本和工件。
6. 检查 `base/runtime-config.yaml` 中区域、队列并发、数据库连接池、CORS、`ENABLE_AUTH=true`、`ALLOW_GENERATION_MOCKS=false` 和 C2PA 文件路径是否适合目标环境。
7. 由基础设施层提供 TLS、Ingress/网关、前端托管、高可用数据库、Redis、MinIO、备份与告警。

运行账户应是非超级用户、无 `BYPASSRLS` 权限的数据库账户。PostgreSQL 角色划分参考 [`deploy/postgres/roles.sql.example`](../postgres/roles.sql.example)。

## 推荐发布顺序

先在受保护的发布仓库中复制并替换迁移 Job 的镜像占位符，执行迁移并等待成功：

```bash
kubectl -n shelook apply -f /secure/deployment/shelook-migration-job.yaml
kubectl -n shelook wait --for=condition=complete job/shelook-migrate-manual --timeout=10m
```

再渲染并应用基础资源：

```bash
kubectl kustomize deploy/kubernetes/base
kubectl apply -k deploy/kubernetes/base
kubectl -n shelook rollout status deployment/shelook-api --timeout=10m
kubectl -n shelook get pods
```

API 的就绪与存活端点分别为 `/api/health/ready`、`/api/health/live`。应用指标端点是 `/metrics`；Prometheus 必须携带 `Authorization: Bearer <METRICS_API_KEY>`，不得通过公共入口暴露该端点。

## 身份与租户边界

生产配置启用认证后，至少配置一种外部身份来源：飞书 OAuth 或通用企业 OIDC/SSO。公开回调地址应为 `https://<public-ui-host>/login/callback`，并与 `FEISHU_REDIRECT_URI` 或 `OIDC_REDIRECT_URI` 完全一致。多租户环境使用 `FEISHU_TENANT_KEY_MAP` 或 `OIDC_TENANT_CLAIM_MAP` 将外部组织标识显式映射到本地 `tenant_id`；不能信任客户端传入的租户 ID。

在首位成员登录前，使用受控 Job 创建本地租户与管理员，详见 [`backend/scripts/provision_tenant.md`](../../backend/scripts/provision_tenant.md)。示例 Job 默认省略 `--confirm`，直接应用不会写入数据。

## 上线后核验

- 确认 API 三副本均通过 readiness，Worker 分队列正常消费且无持续重试，Celery Beat 恰好只有一个运行实例。
- 确认迁移版本与发布镜像匹配，并以运行账户验证 RLS 租户隔离。
- 从已授权组织完成一次登录，检查角色导航、活动创建、审核、预测、实验和复盘的权限边界。
- 验证 `/metrics` 仅能被携带密钥的采集器访问，日志与审计记录不包含外部令牌或密钥。
- 在非生产环境演练 API 滚动更新、Worker 故障恢复和数据库备份恢复；生产阈值与告警应按真实容量数据设定。
