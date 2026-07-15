/**
 * TanStack Query Hooks —— 与 lib/api.ts 完全对齐
 */

import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  ProductCreate, GenerateRequest, ReviewRequest, ExperimentCreateRequest,
  SchemeFusionRecommendRequest, BreakdownDimension,
  VideoGenerateParams, ClusteringRunRequest,
  LoginRequest, TextMatchRequest, VisionRewardRequest,
  MetricsBatchRequest, ModelRollbackRequest,
} from "@/types";

// ====== 商品 ======
export function useProducts(page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["products", { page, pageSize }],
    queryFn: () => api.getProducts({ page: String(page), page_size: String(pageSize) }),
  });
}
export function useProduct(id: number) {
  return useQuery({ queryKey: ["product", id], queryFn: () => api.getProduct(id), enabled: id > 0 });
}
export function useCreateProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProductCreate) => api.createProduct(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["products"] }),
  });
}
export function useUpdateProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: ProductCreate }) => api.updateProduct(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["products"] }),
  });
}
export function useDeleteProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteProduct(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["products"] }),
  });
}
export function usePublishProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.publishProduct(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["products"] }),
  });
}

// ====== 方案推荐 ======
export function useRecommendSchemes() {
  return useMutation({
    mutationFn: (params: { imageUrl: string; topK?: number }) =>
      api.recommendSchemes(params.imageUrl, params.topK ?? 5),
  });
}
export function useRecommendSchemesFusion() {
  return useMutation({
    mutationFn: (params: SchemeFusionRecommendRequest) => api.recommendSchemesFusion(params),
  });
}

// ====== 生成任务 ======
export function useStartGeneration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GenerateRequest) => api.startGeneration(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["generation"] }),
  });
}
export function useGenerationStatus(imageId: number, pollInterval = 5000) {
  return useQuery({
    queryKey: ["generation", "status", imageId],
    queryFn: () => api.getGenerationStatus(imageId),
    enabled: imageId > 0,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "processing" ? pollInterval : false;
    },
  });
}

// ====== 审核 ======
export function useReviewQueue(page = 1, pageSize = 20, marketVariant?: string) {
  return useQuery({
    queryKey: ["review-queue", { page, pageSize, marketVariant }],
    queryFn: () => api.getReviewQueue(page, pageSize, marketVariant),
    refetchInterval: 10000,
  });
}
export function useDecideReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ imageId, body }: { imageId: number; body: ReviewRequest }) =>
      api.decideReview(imageId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["review-queue"] }),
  });
}
export function useAutoReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (imageId: number) => api.autoReviewImage(imageId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["review-queue"] }),
  });
}

// ====== 效果预估 ======
export function usePrediction(imageId: number, enabled = true) {
  return useQuery({
    queryKey: ["prediction", imageId],
    queryFn: () => api.predictImage(imageId),
    enabled: enabled && imageId > 0,
  });
}
export function usePredictionHistory(imageId: number) {
  return useQuery({
    queryKey: ["prediction-history", imageId],
    queryFn: () => api.getPredictionHistory(imageId),
    enabled: imageId > 0,
  });
}

// ====== A/B 实验 ======
export function useExperiments(page = 1, pageSize = 20, status?: string) {
  return useQuery({
    queryKey: ["experiments", { page, pageSize, status }],
    queryFn: () => api.listExperiments(page, pageSize, status),
    refetchInterval: 30000,
  });
}
export function useExperiment(id: number) {
  return useQuery({
    queryKey: ["experiment", id],
    queryFn: () => api.getExperiment(id),
    enabled: id > 0,
  });
}
export function useCreateExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ExperimentCreateRequest) => api.createExperiment(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["experiments"] }),
  });
}
export function useStopExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.stopExperiment(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["experiments"] });
      qc.invalidateQueries({ queryKey: ["experiment", id] });
    },
  });
}
export function useExperimentBreakdown(id: number, dimension: BreakdownDimension = "date") {
  return useQuery({
    queryKey: ["experiment-breakdown", id, dimension],
    queryFn: () => api.getExperimentBreakdown(id, dimension),
    enabled: id > 0,
  });
}
export function useTriggerAutoCreateExperiments() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.triggerAutoCreateExperiments(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["experiments"] }),
  });
}
export function useAutoExperimentSummary() {
  return useQuery({
    queryKey: ["auto-experiment-summary"],
    queryFn: () => api.getAutoExperimentSummary(),
  });
}
export function useUpdateExperimentTraffic() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.updateExperimentTraffic(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["experiment", id] });
      qc.invalidateQueries({ queryKey: ["experiments"] });
    },
  });
}

// ====== 数据飞轮 ======
export function useTriggerFlywheelSync() {
  return useMutation({ mutationFn: () => api.triggerFlywheelSync() });
}
export function useTriggerFlywheelRetrain() {
  return useMutation({ mutationFn: () => api.triggerFlywheelRetrain() });
}

// ====== 运营看板 ======
export function useDashboardSummary(params?: { market?: string; category?: string }) {
  return useQuery({
    queryKey: ["dashboard-summary", params],
    queryFn: () => api.getDashboardSummary(params),
    refetchInterval: 60000,
  });
}
export function useCTRTrend(days = 30) {
  return useQuery({
    queryKey: ["ctr-trend", days],
    queryFn: () => api.getCTRTrend(days),
  });
}
export function useMarketComparison() {
  return useQuery({
    queryKey: ["market-comparison"],
    queryFn: api.getMarketComparison,
  });
}
export function useStyleInsight() {
  return useQuery({
    queryKey: ["style-insight"],
    queryFn: api.getStyleInsight,
  });
}

// ====== 审计日志 ======
export function useAuditLogs(params?: {
  request_id?: string; image_id?: number; operation?: string;
  status?: string; start_date?: string; end_date?: string;
  limit?: number; offset?: number;
}) {
  return useQuery({
    queryKey: ["audit-logs", params],
    queryFn: () => api.getAuditLogs(params),
  });
}
export function useAuditTrace(requestId: string) {
  return useQuery({
    queryKey: ["audit-trace", requestId],
    queryFn: () => api.getAuditTrace(requestId),
    enabled: requestId.length > 0,
  });
}

// ====== 视频生成 ======
export function useGenerateVideo() {
  return useMutation({
    mutationFn: (params: VideoGenerateParams) => api.generateVideo(params),
  });
}
export function useVideoProviders() {
  return useQuery({
    queryKey: ["video-providers"],
    queryFn: api.getVideoProviders,
  });
}

// ====== 公平性分析 ======
export function useSkinToneDistribution(params?: { market?: string; category?: string }) {
  return useQuery({
    queryKey: ["skin-tone", params],
    queryFn: () => api.getSkinToneDistribution(params),
  });
}
export function useFairnessMarketReport(market: string) {
  return useQuery({
    queryKey: ["fairness-market-report", market],
    queryFn: () => api.getFairnessMarketReport(market),
    enabled: !!market,
  });
}
export function useCheckSchemeFairness() {
  return useMutation({
    mutationFn: (schemeId: number) => api.checkSchemeFairness(schemeId),
  });
}

// ====== 聚类分析 ======
export function useRunClustering() {
  return useMutation({
    mutationFn: (body: ClusteringRunRequest) => api.runClustering(body),
  });
}

// ====== 平台导出 ======
export function useExportPlatforms() {
  return useQuery({
    queryKey: ["export-platforms"],
    queryFn: () => api.getExportPlatforms(),
    staleTime: Infinity, // 平台规格极少变动
  });
}

export function useExportImage() {
  return useMutation({
    mutationFn: ({ imageId, platform }: { imageId: number; platform: string }) =>
      api.exportImage(imageId, platform),
  });
}

// ====== 认证 ======
export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: LoginRequest) => api.login(body),
    onSuccess: (data) => {
      if (typeof window !== "undefined") {
        localStorage.setItem("shelook_auth", JSON.stringify(data));
      }
      qc.invalidateQueries({ queryKey: ["current-user"] });
    },
  });
}

export function useCurrentUser() {
  return useQuery({
    queryKey: ["current-user"],
    queryFn: () => api.getCurrentUser(),
    enabled: typeof window !== "undefined" && !!localStorage.getItem("shelook_auth"),
    retry: false,
  });
}

// ====== 以图搜图 ======
export function useSearchByImage() {
  return useMutation({
    mutationFn: (params: { image_url: string; top_k?: number; category?: string; market?: string }) =>
      api.searchByImage(params),
  });
}

export function useSearchByImageUpload() {
  return useMutation({
    mutationFn: ({ file, topK, category }: { file: File; topK?: number; category?: string }) =>
      api.searchByImageUpload(file, topK ?? 10, category),
  });
}

// ====== 图文匹配验证 ======
export function useCheckTextMatch() {
  return useMutation({
    mutationFn: (body: TextMatchRequest) => api.checkTextMatch(body),
  });
}

// ====== 九维审美启发式评估 ======
export function useEvaluateAesthetic() {
  return useMutation({
    mutationFn: (body: VisionRewardRequest) => api.evaluateAesthetic(body),
  });
}

// ====== 数据指标 ======
export function useMetricsStats() {
  return useQuery({
    queryKey: ["metrics-stats"],
    queryFn: () => api.getMetricsStats(),
    refetchInterval: 30000,
  });
}

export function useSyncPlatformMetrics() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ platform, apiKey, dateFrom, dateTo }: {
      platform: string; apiKey?: string; dateFrom?: string; dateTo?: string;
    }) => api.syncPlatformMetrics(platform, apiKey, dateFrom, dateTo),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["metrics-stats"] }),
  });
}

export function useBatchUpsertMetrics() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ body, apiKey }: { body: MetricsBatchRequest; apiKey?: string }) =>
      api.batchUpsertMetrics(body, apiKey),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["metrics-stats"] }),
  });
}

// ====== 预测模型版本管理 ======
export function useModelVersions() {
  return useQuery({
    queryKey: ["model-versions"],
    queryFn: () => api.getModelVersions(),
  });
}

export function useRollbackModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ModelRollbackRequest) => api.rollbackModel(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["model-versions"] }),
  });
}

// ====== 审计日志详情 ======
export function useAuditLogDetail(logId: number | null) {
  return useQuery({
    queryKey: ["audit-log-detail", logId],
    queryFn: () => api.getAuditLogDetail(logId!),
    enabled: logId != null && logId > 0,
  });
}

// ====== 供应商历史报告 ======
export function useSupplierReports(supplierId: string, limit = 20, offset = 0) {
  return useQuery({
    queryKey: ["supplier-reports", supplierId, limit, offset],
    queryFn: () => api.getSupplierReports(supplierId, limit, offset),
    enabled: !!supplierId,
  });
}

// ====== WebSocket 生成进度（实时事件驱动）======
export type WsConnectionState = "idle" | "connecting" | "open" | "closed" | "error";

export interface WsGenerationMessage {
  status?: string;
  image_id?: number;
  image_url?: string;
  overall_score?: number;
  [key: string]: unknown;
}

/**
 * 实时 WebSocket 生成进度 hook。
 * 作为轮询的补充：收到 completed 消息时立即触发 query 刷新，降低完成感知延迟。
 * WebSocket 失败时静默降级为轮询模式。
 */
export function useGenerationWebSocket(imageId: number) {
  const qc = useQueryClient();
  const [connectionState, setConnectionState] = useState<WsConnectionState>("idle");
  const [lastMessage, setLastMessage] = useState<WsGenerationMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || imageId <= 0) {
      return;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/generation/ws/${imageId}`;

    setConnectionState("connecting");
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setConnectionState("open");

    ws.onmessage = (event) => {
      try {
        const data: WsGenerationMessage = JSON.parse(event.data);
        setLastMessage(data);
        // 收到任意消息即触发轮询查询刷新，确保数据最新
        qc.invalidateQueries({ queryKey: ["generation", "status", imageId] });
        if (data.status === "completed" || data.status === "failed") {
          ws.close();
        }
      } catch {
        // 忽略解析异常
      }
    };

    ws.onerror = () => setConnectionState("error");

    ws.onclose = () => setConnectionState("closed");

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [imageId, qc]);

  return { connectionState, lastMessage };
}
