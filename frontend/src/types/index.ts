// TypeScript类型定义，跟后端Pydantic Schema对齐的

// 商品

export interface ProductCreate {
  sku_code: string;
  title: string;
  category: string;
  price_range?: string;
  target_markets?: string[];
  supplier_id?: string;
  image_raw_url?: string;
}

export interface SchemeOut {
  id: number;
  scheme_name: string;
  style_tags?: Record<string, unknown>;
  reference_images?: string[];
  recommendation_reason?: string;
  recommendation_score?: number;
  created_at?: string;
}

export interface Product {
  id: number;
  sku_code: string;
  title: string;
  category: string;
  price_range?: string;
  target_markets?: string[];
  supplier_id?: string;
  image_raw_url?: string;
  status: "draft" | "published" | "archived";
  schemes: SchemeOut[];
  created_at?: string;
  updated_at?: string;
}

export interface ProductList {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
}

// 视觉方案

export interface SchemeRecommendRequest {
  image_url: string;
  top_k?: number;
}

export interface SchemeRecommendOut {
  schemes: { product_id: number; similarity: number; schemes: SchemeOut[] }[];
  source: string;
}

// 三维度融合推荐

export interface SchemeFusionRecommendRequest {
  category: string;
  market?: string;
  top_k?: number;
}

export type FusionDimension = "same_category" | "cross_category" | "market";

export interface FusionRecommendation {
  scheme_name: string;
  style_tags?: Record<string, unknown>;
  recommendation_score: number;
  dimensions: FusionDimension[];
  reason: string;
  metrics: {
    avg_ctr?: number;
    total_impressions?: number;
    category_count?: number;
    avg_return_rate?: number;
  };
}

export interface SchemeFusionRecommendOut {
  recommendations: FusionRecommendation[];
  weights: Record<FusionDimension, number>;
  source: string;
}

// 质检分数结构

export interface L1CheckItem {
  dimension: string;
  requirement: string;
  actual: string;
  passed: boolean;
}

export interface L1Compliance {
  passed: boolean;
  checks: L1CheckItem[];
}

export interface L2Quality {
  overall_score: number;
  dimensions: {
    sharpness: number;
    lighting_uniformity: number;
    color_harmony: number;
    composition_balance: number;
    information_density: number;
    // 向后兼容旧字段名
    color_richness?: number;
    overall_quality?: number;
  };
  verdict: string;
}

export interface L3Aesthetic {
  aesthetic_score: number;
  composition: number;
  color_harmony: number;
  lighting_depth: number;
}

export interface QualityScores {
  l1?: L1Compliance;
  l2?: L2Quality;
  l3?: L3Aesthetic;
}

// 图片生成

export interface GenerateRequest {
  scheme_id: number;
  market_variant?: string;
  params?: Record<string, unknown>;
}

export interface GenerateResponse {
  task_id: string;
  image_id: number;
  status: string;
}

export interface GenerationStatus {
  image_id: number;
  task_id?: string;
  status: string;
  image_url?: string;
  error_message?: string;
  overall_score?: number;
  review_status?: string;
  quality_scores?: QualityScores;
  generation_params?: Record<string, unknown>;
  c2pa_manifest?: string;
}

// 审核

export interface ReviewRequest {
  action: "approved" | "rejected";
  reviewer_id?: string;
  reason?: string;
  problem_dimensions?: Record<string, unknown>;
  notes?: string;
}

export interface ReviewResponse {
  record_id: number;
  image_id: number;
  action: string;
  reason?: string;
  problem_dimensions: Record<string, unknown>;
  created_at?: string;
}

export interface ReviewQueueItem {
  id: number;
  image_url: string;
  market_variant?: string;
  overall_score?: number;
  review_status: string;
  created_at?: string;
  quality_scores?: QualityScores;
  generation_params?: Record<string, unknown>;
  c2pa_manifest?: string;
  reviewer_notes?: string;
}

export interface ReviewQueue {
  items: ReviewQueueItem[];
  total: number;
  page: number;
  page_size: number;
}

// AI 自动审核

export interface AutoReviewResult {
  overall_score: number;
  passed: boolean;
  need_manual_review: boolean;
  dimensions: Record<string, { score: number; severity: string; remark: string }>;
  diagnosis: string;
  suggestions: string[];
  model: string;
}

// 效果预估

export interface PredictionRequest {
  image_id: number;
}

export interface PredictionResponse {
  record_id: number;
  image_id: number;
  predicted_ctr?: number;
  normalized_ctr?: number;
  ctr_confidence_interval?: { lower: number; upper: number };
  predicted_hit_probability?: number;
  return_risk?: Record<string, unknown>;
  return_risk_level?: "low" | "medium" | "high";
  return_risk_probability?: number;
  return_risk_source?: "model" | "heuristic";
  compliance?: Record<string, unknown>;
  predicted_at?: string;
}

export interface PredictionHistoryItem {
  id: number;
  predicted_ctr?: number;
  ctr_confidence_interval?: { lower: number; upper: number };
  predicted_hit_probability?: number;
  return_risk_level?: "low" | "medium" | "high";
  predicted_at?: string;
}

// A/B 实验

export interface ExperimentCreateRequest {
  product_id: number;
  variant_a_image_id: number;
  variant_b_image_id: number;
  traffic_ratio: number;
}

export interface Experiment {
  id: number;
  product_id: number;
  variant_a_image_id: number;
  variant_b_image_id: number;
  traffic_ratio: number;
  status: "running" | "stopped" | "completed";
  start_date?: string;
  end_date?: string;
  result_ctr_a?: number;
  result_ctr_b?: number;
  p_value?: number;
  winner_image_id?: number;
  created_at?: string;
}

export interface ExperimentList {
  items: Experiment[];
  total: number;
  page: number;
  page_size: number;
}

export type BreakdownDimension = "market" | "category" | "date";

export interface BreakdownSlice {
  dimension_value: string;
  variant_a: { impressions: number; clicks: number; ctr: number };
  variant_b: { impressions: number; clicks: number; ctr: number };
  lift_pct: number;
  direction: "positive" | "negative" | "neutral";
  p_value: number;
  is_significant: boolean;
}

export interface ExperimentBreakdown {
  experiment_id: number;
  dimension: BreakdownDimension;
  breakdown: BreakdownSlice[];
}

export interface AutoExperimentSummary {
  total_experiments: number;
  running: number;
  completed: number;
  avg_traffic_ratio: number;
}

export interface AutoExperimentCreateResult {
  scanned_products: number;
  created: number;
  skipped_existing: number;
  skipped_insufficient: number;
}

export interface TrafficUpdateResult {
  experiment_id: number;
  old_ratio: number;
  new_ratio: number;
  method: string;
}

// 数据飞轮

export interface FlywheelSyncResponse {
  status: string;
  days?: number;
  total_samples?: number;
  positive_samples?: number;
  negative_samples?: number;
  neutral_samples?: number;
  high_return_samples?: number;
  ctr_p75?: number;
  ctr_p25?: number;
  note?: string;
}

export interface FlywheelRetrainResponse {
  status: string;
  samples?: number;
  positive_samples?: number;
  negative_samples?: number;
  model_saved?: boolean;
  ctr_mean?: number;
  hit_rate?: number;
  message?: string;
}

// 看板

export interface DashboardSummary {
  total_generated: number;
  total_approved: number;
  approval_rate: number;
  total_impressions: number;
  total_clicks: number;
  avg_ctr: number;
  avg_cvr: number;
  avg_return_rate: number;
  total_revenue: number;
  ctr_vs_baseline_percent?: number | null;
  ctr_baseline?: number;
  ctr_auc?: number | null;
  high_ctr_prediction_share?: number | null;
  manual_review_rate?: number;
  filters: { market?: string; category?: string };
}

export interface CTRTrendData {
  days: number;
  data: { date: string; avg_ctr: number }[];
}

export interface MarketComparisonData {
  markets: { market: string; total_images: number; avg_ctr: number; avg_cvr: number; total_impressions: number }[];
}

export interface StyleInsightData {
  insights: { tag: string; count: number }[];
  total_tags: number;
}

// 审计日志

export interface AuditLogItem {
  id: number;
  request_id: string;
  operation: string;
  product_id: number | null;
  image_id: number | null;
  model_name: string | null;
  c2pa_manifest_present: boolean | null;
  compliance_checks_passed: boolean | null;
  status: string;
  created_at: string | null;
}

export interface AuditLogResponse {
  total: number;
  limit: number;
  offset: number;
  items: AuditLogItem[];
}

export interface AuditTraceItem {
  id: number;
  operation: string;
  image_id: number | null;
  model_name: string | null;
  status: string;
  created_at: string | null;
}

export interface AuditTraceResponse {
  request_id: string;
  total: number;
  items: AuditTraceItem[];
}

// 视频生成

export interface VideoGenerateParams {
  image_url?: string;
  image_id?: number;
  prompt?: string;
  duration?: number;
  resolution?: string;
  style?: string;
}

export interface VideoGenerateResponse {
  video_url: string;
  status: string;
  model: string;
  provider: string;
  duration_ms?: number;
  message?: string;
}

export interface VideoProvider {
  name: string;
  type: string;
  cost_per_second: string;
  max_duration: string;
  max_resolution: string;
  strengths: string[];
  status: string;
  note?: string;
}

export interface VideoProvidersResponse {
  providers: VideoProvider[];
}

// 公平性分析

export interface SkinToneItem {
  label: string;
  count: number;
  percentage: number;
}

export interface FairnessMarketDemographic {
  market: string;
  expected: { light: number; medium: number; dark: number };
  actual: { light: number; medium: number; dark: number };
  deviation: Record<string, number>;
}

export interface FairnessAlert {
  market: string;
  dimension: string;
  deviation: number;
  suggestion: string;
}

export interface SchemeFairnessItem {
  scheme_id: number;
  scheme_name: string;
  skin_tone_distribution: SkinToneItem[];
  is_biased: boolean;
}

// 聚类分析

export type ClusteringAlgorithm = "kmeans" | "hdbscan";

export interface ClusteringRunRequest {
  category?: string;
  market?: string;
  algorithm?: ClusteringAlgorithm;
  n_clusters?: number;
}

export interface ClusterInfo {
  cluster_id: number;
  size: number;
  avg_ctr?: number;
  avg_return_rate?: number;
  top_categories?: string[];
  label?: string;
}

export interface TSNECoordinate {
  x: number;
  y: number;
  cluster_id: number;
  product_id: number;
  title?: string;
}

export interface ClusteringRunResponse {
  algorithm: string;
  n_clusters: number;
  silhouette_score: number | null;
  clusters: ClusterInfo[];
  tsne_coordinates: TSNECoordinate[];
}

// 健康检查

export interface HealthCheck {
  status: string;
  version: string;
  environment: string;
  checks: { database: string };
}

export interface ReadinessCheck {
  status: "ready" | "not_ready";
  checks: Record<string, string>;
}

// 供应商分析报告
export interface DimensionScore {
  name: string;
  display_name: string;
  score: number;
  benchmark: number;
  gap: number;
  weight: number;
}

export interface ImprovementSuggestion {
  dimension: string;
  priority: number;
  title: string;
  description: string;
  expected_improvement: string;
}

export interface BenchmarkInfo {
  category: string;
  sample_count: number;
  top_ctr_threshold: number;
}

export interface SupplierReport {
  report_id: string;
  image_url: string;
  category: string;
  market: string;
  overall_score: number;
  quality_verdict: string;
  l1_passed: boolean;
  l1_details: Record<string, unknown>;
  dimensions: DimensionScore[];
  suggestions: ImprovementSuggestion[];
  benchmark: BenchmarkInfo | null;
  predicted_ctr: number | null;
  normalized_ctr: number | null;
  return_risk_probability: number | null;
}

export interface SupplierReportHistoryItem {
  report_id: string;
  image_url: string;
  category: string;
  market: string;
  overall_score: number;
  quality_verdict: string;
  analyzed_at: string;
}

// 认证

export interface LoginRequest {
  user_id: string;
  username?: string;
  role?: "admin" | "viewer";
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  username: string;
  role: string;
}

export interface AuthConfigResponse {
  auth_enabled: boolean;
  mode: "oidc" | "development";
}

export interface OIDCLoginResponse {
  authorization_url: string;
}

export interface UserResponse {
  user_id: string;
  username: string;
  role: string;
}

// 以图搜图

export interface ImageSearchScheme {
  id: number;
  scheme_name: string;
  style_tags?: string[];
  reference_images?: string[];
  recommendation_reason?: string;
  recommendation_score?: number;
}

export interface ImageSearchResult {
  product_id: number;
  similarity: number;
  title?: string;
  image_url?: string;
  category?: string;
  market_variant?: string;
  scheme_name?: string;
  schemes?: ImageSearchScheme[];
}

export interface ImageSearchResponse {
  results: ImageSearchResult[];
  source: string;
  total: number;
}

// 图文匹配验证

export interface TextMatchRequest {
  image_path: string;
  product_title: string;
  product_description?: string;
  tags?: string[];
}

export interface TextMatchDetails {
  title_similarity: number;
  description_similarity?: number;
  tag_similarities?: Record<string, number>;
}

export interface TextMatchResponse {
  match: boolean;
  similarity_score: number;
  threshold: number;
  product_title: string;
  details: TextMatchDetails;
}

// 九维审美启发式评估

export interface VisionRewardRequest {
  image_path: string;
  dimensions?: string[];
}

export interface PairwiseComparison {
  dimension_a: string;
  score_a: number;
  dimension_b: string;
  score_b: number;
  delta: number;
  preference: string;
}

export interface VisionRewardResponse {
  overall_score: number;
  dimension_scores: Record<string, number>;
  pairwise_comparisons: PairwiseComparison[];
  model_version: string;
}

// 数据指标

export interface MetricsBatchItem {
  image_id: number;
  date: string;
  source_platform?: "manual" | "shopee" | "lazada" | "amazon";
  impressions: number;
  clicks: number;
  ctr?: number;
  cvr?: number;
  add_to_cart_rate?: number;
  return_rate?: number;
  revenue?: number;
}

export interface MetricsBatchRequest {
  items: MetricsBatchItem[];
}

export interface MetricsUpsertResult {
  image_id: number;
  date: string;
  status: "upserted" | "failed";
  error?: string;
}

export interface MetricsBatchResponse {
  total: number;
  upserted: number;
  failed: number;
  results: MetricsUpsertResult[];
}

export interface MetricsStatsResponse {
  total_records: number;
  total_images: number;
  earliest_date?: string;
  latest_date?: string;
  last_import_at?: string;
}

export interface MetricsSyncResponse {
  platform: string;
  status: "success" | "partial" | "failed";
  date_range?: string;
  records_fetched: number;
  records_upserted: number;
  errors: string[];
  message?: string;
}

// 预测模型版本管理

export interface ModelVersionInfo {
  version: string;
  date: string;
  is_current?: boolean;
}

export interface ModelVersionsResponse {
  versions: ModelVersionInfo[];
  current_version?: string;
}

export interface ModelRollbackRequest {
  target_date: string;
}

export interface ModelRollbackResponse {
  success: boolean;
  message?: string;
  target_version?: string;
}

// 审计日志详情

export interface AuditLogDetail {
  id: number;
  request_id: string;
  operation: string;
  product_id: number | null;
  scheme_id: number | null;
  image_id: number | null;
  model_name: string | null;
  prompt_hash: string | null;
  generation_params: Record<string, unknown> | null;
  image_url: string | null;
  c2pa_manifest_present: boolean | null;
  compliance_checks_passed: boolean | null;
  jurisdiction: string | null;
  status: string;
  error_message: string | null;
  duration_ms: number | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string | null;
}
