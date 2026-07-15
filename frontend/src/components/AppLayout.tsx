"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  UploadOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  DashboardOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ThunderboltOutlined,
  VideoCameraOutlined,
  AuditOutlined,
  ClusterOutlined,
  GlobalOutlined,
  SyncOutlined,
  ShopOutlined,
  DatabaseOutlined,
  UserOutlined,
  LogoutOutlined,
  MenuOutlined,
} from "@ant-design/icons";
import type { MenuProps } from "antd";
import { Avatar, Badge, Button, Drawer, Dropdown, Layout, Menu, Spin, Tag } from "antd";
import Image from "next/image";
import React, { useEffect, useMemo, useState } from "react";
import { useUIStore } from "@/stores";
import { useCurrentUser } from "@/hooks";
import ErrorBoundary from "./ErrorBoundary";

const { Sider, Header, Content } = Layout;

const menuItems: MenuProps["items"] = [
  {
    type: "group",
    label: "商品工作台",
    children: [
      { key: "/publish", icon: <UploadOutlined />, label: "发品工作台" },
      { key: "/prediction", icon: <ThunderboltOutlined />, label: "预测决策" },
      { key: "/products", icon: <ShopOutlined />, label: "商品管理" },
    ],
  },
  {
    type: "group",
    label: "质量与审核",
    children: [
      { key: "/review", icon: <CheckCircleOutlined />, label: "审核工作台" },
      { key: "/fairness", icon: <GlobalOutlined />, label: "公平性分析" },
      { key: "/supplier", icon: <ShopOutlined />, label: "供应商分析" },
    ],
  },
  {
    type: "group",
    label: "增长实验",
    children: [
      { key: "/experiments", icon: <ExperimentOutlined />, label: "A/B 实验中心" },
      { key: "/flywheel", icon: <SyncOutlined />, label: "数据飞轮" },
    ],
  },
  {
    type: "group",
    label: "经营洞察",
    children: [
      { key: "/dashboard", icon: <DashboardOutlined />, label: "数据看板" },
      { key: "/clustering", icon: <ClusterOutlined />, label: "聚类分析" },
      { key: "/metrics", icon: <DatabaseOutlined />, label: "指标数据管理" },
    ],
  },
  {
    type: "group",
    label: "系统设置",
    children: [
      { key: "/video-generate", icon: <VideoCameraOutlined />, label: "视频生成" },
      { key: "/audit-logs", icon: <AuditOutlined />, label: "审计日志" },
    ],
  },
];

const pageTitles: Record<string, string> = {
  "/publish": "发品工作台",
  "/prediction": "预测决策",
  "/products": "商品管理",
  "/review": "审核工作台",
  "/fairness": "公平性分析",
  "/supplier": "供应商分析",
  "/experiments": "A/B 实验中心",
  "/flywheel": "数据飞轮",
  "/dashboard": "数据看板",
  "/clustering": "聚类分析",
  "/metrics": "指标数据管理",
  "/video-generate": "视频生成",
  "/audit-logs": "审计日志",
};

function UserProfile({ collapsed = false }: { collapsed?: boolean }) {
  const router = useRouter();
  const { data: user, isLoading } = useCurrentUser();

  const handleLogout = () => {
    localStorage.removeItem("shelook_auth");
    router.replace("/login");
  };

  const userMenuItems: MenuProps["items"] = [
    {
      key: "user-info",
      disabled: true,
      label: (
        <div style={{ padding: "4px 0" }}>
          <div style={{ fontWeight: 650 }}>{user?.username ?? "当前用户"}</div>
          <div style={{ fontSize: 12, color: "#7A8497" }}>{user?.user_id ?? "会话加载中"}</div>
        </div>
      ),
    },
    { type: "divider" },
    { key: "logout", icon: <LogoutOutlined />, label: "退出登录", onClick: handleLogout },
  ];

  return (
    <Dropdown menu={{ items: userMenuItems }} placement="topLeft" trigger={["click"]}>
      <button type="button" className={`office-user ${collapsed ? "office-user--collapsed" : ""}`}>
        {isLoading ? <Spin size="small" /> : <Avatar size={34} icon={<UserOutlined />} />}
        {!collapsed && (
          <span className="office-user__meta">
            <span className="office-user__name">{user?.username ?? "当前用户"}</span>
            <Tag variant="filled" color={user?.role === "admin" ? "blue" : "default"}>
              {user?.role === "admin" ? "管理员" : "协作成员"}
            </Tag>
          </span>
        )}
      </button>
    </Dropdown>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { sidebarCollapsed, toggleSidebar } = useUIStore();
  const [mounted, setMounted] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    setMounted(true);
    const media = window.matchMedia("(max-width: 767px)");
    const syncViewport = () => setIsMobile(media.matches);
    syncViewport();
    media.addEventListener("change", syncViewport);
    return () => media.removeEventListener("change", syncViewport);
  }, []);

  useEffect(() => {
    if (mounted && !localStorage.getItem("shelook_auth") && pathname !== "/login") {
      router.replace("/login");
    }
  }, [mounted, pathname, router]);

  const selectedKey = `/${pathname?.split("/")[1] || "publish"}`;
  const currentTitle = useMemo(
    () => pageTitles[selectedKey] ?? "运营工作台",
    [selectedKey],
  );
  const collapsed = sidebarCollapsed;
  const siderWidth = collapsed ? 80 : 264;

  const navigate: MenuProps["onClick"] = ({ key }) => {
    setMobileMenuOpen(false);
    router.push(key);
  };

  if (!mounted) return null;

  return (
    <Layout className="office-shell">
      {!isMobile && (
        <Sider
          width={siderWidth}
          collapsedWidth={80}
          collapsed={collapsed}
          theme="dark"
          className="office-sider"
          style={{ width: siderWidth }}
        >
          <div className="office-brand">
            <Image
              src={collapsed ? "/logo-icon.svg" : "/logo.svg"}
              alt="SheLook"
              width={collapsed ? 32 : 119}
              height={collapsed ? 32 : 34}
              priority
            />
            <Button
              type="text"
              aria-label={collapsed ? "展开导航" : "收起导航"}
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={toggleSidebar}
              className="office-collapse-button"
            />
          </div>

          <div className="office-nav-label">商品视觉运营</div>
          <Menu
            mode="inline"
            theme="dark"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onClick={navigate}
            className="office-menu"
          />

          <div className="office-sider-footer">
            <UserProfile collapsed={collapsed} />
          </div>
        </Sider>
      )}

      <Layout
        style={{
          marginLeft: isMobile ? 0 : siderWidth,
          minWidth: 0,
          transition: "margin-left 180ms ease",
        }}
      >
        <Header className="office-header">
          <div className="office-header__context">
            {isMobile && (
              <Button
                type="text"
                icon={<MenuOutlined />}
                aria-label="打开导航"
                onClick={() => setMobileMenuOpen(true)}
              />
            )}
            <div>
              <span className="office-header__eyebrow">SHELOOK · 视觉运营中心</span>
              <strong>{currentTitle}</strong>
            </div>
          </div>
          <div className="office-header__status">
            <Badge status="processing" text="服务已连接" />
            {!isMobile && <span>数据与业务链路实时同步</span>}
          </div>
        </Header>

        <Content className="office-content">
          <ErrorBoundary>{children}</ErrorBoundary>
        </Content>
      </Layout>

      <Drawer
        title={<Image src="/logo.svg" alt="SheLook" width={112} height={32} />}
        placement="left"
        size="default"
        open={isMobile && mobileMenuOpen}
        onClose={() => setMobileMenuOpen(false)}
        styles={{ body: { padding: "8px 12px 18px" }, wrapper: { width: 304 } }}
      >
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={navigate}
          className="office-mobile-menu"
        />
        <div className="office-mobile-user">
          <UserProfile />
        </div>
      </Drawer>
    </Layout>
  );
}
