"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  AuditOutlined,
  ApiOutlined,
  CheckCircleOutlined,
  ClusterOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FlagOutlined,
  GlobalOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuOutlined,
  MenuUnfoldOutlined,
  ShopOutlined,
  SettingOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  UploadOutlined,
  UserOutlined,
  VideoCameraOutlined,
  ClockCircleOutlined,
} from "@ant-design/icons";
import type { MenuProps } from "antd";
import { Avatar, Badge, Button, Drawer, Dropdown, Layout, Menu, Spin, Tag } from "antd";
import Image from "next/image";
import React, { useEffect, useMemo, useState } from "react";
import { getAppRole, getRoleLabel, hasAnyPermission, type AppRole } from "@/lib/access";
import { useUIStore } from "@/stores";
import { useCurrentUser, useTenantContext } from "@/hooks";
import type { TenantContext, UserResponse } from "@/types";
import ErrorBoundary from "./ErrorBoundary";

const { Sider, Header, Content } = Layout;

type NavigationIdentity = UserResponse | TenantContext | undefined;

type NavigationItem = {
  key: string;
  icon: React.ReactNode;
  label: string;
  permissions?: string[];
  roles?: AppRole[];
};

type NavigationGroup = {
  label: string;
  children: NavigationItem[];
};

const navigationGroups: NavigationGroup[] = [
  {
    label: "日常运营",
    children: [
      { key: "/campaigns", icon: <FlagOutlined />, label: "运营活动", roles: ["admin", "operator", "analyst", "viewer"] },
      { key: "/dashboard", icon: <DashboardOutlined />, label: "运营首页" },
      { key: "/products", icon: <ShopOutlined />, label: "商品管理", permissions: ["product:read"] },
      { key: "/publish", icon: <UploadOutlined />, label: "发品工作台", permissions: ["generation:run"] },
      { key: "/review", icon: <CheckCircleOutlined />, label: "审核工作台", permissions: ["review:read"] },
      { key: "/tasks", icon: <ClockCircleOutlined />, label: "任务中心", permissions: ["generation:run", "workflow:manage"] },
      { key: "/video-generate", icon: <VideoCameraOutlined />, label: "视频生成", permissions: ["generation:run"] },
    ],
  },
  {
    label: "经营决策",
    children: [
      { key: "/prediction", icon: <ThunderboltOutlined />, label: "预测决策", permissions: ["analytics:read"] },
      { key: "/experiments", icon: <ExperimentOutlined />, label: "A/B 实验", permissions: ["experiment:read"] },
      { key: "/supplier", icon: <ShopOutlined />, label: "供应商协同", permissions: ["supplier:read"] },
    ],
  },
  {
    label: "分析与治理",
    children: [
      { key: "/fairness", icon: <GlobalOutlined />, label: "公平性分析", permissions: ["analytics:read"], roles: ["admin", "operator", "analyst"] },
      { key: "/clustering", icon: <ClusterOutlined />, label: "聚类分析", permissions: ["analytics:read"], roles: ["admin", "operator", "analyst"] },
      { key: "/metrics", icon: <DatabaseOutlined />, label: "指标与模型", roles: ["admin"] },
      { key: "/flywheel", icon: <SyncOutlined />, label: "数据飞轮", permissions: ["model:manage"] },
      { key: "/audit-logs", icon: <AuditOutlined />, label: "审计日志", permissions: ["audit:read"] },
      { key: "/integrations", icon: <ApiOutlined />, label: "系统集成", roles: ["admin"] },
      { key: "/settings", icon: <SettingOutlined />, label: "运行时配置", roles: ["admin"] },
    ],
  },
];

const pageTitles: Record<string, string> = {
  "/campaigns": "运营活动",
  "/dashboard": "运营首页",
  "/publish": "发品工作台",
  "/prediction": "预测决策",
  "/products": "商品管理",
  "/tasks": "任务中心",
  "/review": "审核工作台",
  "/fairness": "公平性分析",
  "/supplier": "供应商协同",
  "/experiments": "A/B 实验",
  "/flywheel": "数据飞轮",
  "/clustering": "聚类分析",
  "/metrics": "指标与模型",
  "/video-generate": "视频生成",
  "/audit-logs": "审计日志",
  "/integrations": "系统集成",
  "/settings": "运行时配置",
};

function canShowNavigationItem(item: NavigationItem, identity: NavigationIdentity): boolean {
  const role = getAppRole(identity);
  if (item.roles && !item.roles.includes(role)) return false;
  return !item.permissions || hasAnyPermission(identity, item.permissions);
}

function buildMenuItems(identity: NavigationIdentity): MenuProps["items"] {
  return navigationGroups
    .map((group) => ({
      type: "group" as const,
      label: group.label,
      children: group.children
        .filter((item) => canShowNavigationItem(item, identity))
        .map(({ key, icon, label }) => ({ key, icon, label })),
    }))
    .filter((group) => group.children.length > 0);
}

function UserProfile({ user, isLoading, collapsed = false }: { user?: UserResponse; isLoading: boolean; collapsed?: boolean }) {
  const router = useRouter();

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
              {getRoleLabel(user)}
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
  const { data: tenant } = useTenantContext();
  const { data: user, isLoading: userLoading } = useCurrentUser();
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

  const selectedKey = `/${pathname?.split("/")[1] || "dashboard"}`;
  const currentTitle = useMemo(() => pageTitles[selectedKey] ?? "视觉运营中心", [selectedKey]);
  const menuItems = useMemo(() => buildMenuItems(user ?? tenant), [tenant, user]);
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

          <div className="office-nav-label">视觉经营决策</div>
          <Menu
            mode="inline"
            theme="dark"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onClick={navigate}
            className="office-menu"
          />

          <div className="office-sider-footer">
            <UserProfile user={user} isLoading={userLoading} collapsed={collapsed} />
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
              <span className="office-header__eyebrow">
                {tenant ? `${tenant.tenant_name} · ${tenant.tenant_id}` : "SHELOOK · 视觉运营中心"}
              </span>
              <strong>{currentTitle}</strong>
            </div>
          </div>
          <div className="office-header__status">
            <Badge status="processing" text="服务已连接" />
            {!isMobile && <span>经营数据与工作流实时同步</span>}
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
          <UserProfile user={user} isLoading={userLoading} />
        </div>
      </Drawer>
    </Layout>
  );
}
