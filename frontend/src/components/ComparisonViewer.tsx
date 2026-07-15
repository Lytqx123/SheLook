"use client";

import { useState } from "react";
import { Button, Tag, Card } from "antd";
import { cn } from "@/lib/utils";

interface ComparisonItem {
  id: number;
  imageUrl: string;
  score?: number;
  label: string;
  market?: string;
  selected?: boolean;
  status?: string;
}

interface ComparisonViewerProps {
  images: ComparisonItem[];
  maxSelect?: number;
  onSelect?: (selectedIds: number[]) => void;
  onApproveAll?: () => void;
  className?: string;
}

export default function ComparisonViewer({
  images,
  maxSelect = 3,
  onSelect,
  onApproveAll,
  className,
}: ComparisonViewerProps) {
  const [selected, setSelected] = useState<Set<number>>(
    new Set(images.filter((i) => i.selected).map((i) => i.id))
  );

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < maxSelect) {
        next.add(id);
      }
      onSelect?.(Array.from(next));
      return next;
    });
  };

  return (
    <Card className={cn(className)}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold text-lg">生成结果对比</h4>
        <div className="flex gap-2 items-center">
          <span className="text-sm text-gray-400">
            已选 {selected.size}/{maxSelect}
          </span>
          <Button size="small" onClick={onApproveAll}>
            全部采纳
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {images.map((img) => (
          <div
            key={img.id}
            className={cn(
              "relative rounded-lg overflow-hidden border-2 cursor-pointer transition-all",
              selected.has(img.id)
                ? "border-blue-500 shadow-md scale-[1.02]"
                : "border-gray-200 hover:border-gray-300"
            )}
            onClick={() => toggleSelect(img.id)}
          >
            <div
              className="aspect-square bg-gray-100 bg-cover bg-center"
              style={{ backgroundImage: `url(${img.imageUrl})` }}
            />
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-2">
              <p className="text-white text-xs truncate">{img.label}</p>
              <div className="flex items-center gap-1 mt-1">
                {img.score !== undefined && (
                  <Tag color={img.score >= 75 ? "green" : "orange"} className="text-[10px] leading-none">
                    {img.score}分
                  </Tag>
                )}
                {img.market && (
                  <span className="text-[10px] text-gray-300">
                    {img.market.toUpperCase()}
                  </span>
                )}
              </div>
            </div>
            {selected.has(img.id) && (
              <div className="absolute top-2 right-2 bg-blue-500 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs font-bold">
                ✓
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
