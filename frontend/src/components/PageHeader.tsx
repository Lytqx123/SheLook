"use client";

import React from "react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  extra?: React.ReactNode;
}

// 统一页面顶部，免得每个页面自己写一遍
export default function PageHeader({ title, subtitle, extra }: PageHeaderProps) {
  return (
    <div className="office-page-header">
      <div>
        <div className="office-page-header__eyebrow">商品视觉运营 / {title}</div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {extra && <div className="office-page-header__extra">{extra}</div>}
    </div>
  );
}
