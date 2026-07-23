"""阶段二：租户上下文和权限边界回归测试。"""

from app.core.auth import UserInfo, has_permission
from app.core.tenant import clear_tenant_context, get_current_tenant_id, tenant_context


def test_tenant_context_is_restored_after_background_scope() -> None:
    clear_tenant_context()
    assert get_current_tenant_id() == "default"
    with tenant_context("tenant-a", user_id="user-a"):
        assert get_current_tenant_id() == "tenant-a"
    assert get_current_tenant_id() == "default"


def test_role_and_explicit_permissions_are_combined() -> None:
    reviewer = UserInfo(user_id="reviewer", role="reviewer", tenant_id="tenant-a")
    assert has_permission(reviewer, "review:decide")
    assert not has_permission(reviewer, "tenant:manage")

    delegated = UserInfo(
        user_id="delegated",
        role="viewer",
        tenant_id="tenant-a",
        permissions=("tenant:manage",),
    )
    assert has_permission(delegated, "tenant:manage")
