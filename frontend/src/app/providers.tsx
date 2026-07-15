"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { ConfigProvider, App, theme } from "antd";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30 * 1000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  return (
    <AntdRegistry>
      <ConfigProvider
        theme={{
          algorithm: theme.defaultAlgorithm,
          token: {
            // ===== 品牌色 — 电商办公蓝 =====
            colorPrimary: "#2563EB",
            colorInfo: "#2563EB",
            colorSuccess: "#0F9D75",
            colorWarning: "#D97706",
            colorError: "#DC2626",

            // ===== 圆角 =====
            borderRadius: 10,
            borderRadiusLG: 13,
            borderRadiusSM: 6,
            borderRadiusXS: 4,

            // ===== 背景层级 =====
            colorBgLayout: "#F5F7FB",
            colorBgContainer: "#FFFFFF",
            colorBgElevated: "#FFFFFF",
            colorFillQuaternary: "#F4F7FB",

            // ===== 边框 =====
            colorBorder: "#E5EAF2",
            colorBorderSecondary: "#EDF0F5",

            // ===== 文字层级 =====
            colorText: "#172033",
            colorTextSecondary: "#657084",
            colorTextTertiary: "#8792A4",
            colorTextQuaternary: "#B4BDCB",

            // ===== 字号 =====
            fontSize: 14,
            fontSizeLG: 16,
            fontSizeSM: 13,
            fontSizeXL: 18,
            fontSizeHeading1: 26,
            fontSizeHeading2: 22,
            fontSizeHeading3: 18,
            fontSizeHeading4: 16,
            fontSizeHeading5: 15,

            // ===== 间距 =====
            padding: 16,
            paddingLG: 24,
            paddingSM: 12,
            paddingXS: 8,
            paddingXXS: 4,
            margin: 16,
            marginLG: 24,
            marginMD: 20,
            marginSM: 12,
            marginXS: 8,
            marginXXS: 4,

            // ===== 控件高度 =====
            controlHeight: 40,
            controlHeightLG: 46,
            controlHeightSM: 30,
            controlHeightXS: 24,

            // ===== 阴影 — 分层式，有深度 =====
            boxShadow:
              "0 1px 2px 0 rgba(20, 35, 59, 0.03), 0 8px 20px rgba(20, 35, 59, 0.04)",
            boxShadowSecondary:
              "0 14px 34px -12px rgba(20, 35, 59, 0.14), 0 4px 10px -4px rgba(20, 35, 59, 0.06)",
            boxShadowTertiary: "0 1px 2px 0 rgba(20, 35, 59, 0.025)",

            // ===== 线条 =====
            wireframe: false,
            lineWidth: 1,
            lineWidthBold: 2,

            // ===== 动效 =====
            motionDurationMid: "0.2s",
            motionDurationSlow: "0.3s",

            // ===== 字体 =====
            fontFamily:
              '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
          },
          components: {
            Card: {
              headerBg: "transparent",
              headerFontSize: 16,
              headerFontSizeSM: 15,
              paddingLG: 22,
              boxShadowTertiary: "none",
              actionsBg: "#F5F7FB",
            },
            Menu: {
              itemHeight: 42,
              iconSize: 16,
              itemMarginInline: 0,
              itemBorderRadius: 9,
              subMenuItemBg: "transparent",
              groupTitleColor: "#64748B",
              groupTitleFontSize: 11,
            },
            Table: {
              headerBg: "#F6F8FC",
              headerColor: "#56637A",
              headerSplitColor: "#E5EAF2",
              rowHoverBg: "#F5F8FF",
              cellPaddingBlock: 14,
              cellPaddingInline: 16,
              borderColor: "#E5EAF2",
            },
            Statistic: {
              titleFontSize: 13,
              contentFontSize: 28,
            },
            Tag: {
              borderRadiusSM: 4,
            },
            Button: {
              controlHeight: 36,
              controlHeightLG: 42,
              paddingInline: 18,
              fontWeight: 500,
            },
            Input: {
              controlHeight: 36,
              controlHeightLG: 42,
            },
            Select: {
              controlHeight: 36,
              controlHeightLG: 42,
            },
            Modal: {
              borderRadiusLG: 10,
            },
            Tabs: {
              itemColor: "#657084",
              itemSelectedColor: "#2563EB",
              inkBarColor: "#2563EB",
              horizontalItemPadding: "12px 0",
            },
            Form: {
              itemMarginBottom: 20,
            },
            Descriptions: {
              titleMarginBottom: 16,
            },
          },
        }}
      >
        <QueryClientProvider client={queryClient}>
          <App>{children}</App>
          {process.env.NODE_ENV === "development" && (
            <ReactQueryDevtools initialIsOpen={false} />
          )}
        </QueryClientProvider>
      </ConfigProvider>
    </AntdRegistry>
  );
}
