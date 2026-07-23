import type { TenantContext, UserResponse } from "@/types";

/**
 * Keep the client-side information architecture aligned with the server role
 * model. This is an experience guard only; API authorization remains the
 * source of truth on the server.
 */
export type AppRole = "admin" | "operator" | "reviewer" | "analyst" | "supplier" | "viewer";

type IdentityContext = Pick<UserResponse, "role" | "permissions"> | Pick<TenantContext, "role" | "permissions"> | null | undefined;

const ROLE_PERMISSIONS: Record<AppRole, readonly string[]> = {
  admin: ["*"],
  operator: [
    "product:read",
    "product:write",
    "generation:run",
    "review:read",
    "analytics:read",
    "experiment:read",
    "experiment:manage",
    "supplier:read",
    "supplier:write",
  ],
  reviewer: ["product:read", "review:read", "review:decide"],
  analyst: ["product:read", "analytics:read", "experiment:read", "supplier:read"],
  supplier: ["product:read", "supplier:read", "supplier:write"],
  viewer: ["product:read", "review:read", "analytics:read"],
};

const ROLE_LABELS: Record<AppRole, string> = {
  admin: "管理员",
  operator: "运营人员",
  reviewer: "审核人员",
  analyst: "分析人员",
  supplier: "供应商",
  viewer: "只读成员",
};

const ROLE_EXPERIENCES: Record<AppRole, { title: string; subtitle: string; emptyHint: string }> = {
  admin: {
    title: "今日经营决策",
    subtitle: "优先处理影响增长、交付和治理的事项，再进入趋势与模型分析。",
    emptyHint: "当前没有需要升级处理的事项，可新建活动或查看经营趋势。",
  },
  operator: {
    title: "今日运营决策",
    subtitle: "从待审核素材、异常任务和运行中的实验开始，推进本次视觉运营活动。",
    emptyHint: "当前没有待处理事项，可新建一项视觉运营活动。",
  },
  reviewer: {
    title: "今日审核优先队列",
    subtitle: "优先处理等待人工确认的素材，确保合规与质量门禁不阻塞后续投放。",
    emptyHint: "当前审核队列没有待处理素材。",
  },
  analyst: {
    title: "今日实验与洞察",
    subtitle: "关注运行中实验、异常经营信号和已验证的视觉策略，为下一次决策提供证据。",
    emptyHint: "暂无需要分析的实验或经营异常，可查看运营活动和趋势数据。",
  },
  supplier: {
    title: "今日交付质量",
    subtitle: "通过质量分析和整改建议，确保本次素材交付满足市场与审核标准。",
    emptyHint: "暂无新的交付提醒，可提交素材进行质量分析或查看历史报告。",
  },
  viewer: {
    title: "经营概览",
    subtitle: "查看当前视觉运营的进展、审核状态和经营信号；需要执行操作时请联系对应负责人。",
    emptyHint: "暂无需要关注的经营事项。",
  },
};

export function getAppRole(identity?: IdentityContext): AppRole {
  const role = identity?.role;
  return role && role in ROLE_PERMISSIONS ? role as AppRole : "viewer";
}

export function getRoleLabel(identity?: IdentityContext): string {
  return ROLE_LABELS[getAppRole(identity)];
}

export function getRoleExperience(identity?: IdentityContext) {
  return ROLE_EXPERIENCES[getAppRole(identity)];
}

export function hasPermission(identity: IdentityContext, permission: string): boolean {
  const role = getAppRole(identity);
  const granted = new Set([...ROLE_PERMISSIONS[role], ...(identity?.permissions ?? [])]);
  return granted.has("*") || granted.has(permission);
}

export function hasAnyPermission(identity: IdentityContext, permissions: readonly string[]): boolean {
  return permissions.some((permission) => hasPermission(identity, permission));
}

export function isOneOfRoles(identity: IdentityContext, roles: readonly AppRole[]): boolean {
  return roles.includes(getAppRole(identity));
}
