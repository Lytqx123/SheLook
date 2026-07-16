"use client";

import { Card, Tag } from "antd";
import type { SchemeOut } from "@/types";

interface SchemeCardProps {
  scheme: SchemeOut;
  selected?: boolean;
  onSelect?: (scheme: SchemeOut) => void;
}

// 风格标签中文名，有些是后端直接返回的英文
const STYLE_LABELS: Record<string, string> = {
  natural_light: "自然光",
  studio_lighting: "棚拍",
  soft_light: "柔光",
  warm_light: "暖光",
  street_snap: "街拍",
  indoor_minimal: "极简室内",
  urban: "都市",
  studio: "影棚",
  full_body_standing: "全身站姿",
  dynamic_movement: "动态",
  half_body: "半身",
  full_body: "全身",
  portrait: "人像",
  warm: "暖调",
  cool: "冷调",
  high_saturation: "高饱和",
  low_saturation: "低饱和",
  morandi: "莫兰迪",
};

export default function SchemeCard({ scheme, selected, onSelect }: SchemeCardProps) {
  // 风格标签从 style_tags（JSON 对象）中提取值
  const styleTags = scheme.style_tags
    ? Object.values(scheme.style_tags).filter((v): v is string => typeof v === "string")
    : [];

  return (
    <Card
      hoverable
      className={`h-full transition-all ${selected ? "ring-2 ring-[#2563EB]" : ""}`}
      onClick={() => onSelect?.(scheme)}
      title={
        <div className="flex items-center justify-between">
          <span className="font-semibold text-base">{scheme.scheme_name}</span>
          {scheme.recommendation_score != null && (
            <Tag color="blue" className="ml-2">
              ★ {scheme.recommendation_score.toFixed(1)}
            </Tag>
          )}
        </div>
      }
    >
      <div className="space-y-3">
        {styleTags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {styleTags.map((tag) => (
              <Tag key={tag} className="text-xs">
                {STYLE_LABELS[tag] || tag}
              </Tag>
            ))}
          </div>
        )}
        {scheme.recommendation_reason && (
          <p className="text-sm text-gray-500 leading-relaxed">
            {scheme.recommendation_reason}
          </p>
        )}
        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <span className="text-xs text-gray-400">
            {scheme.reference_images?.length || 0} 张参考图
          </span>
          {selected && (
            <Tag color="success">已选择</Tag>
          )}
        </div>
      </div>
    </Card>
  );
}
