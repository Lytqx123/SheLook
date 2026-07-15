/**
 * API 客户端 —— 与后端 FastAPI 路由完全对齐
 *
 * 后端路由对照：
 *   /api/products /api/schemes /api/generation /api/review
 *   /api/prediction /api/experiments /api/dashboard /api/flywheel
 *   /api/audit /api/video /api/clustering /api/fairness /api/auth
 */

import type {
  Product, ProductCreate, ProductList,
  SchemeRecommendRequest, SchemeRecommendOut,
  SchemeFusionRecommendRequest, SchemeFusionRecommendOut, SchemeOut,
  GenerateRequest, GenerateResponse, GenerationStatus,
  ReviewRequest, ReviewResponse, ReviewQueue,
  PredictionRequest, PredictionResponse, PredictionHistoryItem,
  Experiment, ExperimentCreateRequest, ExperimentList,
  ExperimentBreakdown, BreakdownDimension,
  AutoExperimentSummary, AutoExperimentCreateResult, TrafficUpdateResult,
  DashboardSummary, CTRTrendData, MarketComparisonData, StyleInsightData,
  FlywheelSyncResponse, FlywheelRetrainResponse,
  AutoReviewResult,
  AuditLogResponse, AuditTraceResponse, AuditLogDetail,
  VideoGenerateParams, VideoGenerateResponse, VideoProvidersResponse,
  ClusteringRunRequest, ClusteringRunResponse,
  SkinToneItem, FairnessMarketDemographic, SchemeFairnessItem,
  SupplierReport, SupplierReportHistoryItem,
  LoginRequest, TokenResponse, UserResponse, AuthConfigResponse, OIDCLoginResponse,
  ImageSearchResponse, TextMatchRequest, TextMatchResponse,
  VisionRewardRequest, VisionRewardResponse,
  MetricsBatchRequest, MetricsBatchResponse, MetricsStatsResponse, MetricsSyncResponse,
  ModelVersionsResponse, ModelRollbackRequest, ModelRollbackResponse,
} from "@/types";

const API_BASE = "/api";

/** 从 localStorage 读取 JWT token（客户端渲染环境下可用） */
function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("shelook_auth");
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed?.access_token ?? null;
  } catch {
    return null;
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options?.headers as Record<string, string>) ?? {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    // 401 时清除本地鉴权信息，触发跳转登录
    if (res.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("shelook_auth");
    }
    throw new Error(error.detail || `HTTP ${res.status}`);
  }
  // 204 No Content 或空 body 时返回空值，避免 JSON 解析报错
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const api = {
  // ====== 商品 CRUD ======
  getProducts: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<ProductList>(`/products${qs}`);
  },
  getProduct: (id: number) => request<Product>(`/products/${id}`),
  createProduct: (body: ProductCreate) =>
    request<Product>("/products", { method: "POST", body: JSON.stringify(body) }),
  updateProduct: (id: number, body: ProductCreate) =>
    request<Product>(`/products/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteProduct: (id: number) =>
    request<void>(`/products/${id}`, { method: "DELETE" }),
  publishProduct: (id: number) =>
    request<Product>(`/products/${id}/publish`, { method: "PATCH" }),

  // ====== 方案推荐 ======
  recommendSchemes: (imageUrl: string, topK = 5) =>
    request<SchemeRecommendOut>("/schemes/recommend", {
      method: "POST",
      body: JSON.stringify({ image_url: imageUrl, top_k: topK }),
    }),
  recommendSchemesFusion: (body: SchemeFusionRecommendRequest) =>
    request<SchemeFusionRecommendOut>("/schemes/recommend-fusion", {
      method: "POST", body: JSON.stringify(body),
    }),

  // ====== 图片生成 ======
  startGeneration: (body: GenerateRequest) =>
    request<GenerateResponse>("/generation", {
      method: "POST", body: JSON.stringify(body),
    }),
  getGenerationStatus: (imageId: number) =>
    request<GenerationStatus>(`/generation/${imageId}/status`),

  // ====== 审核 ======
  getReviewQueue: (page = 1, pageSize = 20, marketVariant?: string) => {
    let qs = `?page=${page}&page_size=${pageSize}`;
    if (marketVariant) qs += `&market_variant=${marketVariant}`;
    return request<ReviewQueue>(`/review/queue${qs}`);
  },
  decideReview: (imageId: number, body: ReviewRequest) =>
    request<ReviewResponse>(`/review/${imageId}/decide`, {
      method: "POST", body: JSON.stringify(body),
    }),
  autoReviewImage: (imageId: number) =>
    request<AutoReviewResult>(`/review/auto-review/${imageId}`, { method: "POST" }),

  // ====== 效果预估 ======
  predictImage: (imageId: number) =>
    request<PredictionResponse>("/prediction", {
      method: "POST",
      body: JSON.stringify({ image_id: imageId } satisfies PredictionRequest),
    }),
  predictByScheme: (schemeId: number) =>
    request<PredictionResponse>(`/prediction/by-scheme/${schemeId}`, { method: "POST" }),
  getPredictionHistory: (imageId: number) =>
    request<{ image_id: number; count: number; items: PredictionHistoryItem[] }>(
      `/prediction/history/${imageId}`
    ),

  // ====== A/B 实验 ======
  listExperiments: (page = 1, pageSize = 20, status?: string) => {
    let qs = `?page=${page}&page_size=${pageSize}`;
    if (status) qs += `&status=${status}`;
    return request<ExperimentList>(`/experiments${qs}`);
  },
  getExperiment: (id: number) => request<Experiment>(`/experiments/${id}`),
  createExperiment: (body: ExperimentCreateRequest) =>
    request<Experiment>("/experiments", { method: "POST", body: JSON.stringify(body) }),
  stopExperiment: (id: number) =>
    request<Experiment>(`/experiments/${id}/stop`, { method: "POST" }),
  getExperimentBreakdown: (id: number, dimension: BreakdownDimension = "date") =>
    request<ExperimentBreakdown>(`/experiments/${id}/breakdown?dimension=${dimension}`),
  triggerAutoCreateExperiments: () =>
    request<AutoExperimentCreateResult>("/experiments/auto/create", { method: "POST" }),
  getAutoExperimentSummary: () =>
    request<AutoExperimentSummary>("/experiments/auto/summary"),
  updateExperimentTraffic: (id: number) =>
    request<TrafficUpdateResult>(`/experiments/${id}/update-traffic`, { method: "POST" }),

  // ====== 数据飞轮 ======
  triggerFlywheelSync: () =>
    request<FlywheelSyncResponse>("/flywheel/sync", { method: "POST" }),
  triggerFlywheelRetrain: () =>
    request<FlywheelRetrainResponse>("/flywheel/retrain", { method: "POST" }),

  // ====== 运营看板 ======
  getDashboardSummary: (params?: { market?: string; category?: string }) => {
    const qs = new URLSearchParams();
    if (params?.market) qs.set("market", params.market);
    if (params?.category) qs.set("category", params.category);
    const qsStr = qs.toString();
    return request<DashboardSummary>(`/dashboard/summary${qsStr ? "?" + qsStr : ""}`);
  },
  getCTRTrend: (days = 30) =>
    request<CTRTrendData>(`/dashboard/ctr_trend?days=${days}`),
  getMarketComparison: () =>
    request<MarketComparisonData>("/dashboard/market_comparison"),
  getStyleInsight: () =>
    request<StyleInsightData>("/dashboard/style_insight"),

  // ====== 审计日志 ======
  getAuditLogs: (params?: {
    request_id?: string; image_id?: number; operation?: string;
    status?: string; start_date?: string; end_date?: string;
    limit?: number; offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null) qs.set(k, String(v));
      });
    }
    const qsStr = qs.toString();
    return request<AuditLogResponse>(`/audit/logs${qsStr ? "?" + qsStr : ""}`);
  },
  getAuditTrace: (requestId: string) =>
    request<AuditTraceResponse>(`/audit/trace/${requestId}`),

  // ====== 视频生成 ======
  generateVideo: (params: VideoGenerateParams) =>
    request<VideoGenerateResponse>("/video/generate", {
      method: "POST", body: JSON.stringify(params),
    }),
  getVideoProviders: () =>
    request<VideoProvidersResponse>("/video/providers"),

  // ====== 公平性分析 ======
  getSkinToneDistribution: (params?: { market?: string; category?: string }) => {
    const qs = new URLSearchParams();
    if (params?.market) qs.set("market", params.market);
    if (params?.category) qs.set("category", params.category);
    const qsStr = qs.toString();
    return request<SkinToneItem[]>(`/fairness/distribution${qsStr ? "?" + qsStr : ""}`);
  },
  getFairnessMarketReport: (market: string) =>
    request<{ markets: FairnessMarketDemographic[] }>(`/fairness/report/${market}`),
  checkSchemeFairness: (schemeId: number) =>
    request<SchemeFairnessItem>(`/fairness/check-scheme/${schemeId}`, { method: "POST" }),

  // ====== 聚类分析 ======
  runClustering: (body: ClusteringRunRequest) =>
    request<ClusteringRunResponse>("/clustering/run", {
      method: "POST", body: JSON.stringify(body),
    }),

  // ====== 平台导出 ======
  getExportPlatforms: () =>
    request<{ platforms: { key: string; label: string; size: string; allow_ai_primary: boolean }[] }>("/generation/platforms"),
  exportImage: (imageId: number, platform: string) =>
    fetch(`${API_BASE}/generation/export?image_id=${imageId}&platform=${platform}`, {
      method: "POST",
      headers: getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {},
    }).then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.blob();
    }),

  // ====== 供应商分析 ======
  analyzeSupplierImage: (params: { image_url: string; category: string; market: string; supplier_id?: string }) =>
    request<SupplierReport>("/supplier/upload-and-analyze", {
      method: "POST", body: JSON.stringify(params),
    }),
  getSupplierReports: (supplierId: string, limit = 20, offset = 0) =>
    request<{ supplier_id: string; total: number; reports: SupplierReportHistoryItem[] }>(
      `/supplier/report/${supplierId}?limit=${limit}&offset=${offset}`
    ),

  // ====== 认证 ======
  login: (body: LoginRequest) =>
    request<TokenResponse>("/auth/token", { method: "POST", body: JSON.stringify(body) }),
  getAuthConfig: () => request<AuthConfigResponse>("/auth/config"),
  beginOIDCLogin: () =>
    request<OIDCLoginResponse>("/auth/login", { method: "POST" }),
  completeOIDCLogin: (code: string, state: string) =>
    request<TokenResponse>("/auth/callback", {
      method: "POST",
      body: JSON.stringify({ code, state }),
    }),
  getCurrentUser: () => request<UserResponse>("/auth/me"),

  // ====== 以图搜图 ======
  searchByImage: (params: { image_url: string; top_k?: number; category?: string; market?: string }) => {
    const qs = new URLSearchParams();
    qs.set("image_url", params.image_url);
    if (params.top_k) qs.set("top_k", String(params.top_k));
    if (params.category) qs.set("category", params.category);
    if (params.market) qs.set("market", params.market);
    return request<ImageSearchResponse>(`/schemes/search-by-image?${qs.toString()}`, { method: "POST" });
  },
  searchByImageUpload: (file: File, top_k = 10, category?: string) => {
    const formData = new FormData();
    formData.append("image_data", file);
    const token = getAuthToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const qs = new URLSearchParams();
    qs.set("top_k", String(top_k));
    if (category) qs.set("category", category);
    return fetch(`${API_BASE}/schemes/search-by-image/upload?${qs.toString()}`, {
      method: "POST",
      headers,
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `HTTP ${res.status}`);
      }
      return res.json() as Promise<ImageSearchResponse>;
    });
  },

  // ====== 图文匹配验证 ======
  checkTextMatch: (body: TextMatchRequest) =>
    request<TextMatchResponse>("/generation/check-text-match", {
      method: "POST", body: JSON.stringify(body),
    }),

  // ====== 九维审美启发式评估 ======
  evaluateAesthetic: (body: VisionRewardRequest) =>
    request<VisionRewardResponse>("/generation/evaluate-aesthetic", {
      method: "POST", body: JSON.stringify(body),
    }),

  // ====== 数据指标 ======
  batchUpsertMetrics: (body: MetricsBatchRequest, apiKey?: string) => {
    const headers: Record<string, string> = {};
    if (apiKey) headers["X-API-Key"] = apiKey;
    return request<MetricsBatchResponse>("/metrics/batch", {
      method: "POST", body: JSON.stringify(body), headers,
    });
  },
  getMetricsStats: () => request<MetricsStatsResponse>("/metrics/stats"),
  syncPlatformMetrics: (platform: string, apiKey?: string, dateFrom?: string, dateTo?: string) => {
    const qs = new URLSearchParams();
    if (dateFrom) qs.set("date_from", dateFrom);
    if (dateTo) qs.set("date_to", dateTo);
    const headers: Record<string, string> = {};
    if (apiKey) headers["X-API-Key"] = apiKey;
    return request<MetricsSyncResponse>(`/metrics/sync/${platform}?${qs.toString()}`, {
      method: "POST", headers,
    });
  },

  // ====== 预测模型版本管理 ======
  getModelVersions: () => request<ModelVersionsResponse>("/prediction/model-versions"),
  rollbackModel: (body: ModelRollbackRequest) =>
    request<ModelRollbackResponse>("/prediction/rollback", {
      method: "POST", body: JSON.stringify(body),
    }),

  // ====== 审计日志详情 ======
  getAuditLogDetail: (logId: number) =>
    request<AuditLogDetail>(`/audit/logs/${logId}`),
};
