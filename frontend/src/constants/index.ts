// 共享常量，免得每个文件自己写

// 市场选项
export const MARKET_OPTIONS = [
  { value: "us", label: "美国" },
  { value: "eu", label: "欧洲" },
  { value: "me", label: "中东" },
  { value: "seasia", label: "东南亚" },
] as const;

// 品类选项
export const CATEGORY_OPTIONS = [
  { value: "dress", label: "连衣裙" },
  { value: "shoes", label: "鞋履" },
  { value: "tops", label: "上衣" },
  { value: "bottoms", label: "裤装" },
  { value: "outerwear", label: "外套" },
  { value: "accessories", label: "配饰" },
  { value: "bags", label: "箱包" },
  { value: "lingerie", label: "内衣" },
  { value: "sportswear", label: "运动服" },
  { value: "kids", label: "童装" },
] as const;

// Ant Design Select格式的
export const MARKET_OPTIONS_SELECT: { value: string; label: string }[] = [
  { value: "us", label: "美国" },
  { value: "eu", label: "欧洲" },
  { value: "me", label: "中东" },
  { value: "seasia", label: "东南亚" },
];

export const CATEGORY_OPTIONS_SELECT: { value: string; label: string }[] = [
  { value: "dress", label: "连衣裙" },
  { value: "shoes", label: "鞋履" },
  { value: "tops", label: "上衣" },
  { value: "bottoms", label: "裤装" },
  { value: "outerwear", label: "外套" },
  { value: "accessories", label: "配饰" },
  { value: "bags", label: "箱包" },
  { value: "lingerie", label: "内衣" },
  { value: "sportswear", label: "运动服" },
  { value: "kids", label: "童装" },
];

// L1 合规维度
export const L1_DIM_LABELS: Record<string, string> = {
  resolution: "分辨率",
  aspect_ratio: "尺寸比例",
  file_size: "文件大小",
  text_match: "图文匹配",
  file_read: "文件读取",
};

// L2 质量维度（v2）
export const L2_DIM_OPTIONS = [
  { label: "清晰度", value: "sharpness" },
  { label: "光影均匀度", value: "lighting_uniformity" },
  { label: "色彩和谐度", value: "color_harmony" },
  { label: "构图平衡", value: "composition_balance" },
  { label: "信息密度", value: "information_density" },
] as const;

// L3 审美维度
export const L3_LABELS: Record<string, string> = {
  aesthetic_score: "美学评分",
  composition: "构图",
  color_harmony: "色彩和谐",
  lighting_depth: "光影层次",
};

// 审核状态
export const REVIEW_STATUS_MAP: Record<string, { color: string; label: string }> = {
  auto_approved: { color: "green", label: "自动通过" },
  manual_pending: { color: "orange", label: "待人工" },
  rejected: { color: "red", label: "已驳回" },
};

// 视频风格
export const VIDEO_STYLE_OPTIONS = [
  { value: "product_showcase", label: "360° 产品展示" },
  { value: "lifestyle", label: "生活场景" },
  { value: "unboxing", label: "开箱演示" },
] as const;

// 视频分辨率
export const VIDEO_RESOLUTION_OPTIONS = [
  { value: "720p", label: "720p" },
  { value: "1080p", label: "1080p" },
  { value: "4k", label: "4K" },
] as const;

// 聚类算法
export const CLUSTERING_ALGORITHM_OPTIONS = [
  { value: "kmeans", label: "K-Means（自动 K 值）" },
  { value: "hdbscan", label: "HDBSCAN（密度聚类）" },
] as const;

// 审计操作类型
export const AUDIT_OPERATION_OPTIONS = [
  { value: "generate", label: "图片生成" },
  { value: "video_generate", label: "视频生成" },
  { value: "auto_review", label: "AI 自动审核" },
  { value: "evaluate", label: "质量评估" },
  { value: "review", label: "人工审核" },
  { value: "export", label: "导出操作" },
] as const;

// 实验状态下拉
export const EXPERIMENT_STATUS_OPTIONS = [
  { value: "running", label: "运行中" },
  { value: "stopped", label: "已停止" },
  { value: "completed", label: "已完成" },
] as const;

// 肤色标签
export const SKIN_TONE_LABELS: Record<string, string> = {
  light: "浅肤色",
  medium: "中等肤色",
  dark: "深肤色",
  no_person: "无人像",
};
