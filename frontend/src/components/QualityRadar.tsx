"use client";

import { Tag, Card } from "antd";

interface QualityRadarProps {
  overallScore?: number;
  reviewStatus: string;
  dimensions?: Record<string, number>;
  failedDimensions?: string[];
}

/** 评分维度中文标签（v2：匹配新 L2 维度名） */
const DIM_LABELS: Record<string, string> = {
  sharpness: "清晰度",
  lighting_uniformity: "光影均匀",
  color_harmony: "色彩和谐",
  color_richness: "色彩丰富",
  composition_balance: "构图平衡",
  information_density: "信息密度",
  overall_quality: "整体质量",
};

/** 审核状态映射 */
const STATUS_MAP: Record<string, { label: string; color: string }> = {
  auto_approved: { label: "自动通过", color: "green" },
  manual_pending: { label: "待人工审核", color: "orange" },
  rejected: { label: "已驳回", color: "red" },
};

// ====== SVG 雷达图参数 ======
const SVG_W = 280;
const SVG_H = 240;
const CX = 140;
const CY = 115;
const R_MAX = 75;
const GRID_LEVELS = [0.25, 0.5, 0.75, 1.0];

/** 计算第 i 个维度的角度（从正上方开始，顺时针） */
function angleOf(index: number, total: number): number {
  return -Math.PI / 2 + (index * 2 * Math.PI) / total;
}

/** 计算顶点坐标 */
function vertex(index: number, total: number, radius: number) {
  const a = angleOf(index, total);
  return { x: CX + radius * Math.cos(a), y: CY + radius * Math.sin(a) };
}

export default function QualityRadar({
  overallScore,
  reviewStatus,
  dimensions,
  failedDimensions,
}: QualityRadarProps) {
  const status = STATUS_MAP[reviewStatus] || STATUS_MAP.manual_pending;

  const dimEntries = dimensions ? Object.entries(dimensions) : [];
  const dimCount = dimEntries.length;

  // 同心网格多边形路径
  const gridPolygons = GRID_LEVELS.map((level) => {
    const r = R_MAX * level;
    return Array.from({ length: dimCount }, (_, i) => {
      const v = vertex(i, dimCount, r);
      return `${v.x.toFixed(1)},${v.y.toFixed(1)}`;
    }).join(" ");
  });

  // 轴线（从中心到各顶点）
  const axisLines = Array.from({ length: dimCount }, (_, i) => {
    const v = vertex(i, dimCount, R_MAX);
    return { x2: v.x, y2: v.y };
  });

  // 数据多边形顶点
  const dataPoints = dimEntries.map(([, score], i) => {
    const r = R_MAX * (Math.min(100, Math.max(0, score)) / 100);
    return vertex(i, dimCount, r);
  });
  const dataPolygon = dataPoints
    .map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(" ");

  // 轴标签
  const labels = dimEntries.map(([key, score], i) => {
    const v = vertex(i, dimCount, R_MAX + 20);
    const isFailed = failedDimensions?.includes(key);
    const textAnchor: "start" | "middle" | "end" =
      v.x < CX - 5 ? "end" : v.x > CX + 5 ? "start" : "middle";
    return {
      x: v.x,
      y: v.y,
      name: DIM_LABELS[key] || key,
      score,
      isFailed,
      textAnchor,
    };
  });

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold text-lg">质量评估</h4>
        <Tag color={status.color}>{status.label}</Tag>
      </div>

      {/* 综合分大字 */}
      <div className="text-center py-2">
        <span
          className={`text-4xl font-bold ${
            overallScore != null && overallScore >= 75
              ? "text-green-500"
              : overallScore != null && overallScore >= 60
                ? "text-yellow-500"
                : "text-red-500"
          }`}
        >
          {overallScore ?? "—"}
        </span>
        <span className="text-sm text-gray-400 ml-1">分</span>
      </div>

      {/* SVG 雷达图 */}
      {dimCount >= 3 && (
        <div className="flex justify-center mt-2 mb-3">
          <svg
            width={SVG_W}
            height={SVG_H}
            viewBox={`0 0 ${SVG_W} ${SVG_H}`}
          >
            {/* 同心网格 */}
            {gridPolygons.map((pts, idx) => (
              <polygon
                key={`grid-${idx}`}
                points={pts}
                fill="none"
                stroke="#E2E8F0"
                strokeWidth={1}
              />
            ))}

            {/* 轴线 */}
            {axisLines.map((line, idx) => (
              <line
                key={`axis-${idx}`}
                x1={CX}
                y1={CY}
                x2={line.x2}
                y2={line.y2}
                stroke="#E2E8F0"
                strokeWidth={1}
              />
            ))}

            {/* 数据多边形 */}
            {dataPolygon && (
              <polygon
                points={dataPolygon}
                fill="#2563EB"
                fillOpacity={0.2}
                stroke="#2563EB"
                strokeWidth={2}
              />
            )}

            {/* 数据顶点圆点 */}
            {dataPoints.map((p, idx) => {
              const isFailed = failedDimensions?.includes(dimEntries[idx][0]);
              return (
                <circle
                  key={`pt-${idx}`}
                  cx={p.x}
                  cy={p.y}
                  r={3}
                  fill={isFailed ? "#DC2626" : "#2563EB"}
                />
              );
            })}

            {/* 轴标签：维度名 + 分数 */}
            {labels.map((label, idx) => (
              <g key={`lbl-${idx}`}>
                <text
                  x={label.x}
                  y={label.y}
                  textAnchor={label.textAnchor}
                  dominantBaseline="middle"
                  fill={label.isFailed ? "#DC2626" : "#64748B"}
                  style={{ fontSize: 11 }}
                >
                  {label.name}
                </text>
                <text
                  x={label.x}
                  y={label.y + 13}
                  textAnchor={label.textAnchor}
                  dominantBaseline="middle"
                  fill={label.isFailed ? "#DC2626" : "#475569"}
                  style={{ fontSize: 11, fontWeight: 600 }}
                >
                  {label.score.toFixed(0)}
                </text>
              </g>
            ))}
          </svg>
        </div>
      )}

      {/* 维度得分条（补充视图） */}
      {dimensions && Object.keys(dimensions).length > 0 && (
        <div className="space-y-2 mt-3">
          {Object.entries(dimensions).map(([key, score]) => {
            const isFailed = failedDimensions?.includes(key);
            return (
              <div key={key} className="flex items-center gap-2">
                <span className="w-20 text-xs text-gray-500 truncate">
                  {DIM_LABELS[key] || key}
                </span>
                <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      isFailed
                        ? "bg-red-400"
                        : score >= 80
                          ? "bg-green-400"
                          : "bg-yellow-400"
                    }`}
                    style={{ width: `${Math.min(100, score)}%` }}
                  />
                </div>
                <span
                  className={`w-10 text-xs text-right ${
                    isFailed ? "text-red-500 font-semibold" : "text-gray-500"
                  }`}
                >
                  {score.toFixed(0)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
