# SheLook｜跨境电商视觉运营决策系统

> 文档基线：2026-07-23。当前数据库迁移头为 `018`；本文描述已部署能力，不把等待供应商授权的接口视为已完成同步。

SheLook 面向跨境电商运营团队，把商品视觉工作从一次性的素材制作，组织成可追踪、可验证、可复用的经营决策流程。系统以“视觉运营活动”为主线，串联商品、市场目标、视觉策略、素材生产、质量门禁、效果预测、A/B 实验、经营指标和复盘洞见。

它不是单纯的 AI 生图后台：生成只是起点，最终要回答的是“这次活动该做什么、为什么做、何时进入实验，以及结果如何改善下一次决策”。

## 本次验证基线（2026-07-23）

本仓库已在本机 `development` Compose 环境完成一次可运行性复核：迁移已执行至 `018`，MinIO 四个业务桶已初始化，API 的 `/api/health/ready` 同时确认 PostgreSQL、Redis 与 MinIO 为 `ok`，并可经 Nginx 的 `/api/health/ready` 访问。API、三个分队列 Worker、Beat、Flower、前端、Nginx、Prometheus、Grafana、PostgreSQL、Redis 与 MinIO 均已启动并通过各自健康检查。

本次还复验了前端生产构建、前端静态检查、后端 Ruff/编译检查、79 项后端回归测试、完整性/RLS 门禁，以及连续 outbox 分发。Celery 的同步任务桥接现在会在 fork 后重置继承的异步连接池，并在每次 `asyncio.run` 结束前释放连接，避免 asyncpg 连接跨事件循环复用；Beat 已实际持续派发任务，Worker 已成功消费。此记录是功能与集成冒烟结果，**不是容量、外部 AI 供应商或真实经营效果的承诺**；性能验证范围见 [PERFORMANCE.md](./PERFORMANCE.md)。

为降低后续维护风险，视觉运营活动 API 已按路由入口、共享鉴权与状态校验、详情聚合读模型拆分为三个模块；两个既有活动 URL 前缀及其请求、响应契约保持不变。

## 当前产品主线

一项视觉运营活动可以围绕一个商品和目标市场建立，并在活动详情中汇总候选素材、审核结果、预测判断、实验状态、真实指标、时间线和可复用洞见。当前活动阶段为：需求简报、策略、生产、审核、预测、实验、学习；活动状态会随业务推进在草稿、进行中、待审核、实验中、学习中、完成和归档之间流转。

典型工作路径如下：

1. 创建视觉运营活动，设定商品、市场、经营目标及目标指标。
2. 在发品工作台建立商品、选择或生成视觉方案与图片、视频素材。
3. 将素材送入质量审核和效果预测，查看质量结果、点击潜力、爆款概率、退货风险及下一步建议。
4. 从预测页挑选候选素材发起 A/B 实验，以真实流量和指标验证方案。
5. 将实验或经营结果沉淀为活动洞见，并在数据飞轮中同步样本、触发训练流程或查看模型版本。

## 已实现能力

| 能力域 | 当前实现 |
| --- | --- |
| 视觉运营活动 | 建立活动目标、阶段和负责人；聚合商品、方案、素材、审核、预测、实验、指标、时间线及洞见。 |
| 商品与内容生产 | 商品管理、视觉方案推荐、相似素材检索、图片生成、视频生成、平台规格导出。 |
| 质量与风险门禁 | 自动审核、人工审核队列、质量维度、内容合规与问题追踪。 |
| 经营决策 | CTR、爆款潜力、退货风险预测；候选方案比较；可从预测结果创建 A/B 实验。 |
| 验证与学习 | A/B 实验、流量与结果拆解、指标导入和平台同步、样本沉淀、模型训练与版本管理。 |
| 协同与治理 | 角色化首页和菜单、任务中心、供应商协同、组织/租户上下文、审计日志、功能开关和配额。 |
| 分析能力 | 经营首页、市场与风格分析、聚类分析、公平性分析、供应商质量分析。 |

## 技术组成

| 层级 | 当前组件 |
| --- | --- |
| 前端 | Next.js 16、React 19、TypeScript、Ant Design 6、TanStack Query、Zustand、Recharts、Tailwind CSS 4。 |
| 服务端 | Python 3.13、FastAPI、Pydantic 2、SQLAlchemy Async、Alembic。 |
| 任务与缓存 | Celery、Redis、Redis Pub/Sub、Flower。 |
| 数据与存储 | PostgreSQL 17、pgvector、MinIO。 |
| AI 与分析 | CLIP、Transformers、PyTorch、scikit-learn、HDBSCAN；按配置接入外部图像、视频和平台服务。 |
| 可观测与部署 | Prometheus、Grafana、结构化日志、可选 OpenTelemetry、Docker Compose、Nginx。 |

## 快速启动

前提：已安装并启动 Docker Desktop 或 Docker Engine，以及支持 `!reset`/`!override` 覆盖语义的现代 Docker Compose v2。外部 AI、视频和电商平台密钥均为可选配置；缺少它们时，对应能力不会作为真实第三方调用运行。

Windows：

~~~powershell
.\setup.ps1 -Env dev
~~~

Linux / macOS：

~~~bash
./setup.sh --env dev
~~~

上述脚本会创建 `.env.dev`、构建开发镜像、执行独立数据库迁移、初始化对象存储并启动服务。默认保持空业务库，不会写入演示数据。

如需在本地开发库填充合成演示数据，必须显式开启并完成二次确认：

~~~powershell
.\setup.ps1 -Env dev -SeedDemo
# CI 或非交互场景：.\setup.ps1 -Env dev -SeedDemo -ConfirmSeedDemo
~~~

~~~bash
./setup.sh --env dev --seed-demo
# CI 或非交互场景：./setup.sh --env dev --seed-demo --confirm-seed-demo
~~~

演示数据只能写入 `development`/`test` 环境；启动脚本和数据脚本都会拒绝在预发或生产写入。预发、生产分别使用 `.env.staging`、`.env.prod`，缺失时会从对应的受控模板创建一次。发布前必须填写不可变镜像 digest、非开发凭据、CORS、企业认证、C2PA 文件、指标密钥文件和迁移连接：

~~~powershell
.\setup.ps1 -Env staging -Update
.\setup.ps1 -Env prod -Update
~~~

~~~bash
./setup.sh --env staging --update
./setup.sh --env prod --update
~~~

预发、生产默认不启动 Flower；如确有受控排障需要，可使用 `-WithOps` / `--with-ops` 启动它。该服务没有宿主机端口，仅在内部网络可达。

### 旧本地 Compose 环境升级

旧版本默认使用项目名 `shelook`，并可能把数据库、缓存、对象存储和管理端口直接暴露在宿主机；新开发基线默认使用 `shelook-dev`。启动脚本不会自动停止旧项目，也不会自动迁移旧数据卷，以避免意外中断或覆盖数据。若确认不再使用旧本地环境，可先执行 `docker compose -p shelook down`（不会删除卷），再启动新环境；若需要保留旧数据，应先完成备份/恢复或明确制定卷迁移方案。

常用地址：

| 服务 | 地址 |
| --- | --- |
| 统一入口 | http://localhost |
| 前端应用 | http://localhost:3000 |
| 后端健康检查 | http://localhost:8000/api/health |
| MinIO 控制台 | http://localhost:9001 |
| Flower | http://localhost:5555/flower |
| Prometheus | http://localhost:9090 |
| Grafana（Nginx 子路径） | http://localhost/grafana/ |
| Grafana（本机诊断端口） | http://localhost:3001 |

如果宿主机策略或其他本地服务占用 80 端口，可在 `.env.dev` 设置 `NGINX_PORT=8080`，统一入口随之改为 `http://localhost:8080`，并将 `GRAFANA_ROOT_URL` 同步设为 `http://localhost:8080/grafana/`；此项只影响开发环境，预发和生产仍应由受控入口提供 80/443。

FastAPI 文档仅在 DEBUG=true 时挂载，可通过 http://localhost:8000/docs 访问；生产配置不会默认公开该入口。

## 本地开发

前端开发：

~~~powershell
Set-Location frontend
npm ci
Set-Item Env:BACKEND_URL http://localhost:8000
npm run dev
~~~

后端开发前，请先通过启动脚本或 Docker Compose 准备 PostgreSQL、Redis 和 MinIO；随后执行：

~~~powershell
Set-Location backend
uv sync --extra providers --extra observability --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
~~~

## 文档索引

- [项目介绍](./项目介绍.md)：面向产品、面试和业务沟通的项目定位与价值说明。
- [前端说明](./前端.md)：当前页面、交互、状态管理和前端运行方式。
- [后端说明](./后端.md)：服务边界、接口、数据安全、任务与部署说明。
- [当前方案](./方案.md)：已落地的产品主线、架构边界和运行方案。
- [企业数据接入与 CTR 闭环路线图](./重构方案/07-企业数据接入与CTR闭环六阶段路线图.md)：店小秘优先接入、运行时配置中心与真实 CTR 模型反馈的六阶段实施计划。
- [外部 API 网页配置](./重构方案/08-全仓审计与文档治理.md)：业务供应商凭据的租户隔离、加密保存、运行时读取与部署验证口径。
- [全仓审计与文档治理](./重构方案/08-全仓审计与文档治理.md)：文档分层、当前实施基线、审计口径及维护规则。
- [性能与发布验证](./PERFORMANCE.md)：压测场景、指标口径和发布验证方法。
- [Kubernetes 部署](./deploy/kubernetes/README.md)：Kubernetes 清单与部署说明。

## 当前边界与生产安全

- 图像生成、视频生成、AI 审核及 Amazon、Shopee 等平台同步依赖相应的外部凭据和服务可用性。业务 API 凭据不再写入 `.env` 或 Compose 环境：管理员在“系统集成 / 外部 API 配置”中按租户录入，服务端加密保存、运行时读取且从不回传明文；开发环境仍可显式使用占位生成，预发、生产必须关闭该模式。
- 店小秘已落地租户级 Web 集成中心：管理员可保存店铺范围、同步范围和加密凭据，并可创建异步同步任务。没有贵司已授权的接口地址、签名规则、字段契约和游标规则时，任务会明确停在 `awaiting_provider_contract`，系统不会伪造同步成功。集成凭据的加密根密钥仍属于启动级 Secret，不能迁入网页。
- 已增加“运行时配置”页面和版本化配置 API。当前开放 CTR 基线、A/B 实验完成曝光量和 CTR 成熟最小曝光量；保存后由实际 API/Worker 在下一次执行时解析。数据库、Redis、JWT、TLS 和根加密密钥仍由部署 Secret 管理。
- 2026-07-23 已部署验证外部 API 配置中心：迁移头为 `019`，`provider_configs` 启用租户 RLS；视频页与配置页可访问，临时假凭据能加密保存、状态即时生效且不回显，删除后视频生成明确返回不可用。完整后端回归测试为 82 通过。
- 外部实体映射、经营事实、真实效果事实、预测快照和反馈标签已分表保存。真实 CTR 严格由 `sum(clicks) / sum(impressions)` 计算，并且只在映射完成、数据成熟且达到最小曝光量后用于模型反馈；它不会覆盖历史预测记录。
- 演示数据为显式、开发专用动作：启动默认不填充；预发、生产和直接脚本调用都会被环境保护拒绝。
- Compose 的预发、生产路径只拉取带 `@sha256:` digest 的不可变镜像。API/Worker 不再自行迁移数据库，迁移由独立 `migrate` 服务执行；生产指标采集使用文件型 Docker secret，不把 Bearer 凭据写入 Prometheus 配置。
- Grafana 通过 Nginx 的 `/grafana/` 提供服务。开发环境默认使用 `http://localhost/grafana/`；预发和生产必须显式配置以 `/grafana/` 结尾的 HTTPS `GRAFANA_ROOT_URL`，避免登录跳转到错误入口。
- 预测、实验和学习模块提供经营判断与证据，不承诺固定业务提升；结果质量取决于实际业务数据、样本覆盖与运营执行。
- 前端的菜单隐藏用于改善使用体验，真正的数据范围和写入权限由后端认证、成员关系、租户边界和数据库行级安全共同约束。
- 仓库尚未发布可泛化的容量压测结论。部署规模应以目标环境的实测报告为准，详见 [性能与发布验证](./PERFORMANCE.md)。
