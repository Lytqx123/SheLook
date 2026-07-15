"use client";

import React from "react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  extra?: React.ReactNode;
}

/**
 * 统一页头组件 —— 极简、留白充足、企业级 B2B 风格
 * 替代各页面自行用 Card 包裹的标题栏
 */
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
