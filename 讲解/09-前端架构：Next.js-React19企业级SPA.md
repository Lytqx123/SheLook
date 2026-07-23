# 第九章：前端架构 —— Next.js React 19 企业级 SPA

> 维护说明（2026-07-23）：前端当前包含店小秘集成、外部 API 配置和运行时配置页面；浏览器仅提交只写凭据，所有授权仍由后端判定。

> 更新说明（2026-07-22）：当前前端使用 Next.js 16.2.11、React 19；静态检查和生产构建已通过。页面和组件数量会随功能演进调整，应以 `frontend/src/app` 的现行路由为准。

---

## 一、为什么选择 Next.js？—— 不是追新技术，是解决真问题

### 1.1 后台管理系统的前端选型困境

SheLook 本质上是一个**后台管理系统**（Dashboard + CRUD + 图表 + 实时通知）。这类应用通常有两个技术路线：

| 方案 | 代表 | 优势 | 劣势 |
|------|------|------|------|
| 纯 SPA | Vite + React | 构建快、配置简单、生态成熟 | 需要额外的路由库、无内置 API 代理、SEO 差（但后台不需要 SEO）、首屏需要加载完整的 JS bundle |
| 全栈框架 | Next.js / Nuxt | SSR + 路由约定 + API 代理 + 图片优化 + 流式渲染 | 学习曲线、框架约束多、构建产物更复杂 |

对于后台管理系统来说，SEO 不重要（搜索引擎不会索引管理后台的页面），SSR 也不是刚需（用户登录后加载的交互式仪表盘不需要服务端渲染）。那为什么 SheLook 还选 Next.js？

答案是三个"恰好"：**恰好解决了三个传统 SPA 模式下需要额外引入第三方库才能解决的工程问题。**

### 1.2 三个核心价值

**价值 1：API 代理 —— 一道免费的安全防线**

在 Vite + React 的架构中，前端需要直接调用后端 API。这意味着前端代码中必须包含后端 URL——`VITE_API_BASE_URL = "https://api.shelook.com"`——这个地址对任何打开浏览器开发者工具的人都可见。虽然暴露 URL 本身不构成安全漏洞（后端仍然有认证），但它增加了攻击面（攻击者可以直接用这个地址做字典扫描、暴力破解等）。

Next.js 的 `rewrites` 机制提供了一个更优雅的方案：

```typescript
// next.config.ts
rewrites: async () => [
  {
    source: "/api/:path*",
    destination: `${backendUrl}/api/:path*`,
  },
]
```

前端所有请求都发往 `/api/*`——这是 Next.js 自身的路由。Next.js 在服务端将请求转发到真实的后端地址。浏览器的网络面板中看到的始终是 `/api/products`，后端真实地址（`http://backend:8000`）从未暴露给客户端。这相当于在 Next.js 服务端做了一层透明的反向代理，零配置、零运维。

**价值 2：路由约定 —— 文件夹即路由**

传统 SPA 需要 React Router 手动配置路由表。17 个页面意味着 17 条路由配置——页面增删时需要同时修改路由文件。Next.js App Router 采用"文件夹即路由"的约定：`src/app/products/page.tsx` 自动映射为 URL `/products`。新增一个页面就是新建一个文件夹加一个文件，不需要修改任何路由配置。这种"约定优于配置"的模式在页面数量增长时价值尤为明显——不需要维护一份越来越长的路由列表。

**价值 3：Standalone 部署 —— Docker 镜像不需要 npm install**

```typescript
output: "standalone"
```

这个配置让 Next.js 在构建时自动分析依赖，打包出一个最小化的、自包含的 Node.js 应用——只包含运行时真正需要的 `node_modules` 子集。Dockerfile 中只需要 `COPY` 不需要 `npm install`——这意味着生产镜像中没有 TypeScript 编译器、ESLint、Prettier、Tailwind JIT 编译器等开发工具，镜像体积小、构建快、安全性高（攻击面小）。

---

## 二、页面架构全景：17 个页面，一个模式

### 2.1 页面地图

```
src/app/(main)/
├── dashboard/        仪表盘 —— 关键指标总览、CTR 趋势图、市场分布
├── campaigns/        运营活动 —— 按活动维度组织生图和方案
├── products/         商品管理 —— 商品 CRUD、图片上传、以图搜图入口
├── publish/          方案发布 —— AI 生图的主入口、视觉方案配置
├── review/           审核工作台 —— L1 像素级 + L2 CLIP 零样本 + L3 Gemini AI 审核
├── tasks/            任务中心 —— 所有 Celery 任务的实时进度追踪
├── prediction/       效果预测 —— CTR/爆款/退货风险预测查询
├── experiments/      实验列表 —— A/B 实验管理中心
├── experiments/[id]/ 实验详情 —— 单实验的深度分析（趋势图、维度下钻、流量分配图）
├── images/[id]/      图片详情 —— 图片信息面板、C2PA 溯源数据、质量评估结果
├── video-generate/   视频生成 —— 图生视频的上传、提示词、进度追踪
├── supplier/         供应商协作 —— 外部供应商作品上传、历史分析、业绩统计
├── fairness/         公平性分析 —— 肤色分布统计、市场偏见检测报告
├── clustering/       风格聚类 —— 商品图基于 CLIP 向量的自动风格分组
├── flywheel/         数据飞轮 —— 回流数据概览、标注样本质量、模型版本管理
├── metrics/          指标管理 —— 自定义预测指标、模型效果回溯
├── audit-logs/       审计日志 —— 操作记录搜索、追溯、导出
└── login/            登录（独立路由组，不经过 AppLayout）
```

### 2.2 核心模式：page.tsx + Content.tsx 分离

每个页面目录遵循统一的结构：

```
products/
├── page.tsx             ← 服务端组件（Server Component）：极简包装
├── ProductsContent.tsx  ← 客户端组件（Client Component）：所有逻辑
└── loading.tsx          ← 加载态骨架屏

其中：
page.tsx 只有两件事：
  1. export metadata（SEO 相关，如页面标题）
  2. 渲染 ProductsContent

ProductsContent.tsx 有所有东西：
  1. React Query hooks（数据获取）
  2. 交互逻辑（CRUD、分页、搜索、排序）
  3. 浏览器 API 调用（localStorage、window、WebSocket）
```

**为什么要分离？—— React 服务端组件和客户端组件的根本区别**

这是 Next.js 13+ App Router 引入的最重要的架构概念。在 App Router 中，所有组件默认是**服务端组件**——它们在服务端渲染为 HTML 字符串，从不发送 JavaScript 到浏览器。只有显式标记了 `'use client'` 的组件才是客户端组件——它们会在浏览器中被 React 重新渲染，支持用户交互。

服务端组件的价值在于：**零客户端 JavaScript。** 一个只有静态内容的页面（比如产品文档），整个组件树的代码都不会打包到客户端的 JS bundle 中。但服务端组件不能使用浏览器 API（如 `useState`、`useEffect`、`onClick`、`localStorage`）。

`page.tsx + Content.tsx` 分离模式的精妙之处在于：它让 `page.tsx` 作为服务端组件（可以利用 Next.js 的静态优化、SEO metadata），而 `ProductsContent.tsx` 作为客户端组件（可以使用所有浏览器交互能力）。Next.js 在编译时识别出服务端组件只是简单地渲染了一个客户端组件，会将它优化为最小化的服务端包装。

```
Next.js 编译优化：

page.tsx（服务端）         ProductsContent.tsx（客户端）
  export metadata            'use client'
  return <Content />   →    function ProductsContent() { ... }
  
经过编译后：
  page.tsx → 在服务端渲染为 HTML（只包含 metadata + 少量占位内容）
  ProductsContent.tsx → 打包到客户端的 JavaScript bundle 中
                       → 浏览器加载后 React 对 ProductsContent 做水合（hydration）
```

### 2.3 路由组 `(main)`：不影响 URL 的布局分组

```
src/app/
├── (main)/           ← 圆括号 = 路由组，不产生 URL 段
│   ├── layout.tsx    ← 所有 (main) 内页面共享的布局（AppLayout）
│   ├── dashboard/    → 浏览器 URL: /dashboard
│   └── products/     → 浏览器 URL: /products
│
└── login/            → 浏览器 URL: /login（不受 (main) 的 layout.tsx 影响）
    └── page.tsx       拥有自己独立的未认证布局
```

路由组解决了"同一批页面共享同一个布局，但另一批页面不需要"的问题。登录页面不需要 Sidebar 和 Header——它应该是一个纯净的登录表单。路由组让 `/login` 完全摆脱 AppLayout 的包裹，同时保持 URL 结构简洁（登录页就是 `/login`，不是 `/main/login` 或 `/app/login`）。

---

## 三、AppLayout：所有已认证页面的"壳"

### 3.1 三层布局嵌套

```
根布局 (app/layout.tsx)
  └── <html lang="zh">
        └── <body>
              └── <Providers>          ← React Query + Zustand + Ant Design ConfigProvider
                    │
                    └── (main)/layout.tsx
                          └── <AppLayout>
                                ├── Layout.Sider  → <Sidebar>
                                ├── Layout.Header → <Header>
                                └── Layout.Content
                                      └── <ErrorBoundary>
                                            └── {children}  ← 当前路由的 page.tsx 内容
```

`Providers` 在根布局中包裹整个应用树，确保 React Query 的 queryClient、Zustand 的 store、Ant Design 的主题配置在所有页面中都可用。这些 Provider 不需要在每个页面中重复声明——根布局中的一次设置就覆盖了整个应用。

### 3.2 Sidebar 设计详解

Sidebar 承载了导航、权限过滤、用户信息展示三个职责：

```
Sidebar 结构（264px 宽 / 折叠后 80px）：

顶部：Logo + 应用名称
中部：三组菜单
  第一组「日常运营」
    └── 活动、工作台、商品、发布、审核、任务中心、视频生成
  第二组「经营决策」
    └── 效果预测、A/B 实验、供应商协作
  第三组「分析与治理」
    └── 公平性、风格聚类、指标管理、数据飞轮、审计日志

底部：用户信息下拉
  └── 头像 + 用户名 + 角色标签（如 "管理员"、"运营"）
  └── 退出登录按钮

角色过滤：viewer 角色的用户看不到"生成图片"、"创建实验"、"供应商管理"菜单项
          admin 角色的用户可以看到全部菜单

折叠状态：通过 Zustand store 管理，持久化到 localStorage
          用户刷新页面后折叠状态保持不变
```

### 3.3 三种登录方式

SheLook 支持三种认证模式，通过 `getAuthConfig()` 函数根据环境变量动态选择：

| 方式 | 配置变量 | 使用场景 | OAuth 流程 |
|------|----------|----------|-----------|
| 飞书登录 | `FEISHU_APP_ID` + `FEISHU_APP_SECRET` | 企业飞书组织内使用，用户用飞书扫码或一键登录 | 飞书 OAuth 2.0，授权码回调 → 后端换 access_token |
| 企业 SSO（OIDC） | `OIDC_ISSUER_URL` + `OIDC_CLIENT_ID` | 通用企业 OIDC Provider（Okta、Azure AD、Keycloak） | 标准 OIDC Authorization Code Flow |
| 开发模式 | `ENABLE_AUTH=false` | 本地开发和测试环境，跳过所有 OAuth 流程 | 前端直接 POST `/auth/token` 拿 token，不经过 OAuth 回调 |

开发模式的存在极大地简化了本地调试——开发者不需要配置飞书应用、不需要设置 OIDC Provider、不需要公网回调 URL。一个环境变量 `ENABLE_AUTH=false` 就让整个认证系统"真空运行"。但生产环境必须关闭这个开关——否则任何人都可以通过 POST `/auth/token` 获取任意权限的 token。

---

## 四、React Query v5：把所有"数据"从组件中抽离出来

### 4.1 React Query 解决了什么问题？

React 组件中管理异步数据有三个"地方"：`useState`（数据本身）、`useEffect`（触发数据获取）、手动管理（loading、error、缓存失效）。这三个地方分散在组件中，导致同一个数据源被不同组件重复请求、缓存策略不一致、更新后不知道哪些组件需要重新渲染。

React Query 把这些逻辑全部抽离到一个统一的"服务端状态缓存"层中：

```
不用 React Query 时，组件需要自己管理数据生命周期：
  const [data, setData] = useState(null)         ← 数据存在哪
  const [loading, setLoading] = useState(true)    ← 加载状态
  const [error, setError] = useState(null)        ← 错误状态
  
  useEffect(() => {                                ← 何时获取
    setLoading(true)
    fetchSomething().then(setData).catch(setError)
    .finally(() => setLoading(false))
  }, [])
  // 问题：
  // 1. 组件 A 和组件 B 各自调了 fetchSomething → 重复请求
  // 2. 没有缓存 → 每次组件挂载都重新获取
  // 3. 不知道其他组件的 mutation 是否影响了这个数据 → 缓存不会失效
  // 4. 需要手动为每个 API 调用写相同的 boilerplate

用 React Query 时：
  const { data, isLoading, error } = useQuery({
    queryKey: ["products", { page }],     ← 同一 key 共享缓存
    queryFn: () => api.getProducts({ page }),
    staleTime: 30 * 1000,                  ← 30 秒内视为"新鲜"
    gcTime: 5 * 60 * 1000,                 ← 5 分钟无组件使用则清除
  })
  // 好处：
  // 1. ["products", { page: 1 }] 全局只有一份缓存 → 所有组件共享
  // 2. 30 秒内重复挂载组件 → 不发起新请求（staleTime 保护）
  // 3. mutation 删除商品 → invalidateQueries(["products"]) → 自动重新获取
  // 4. 所有状态管理都在 hook 中，组件只关心渲染
```

React Query 不是"状态管理库"（那是 Redux 和 Zustand 的领域），而是"服务端状态缓存库"。它有两个核心洞察：

**洞察 1：服务端状态不是前端状态。** 商品列表不是前端的——它在数据库中。前端只是"缓存"了它的一小段时间。当后台有其他用户修改了商品数据，前端的缓存应该失效并且重新从服务端获取——这是服务器驱动的状态管理，不是客户端驱动。

**洞察 2：缓存失效比获取新数据更难。** 获取数据容易（一个 `fetch` 调用），但知道"什么时候应该重新获取"是困难的。React Query 通过 `queryKey` 机制解决了这个问题——同一个 key 的所有查询共享同一份缓存，mutation 成功后通过 `invalidateQueries` 标记相关 key 的缓存为过期，框架自动在合适的时机重新获取。

### 4.2 智能轮询：只在必要时刷新

```typescript
// 生图状态查询：轮询频率自适应任务状态
export function useGenerationStatus(imageId: number, pollInterval = 3000) {
  return useQuery({
    queryKey: ["generation", "status", imageId],
    queryFn: () => api.getGenerationStatus(imageId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === "pending" || status === "processing") {
        return pollInterval  // 任务还在跑 → 每 3 秒刷新
      }
      return false  // 终态（succeeded / failed / cancelled）→ 停止轮询
    },
  })
}
```

这个设计的精妙之处在于 `refetchInterval` 的参数：它接收一个函数而不是一个固定数值——函数可以读取当前 query 的最新数据，根据数据的状态决定下一步的轮询频率。这实现了"轮询自适应"：任务活跃时密集查询（3 秒），任务完成后立即停止。不需要开发者在组件中手动判断"如果状态是 completed 就清除 setInterval"——React Query 框架自动处理。

### 4.3 Mutation 缓存失效：写操作触发读更新

React Query 的 mutation 不直接返回数据让开发者手动更新 UI，而是通过"缓存失效"触发被影响的 queries 自动重新获取：

```
旧模式（手动更新、容易出错）：
  删除商品 #42 → API 返回 { success: true }
  → 手动从本地 state.filter(p => p.id !== 42)
  → 忘记更新总计数 state.total -= 1
  → 忘记更新仪表盘的缓存
  → 忘记更新其他引用了商品 #42 的组件

新模式（缓存失效、自动同步）：
  删除商品 #42 → API 返回成功
  → queryClient.invalidateQueries({ queryKey: ["products"] })
  → 所有 queryKey 以 "products" 开头的查询（列表、详情、关联数据）
    被标记为 stale
  → 这些查询对应的组件在重新渲染时自动重新获取
  → 用户看到的是最新的、一致的数据
```

关键在于：**开发者不需要知道"哪些组件引用了商品 #42"**——React Query 框架知道（通过 queryKey 的反向索引），自动标记所有相关缓存为过期。

### 4.4 staleTime 的设计哲学

```typescript
staleTime: 30 * 1000,  // 30 秒
// vs
staleTime: 10 * 1000,  // 商品列表：10 秒（数据变更频繁）
// vs
staleTime: 5 * 60 * 1000,  // 统计数据：5 分钟（数据变更慢）
```

`staleTime` 不是"数据多久过期"，而是"数据多久后应该重新验证"。在 staleTime 内，重复挂载的组件使用缓存，不发起网络请求。数据仍然是"可用的"——只是 React Query 会在后台默默地重新获取以更新缓存。这种"stale-while-revalidate"策略是 HTTP 缓存中常见的模式（如浏览器缓存中的 `max-age` + `must-revalidate`），React Query 将其应用到了组件层。

---

## 五、Zustand：极简到只有一种状态

### 5.1 为什么整个应用只有一个 Zustand 状态？

```typescript
// stores/index.ts
interface UIState {
  sidebarCollapsed: boolean       // 侧边栏是否折叠
  toggleSidebar: () => void       // 切换折叠
  setSidebarCollapsed: (collapsed: boolean) => void
}
```

在 SheLook 中，所有业务数据（商品列表、实验数据、仪表盘统计）都在 React Query 的缓存中。那 Zustand 还剩下什么？

答案是：**纯粹的 UI 状态。** 那些不属于服务端数据、不需要缓存失效、和任何 API 无关的、仅存在于客户端的状态——侧边栏折叠、主题偏好、最后访问的标签页。SheLook 目前只有侧边栏折叠这一个 UI 状态的持久化需求，所以 Zustand 的 store 就只有一个字段。

这不是 Zustand 没用——恰恰相反，这证明了 React Query 承担了大部分状态管理的职责，让 Zustand 只处理它最擅长的那一小部分：**不需要与服务器同步的、跨组件共享的、需要持久化的 UI 状态。**

### 5.2 持久化到 localStorage：一行配置完成

```typescript
const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    }),
    {
      name: "shelook-ui-storage",                 // localStorage key 名称
      storage: createJSONStorage(() => localStorage),  // 存储引擎
    }
  )
)
```

Zustand 的 `persist` 中间件是一个让人"用了就回不去"的特性。不需要手动写 `localStorage.setItem`、`localStorage.getItem` 和 JSON 序列化/反序列化——只需声明要持久化的 store 和 storage 引擎，Zustand 自动处理存储同步。用户折叠侧边栏、关闭浏览器、第二天打开——侧边栏还是折叠状态。

---

## 六、API Client 层：一个 `request` 函数统一一切

### 6.1 统一请求函数的大脑式设计

```typescript
// lib/api.ts

const BASE_URL = "/api"  // Next.js 代理，不暴露后端地址

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  // 1. 认证：从 localStorage 读取 token
  const auth = localStorage.getItem("shelook_auth")
  const token = auth ? JSON.parse(auth).access_token : null
  
  // 2. 头注入：添加 Authorization 和 Content-Type
  const headers = new Headers(options?.headers)
  if (token) {
    headers.set("Authorization", `Bearer ${token}`)
  }
  headers.set("Content-Type", "application/json")
  
  // 3. 发送请求
  const response = await fetch(`${BASE_URL}${url}`, { ...options, headers })
  
  // 4. 统一错误处理
  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem("shelook_auth")  // token 过期 → 清除
      window.location.href = "/login"
    }
    const error = await response.json().catch(() => ({}))
    throw new ApiError(response.status, error.detail || "请求失败")
  }
  
  // 5. 解析 JSON（204 No Content 特殊处理）
  if (response.status === 204) return undefined as T
  return response.json()
}
```

一个 `request` 函数，所有 API 调用共享。不要在每个 API 方法中重复 token 读取、错误处理、JSON 解析。任何一个 API 调用自动获得：
- Token 自动注入（开发者在业务代码中不需要关心认证头）
- 统一的 401 处理（token 过期自动清除并跳转登录页）
- 统一的错误格式（所有错误都是 `ApiError` 类型，前端可以统一展示）

### 6.2 Next.js rewrites：透明代理

```typescript
// next.config.ts
rewrites: async () => [
  {
    source: "/api/:path*",
    destination: `${backendUrl}/api/:path*`,
  },
]
```

这是 Next.js 内置的反向代理能力。前端请求 `/api/products` → Next.js 服务端转发到 `http://backend:8000/api/products` → 后端返回 JSON → Next.js 服务端传回浏览器。浏览器的网络面板中看到的请求地址始终是 `/api/products`——后端服务器地址对客户端完全不可见。

### 6.3 不实现 Refresh Token 的原因

当前 Token 过期策略非常简单：过期了就清除，用户重新登录。没有 refresh token 机制。这不是"偷懒"，而是基于对后台管理系统使用模式的分析：

- 后台管理系统使用频率低且间歇——用户在办公时间打开、完成几个操作、关闭浏览器。不会像社交 App 一样 24 小时持续使用。
- 24 小时 Token 过期时间覆盖了"一天的工作时间不中断"，用户最坏的情况是第二天早上需要重新登录——这在一个 B2B SaaS 工具的体验中完全可接受。
- Refresh Token 带来的复杂性：需要处理并发 refresh 的互斥锁（防止多个请求同时触发 refresh 导致竞态条件），需要处理 refresh token 本身的过期和轮换——这些工程复杂度在 SheLook 的用户规模和使用模式下收益不大。

---

## 七、RBAC 权限守卫：前端是"礼貌"不是"安全"

### 7.1 六种角色的权限矩阵

```typescript
type AppRole = "admin" | "operator" | "reviewer" | "analyst" | "supplier" | "viewer"

const ROLE_PERMISSIONS: Record<AppRole, string[]> = {
  admin:    ["*"],       // 通配：所有权限
  operator: [
    "product:read", "product:write",           // 商品管理
    "generation:run",                          // 发起生图
    "review:read", "review:decide",            // 审核
    "analytics:read",                          // 查看分析
    "experiment:read", "experiment:manage",    // A/B 实验
    "supplier:read", "supplier:write",         // 供应商管理
  ],
  reviewer: ["product:read", "review:read", "review:decide"],
  analyst:  ["product:read", "analytics:read", "experiment:read", "supplier:read"],
  supplier: ["product:read", "supplier:read", "supplier:write"],
  viewer:   ["product:read", "review:read", "analytics:read"],  // 只能看
}
```

### 7.2 前端的角色：UI 层面的"礼貌"

前端权限校验只做一件事：**过滤用户看不到的菜单项。** Viewer 看不到"生成图片"菜单 → 不会点进去 → 不会在 URL 栏尝试 `/publish` → 不会看到一个 403 错误页。

但真正的安全校验在后端。即使 Viewer 手动输入 URL 访问 `/publish`（前端路由不会阻止渲染——因为前端的"隐藏菜单"只是视觉上的），页面加载时会调用后端 API，后端返回 403。前端的权限控制是**体验优化**不是**安全机制**。这个区别是理解前后端权限分离的关键：

```
前端 RBAC（体验层）：
  ✓ 隐藏"生成"按钮 → 用户不觉得混乱，界面干净
  ✓ 过滤菜单 → 用户只看到和已相关的功能
  ✗ 不能作为安全机制——JavaScript 可以被修改，DevTools 可以绕过

后端 RBAC（安全层）：
  ✓ 每个 API 端点验证 JWT scope → 强制权限
  ✓ 无法绕过（除非拿到他人的 token）
  ✗ 不改善用户体验——用户点击按钮后看到 403 体验很糟糕
```

### 7.3 个人额外权限

除了默认的角色权限外，每个用户可以有"个人额外权限"——通过 `TenantMembership.permissions` JSON 数组字段。这解决了"一般规则 + 例外情况"的权限模型：

```
operator 角色默认有 "generation:run" 权限。
但某个 operator 因为正在培训期，暂时不被允许生图。
→ 不给她 "generation:run" 权限，但保留她的 operator 身份。
→ 她可以看到其他 operator 能看到的菜单，但"生成"按钮不可用。

或者：
supplier 角色默认不能查看实验。
但某位 senior supplier 因为在测试新的视觉方案，需要看实验数据。
→ 给她临时加入 "experiment:read" 权限。
→ 不需要把她的角色升级到 analyst（那会给她太多不必要的权限）。
```

---

## 八、组件体系：从错误到加载到布局

### 8.1 三层错误边界

```
全局: global-error.tsx     → 整个应用崩溃时的最终兜底页
路由: error.tsx            → 单个路由页面内部出错时的 fallback
组件: ErrorBoundary 组件    → AppLayout Content 内部的组件错误隔离

每一层的"捕获范围"不同：
  global-error.tsx：捕获根布局的渲染错误（比如 Providers 组件中 throw）
  error.tsx：捕获当前路由的 page.tsx 和其子组件中 throw
  ErrorBoundary：捕获 AppLayout 内部、但不是路由层级的错误
```

高层的错误边界捕获低层的错误。如果 `error.tsx` 自己也出错了，错误冒泡到 `global-error.tsx`。这就保证了"用户永远看不到白屏"——最坏的情况是看到一个"系统似乎出了点问题"的兜底页面，而不是一个空白屏幕。

### 8.2 HydrationGuard：防止 SSR 和客户端的不一致

```typescript
function HydrationGuard({ children }) {
  const [mounted, setMounted] = useState(false)
  
  useEffect(() => {
    setMounted(true)  // 组件挂载（浏览器端）→ 标记为可以渲染
  }, [])
  
  if (!mounted) return null  // SSR 阶段 → 返回空
  return children             // 客户端阶段 → 渲染子组件
}
```

Next.js App Router 默认在服务端做静态渲染。如果一个组件依赖了 `localStorage`、`window`、`document` 等浏览器专属 API，在服务端会报错（`ReferenceError: localStorage is not defined`）。`HydrationGuard` 的解决方案是：在服务端渲染阶段返回 `null`（安全的 null 渲染不会触发水合不匹配），在客户端 `useEffect` 触发后才真正渲染子组件。

---

## 九、Recharts：声明式 React 图表

SheLook 选择 Recharts 而非 ECharts 的核心原因不是"性能更好"或"功能更全"——ECharts 在复杂图表场景下比 Recharts 功能更丰富。选择 Recharts 的原因是**架构匹配度**：

| 维度 | Recharts | ECharts |
|------|----------|---------|
| 渲染方式 | SVG（React 组件树的一部分） | Canvas（独立渲染层，非 React 组件树） |
| 事件系统 | React 的 onClick/onHover | ECharts 自有事件系统（需要 ref 绑定） |
| 声明式 vs 命令式 | 声明式（`<Line data={data} />`） | 命令式（`chart.setOption({...})`） |
| Tree shaking | 原生支持（只打包用到的图表类型） | 有限（核心库较大） |
| 与 React 心智模型的匹配 | 高度匹配（图表 = React 组件） | 中等（需要额外的 wrapper 和 lifecycle 管理） |

在 SheLook 这种中等复杂度的图表需求下（CTR 趋势折线图、品类分布柱状图、市场对比多系列图），Recharts 的声明式 API 让图表组件完全融入 React 的心智模型——图表数据变化时，React 的状态更新自动驱动图表重新渲染。不需要手动监听数据变化、不需要调用 `chart.setOption()`。

---

## 十、WebSocket：双通道保证用户不丢通知

### 10.1 WebSocket hook 的设计

```typescript
function useGenerationWebSocket(imageId: number) {
  const [connectionState, setConnectionState] = useState("connecting")
  
  useEffect(() => {
    const ws = new WebSocket(`ws://${host}/api/generation/ws/${imageId}`)
    
    ws.onopen = () => setConnectionState("connected")
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      // 收到任务完成或失败消息 → 主动关闭 WebSocket
      if (data.status === "completed" || data.status === "failed") {
        ws.close()
      }
    }
    ws.onerror = () => setConnectionState("error")
    ws.onclose = () => setConnectionState("disconnected")
    
    return () => ws.close()  // 组件卸载时清理
  }, [imageId])
}
```

WebSocket 在任务完成时主动关闭是一种资源节俭的设计——不需要为一个已经完成的任务保持 WebSocket 连接。连接关闭后，组件的 `useEffect` cleanup 函数确保不会产生内存泄漏。

### 10.2 双通道冗余的触发逻辑

```
WebSocket（主通道）
  优势：实时推送，零延迟
  风险：防火墙拦截 WebSocket、代理超时断开（Nginx 默认 60 秒）、
        Redis Pub/Sub 消息丢失（订阅者离线）
  
  5 分钟超时无消息 → 自动降级 → 
  
React Query 轮询（兜底通道）
  轮询间隔：3 秒
  轮询条件：status 为 pending 或 processing
  优势：100% 可靠（HTTP 永远不会被防火墙拦截）
  劣势：3 秒延迟、少量无效请求
```

双通道的配合不是"选一个更好的"，而是"两个都上线，确保至少有一个工作"。WebSocket 在 95% 的场景下工作完美（零延迟通知），轮询在剩下的 5% 场景中兜底（慢一点但不会丢结果）。

---

## 十一、类型系统：手动 vs 自动生成的权衡

### 11.1 现状：975 行手动 TypeScript

`types/index.ts` 约 975 行，定义了所有前后端共享的类型：

- `Product`、`ImageScheme`、`GeneratedImage`
- `ReviewResult`、`PredictionResult`、`Experiment`
- `DashboardSummary`、`CTRTrend`、`WorkflowTask`
- `AuditLog`、`TenantContext`、所有 API 请求/响应类型

前端 TypeScript 类型和后端 Pydantic Schema 是手动维护的：

```
后端 Pydantic（Python）:
  class ProductOut(BaseModel):
      id: int
      title: str
      category: str
      price: float
      ...

前端 TypeScript:
  interface Product {
    id: number
    title: string
    category: string
    price: number
    ...
  }
```

两个文件是平行的、独立维护的、没有自动化同步机制。

### 11.2 为什么不自动生成？

FastAPI 自带 OpenAPI JSON 输出（`/openapi.json`），可以用 `openapi-typescript` 从中自动生成 TypeScript 类型。但 SheLook 选择了手动维护，原因是：

1. **项目初期规模小**：975 行手动类型对于一个 17 页面的后台系统来说完全可控。在类型定义的活跃修改期（前 3-6 个月），手动维护比配置一个自动生成工具链要简单。

2. **自动生成的类型不够"友好"**：`openapi-typescript` 生成的类型是机器化的（如 `components["schemas"]["ProductOut"]`），不够语义化，需要额外的手动 aliasing。

3. **自动生成引入了新的运维债务**：需要在 CI 中增加类型生成步骤、需要处理版本不匹配时的 diff、需要监控 OpenAPI schema 的向后兼容性。

### 11.3 技术债务与未来方案

当前的 975 行手动类型是一笔可以量化的**技术债务**。当字段在后端被增删时，前端类型不会自动同步——TypeScript 编译器不会告诉你 `Product.price` 在后端已经被改名为 `Product.unit_price`。运行时才会暴露（API 返回的 JSON 中少了前端期望的字段 → React Query 的 `data.price` 是 `undefined` → 渲染时看到空白单元格）。

未来应该引入 `openapi-typescript` + CI 类型检查，确保：
- 后端 Schema 变更 → OpenAPI JSON 自动更新 → CI 生成新的 TypeScript 类型 → 检查前端是否编译通过
- 编译失败 → 阻止合并（防止前端用旧类型调用新 API）

---

## 十二、Standalone 部署：最小化生产镜像

```typescript
// next.config.ts
output: "standalone"
```

这个配置让 Next.js 在构建时输出一个自包含的 Node.js 应用：

```
.next/standalone/
├── server.js              ← 最小化 Node.js HTTP 服务器
├── node_modules/          ← 只包含运行时真正 import 的依赖
│                           （没有 TypeScript、ESLint、Tailwind JIT 等开发工具）
├── .next/static/          ← JS/CSS/字体/图片等静态资源（可走 CDN）
└── package.json           ← 最小化的依赖声明

Dockerfile：
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

CMD ["node", "server.js"]
```

不需要在生产环境中执行 `npm install`——所有运行时依赖已经在构建阶段被 Next.js 自动分析并复制到 standalone 目录中。生产镜像只有 Node.js 运行时 + 精简后的依赖 + 构建产物。

---

## 十三、本章小结

1. **Next.js 16 被选中不是因为"新技术"**，而是因为它恰好解决了传统 SPA 的三个工程痛点：API 代理隐藏后端地址、路由约定消除手动路由表、standalone 输出简化 Docker 部署。

2. **17 个业务页面统一采用 page.tsx（服务端薄包装）+ Content.tsx（客户端厚逻辑）** 的模式，让 Next.js 能分别对服务端组件和客户端组件做最优的编译优化。

3. **React Query v5 是前端数据层的核心**——不是状态管理库，而是服务端状态缓存库。智能轮询（终态自适应停止）、缓存失效（mutation → invalidateQueries）、staleTime 防重复请求。所有异步数据管理都集中在 hooks 中，组件只关心渲染。

4. **Zustand 只有一种状态**（侧边栏折叠），持久化到 localStorage——因为其他所有状态都被 React Query 覆盖。这不是 Zustand 不好用，恰恰是 React Query 做得太好。

5. **API Client 层的 `request` 函数**统一了 token 注入、401 统一处理、Next.js rewrites 代理。后端服务器地址对浏览器完全不可见。没有 refresh token 机制是故意为之——后台管理系统的使用模式不需要。

6. **RBAC 六种角色在前端是"体验守门"**——隐藏无权限菜单、过滤按钮。真正的安全校验在后端 API 中。前端权限是可以被绕过的（DevTools），但后端的是没法绕过的。

7. **三层错误边界**（global-error → route-error → component error boundary）保证用户永远看不到白屏。最坏情况是一个兜底错误页面。

8. **WebSocket + React Query 轮询双通道**确保前端不会错过任何任务完成通知——WebSocket 是主通道（快），轮询是兜底通道（可靠）。

9. **975 行手动 TypeScript 类型**是一笔可量化的技术债务。未来应引入 `openapi-typescript` 从 FastAPI 的 OpenAPI JSON 自动生成类型。

10. **`output: "standalone"`** 让 Docker 生产镜像不需要 `npm install`——Next.js 自动分析依赖并打包最小化的 Node.js 运行时。

下一章预告：**可观测性与运维**——Prometheus + Grafana 监控体系、OpenTelemetry 链路追踪、审计日志、以及从 Docker Compose 到 Kubernetes 的完整部署架构。
