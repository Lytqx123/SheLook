"use client";

import { Progress, Card, Tag } from "antd";
import { cn } from "@/lib/utils";

interface GenerateProgressProps {
  total: number;
  completed: number;
  images?: { id: number; imageUrl: string; score?: number; status: string }[];
  className?: string;
}

export default function GenerateProgress({
  total,
  completed,
  images,
  className,
}: GenerateProgressProps) {
  const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <Card className={cn(className)}>
      <div className="flex items-center justify-between mb-2">
        <h4 className="font-semibold">生成进度</h4>
        <span className="text-sm text-gray-400">
          {completed} / {total}
        </span>
      </div>
      <Progress percent={percentage} showInfo={false} strokeColor="#2563EB" />

      {images && images.length > 0 && (
        <div className="grid grid-cols-3 gap-2 mt-4">
          {images.map((img) => (
            <div
              key={img.id}
              className="relative aspect-square rounded overflow-hidden border border-gray-100"
            >
              <div
                className="w-full h-full bg-gray-100 bg-cover bg-center"
                style={{ backgroundImage: `url(${img.imageUrl})` }}
              />
              {img.score !== undefined && (
                <Tag
                  color={img.score >= 75 ? "green" : "orange"}
                  className="absolute top-1 right-1 text-xs"
                >
                  {img.score}分
                </Tag>
              )}
              {img.status === "pending" && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/30">
                  <div className="h-6 w-6 border-2 border-white border-t-transparent rounded-full animate-spin" />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {percentage === 100 && (
        <p className="text-center text-green-500 mt-3 text-sm">全部图片生成完成</p>
      )}
    </Card>
  );
}
