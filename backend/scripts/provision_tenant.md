# 受控租户与首位管理员引导

> 文档基线：2026-07-23。该流程必须在受控管理员身份和明确的租户上下文中执行。

`python -m scripts.provision_tenant` 是部署运维命令，不是公开注册接口。它在一个事务中创建或校验一组明确的数据：`Tenant`、默认 `TenantQuota` 和首位已启用的 `TenantMembership(admin + tenant:manage)`。外部身份登录只能匹配已有成员，不能自行创建租户、成员或权限。

> 文档状态（2026-07-23）：脚本与当前迁移头 `018` 对齐。租户引导需要在数据库迁移和身份映射已完成后执行；development 的可运行性验证不替代真实企业身份的上线验收。

## 何时使用

在数据库迁移完成、飞书或企业 OIDC/SSO 配置就绪后，为每个新组织执行一次。生产环境必须先在身份提供方登记 HTTPS 回调地址，再由受控发布流程执行本命令；不要把前端参数、邮箱或用户自报信息当作租户归属依据。

## 输入与身份映射

命令要求显式提供：

- `--tenant-id`：1–36 位稳定本地租户 ID，只能包含字母、数字、点、下划线或连字符。
- `--slug`：稳定的小写组织标识，只能包含小写字母、数字和连字符。
- `--name`：组织显示名称。
- `--admin-identity-provider`：`feishu` 或 `oidc`。
- `--admin-subject`：飞书使用受控流程获得的 `open_id`；OIDC 使用身份提供方返回的原始 `sub` claim。
- `--admin-display-name`：首位管理员显示名。

脚本根据身份来源、OIDC issuer 和原始 subject 生成规范化本地成员键。原始 OIDC `sub` 不会直接作为数据库成员 ID，因此不会与飞书身份或其他 issuer 的同名 subject 冲突。

## 本地或 Docker Compose 用法

先做只读校验：

```bash
docker compose exec backend python -m scripts.provision_tenant \
  --tenant-id acme-prod \
  --slug acme \
  --name "Acme Commerce" \
  --admin-identity-provider feishu \
  --admin-subject "ou_xxxxxxxxx" \
  --admin-display-name "Acme Admin" \
  --dry-run
```

确认输出与身份映射正确后，改用 `--confirm` 执行写入：

```bash
docker compose exec backend python -m scripts.provision_tenant \
  --tenant-id acme-prod \
  --slug acme \
  --name "Acme Commerce" \
  --admin-identity-provider feishu \
  --admin-subject "ou_xxxxxxxxx" \
  --admin-display-name "Acme Admin" \
  --confirm
```

OIDC 场景只需将 `--admin-identity-provider` 改为 `oidc`，并填入该用户精确的原始 `sub`。`--confirm` 与 `--dry-run` 互斥；两者都不提供时，命令会拒绝运行。

## 安全与幂等规则

对完全相同的输入重复执行是安全的：已有且状态正确的租户、配额和管理员成员会被校验，不会被改写。以下情况会以非零状态退出，要求人工处理，而不是猜测或提升权限：

- 租户 ID、slug 或名称与既有数据冲突；
- 租户不是 `active`；
- 目标成员已存在但不是已启用的管理员，或缺少 `tenant:manage`；
- 租户已有其他成员，但请求的首位管理员不存在；
- 并发写入或数据库约束导致数据不一致。

脚本在打开事务前安装 `tenant_context`，让 PostgreSQL 行级安全策略能够约束 `tenant_memberships` 与 `tenant_quotas`；发生任何异常时整笔操作回滚。输出只包含租户、身份来源、不可逆本地成员键与创建/校验状态，不输出令牌、密钥或外部身份资料。

## Kubernetes 用法

`deploy/kubernetes/base/tenant-provision-job.example.yaml` 是刻意不含 `--confirm` 的模板，且未被基础 kustomization 自动引用。将它复制到受保护的部署仓库，替换镜像、租户与管理员占位符，经过审批后才在 `args` 末尾加入 `--confirm`：

```bash
kubectl -n shelook apply -f /secure/deployment/shelook-tenant-provision-job.yaml
kubectl -n shelook logs -f job/shelook-provision-tenant
kubectl -n shelook wait --for=condition=complete job/shelook-provision-tenant --timeout=5m
```

每个新组织使用一个独立、可追踪的 Job 名称，并保留 Job 日志作为受控部署审计记录。旧版将原始 OIDC subject 直接写入成员 ID 的环境，应先使用 `python -m scripts.migrate_oidc_membership --dry-run` 逐项核查，再在批准窗口内使用 `--confirm` 迁移。
