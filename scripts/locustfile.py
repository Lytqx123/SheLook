"""SheLook Locust 压测场景。

默认只跑已认证的只读请求。预测和生图会写入数据，
需要设 SHELOOK_ENABLE_MUTATIONS=true 并提供对应 ID 才启用。
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task
from locust.exception import StopUser


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


TOKEN = os.getenv("SHELOOK_TOKEN", "").strip()
USER_ID = os.getenv("SHELOOK_USER_ID", "locust-user").strip()
USERNAME = os.getenv("SHELOOK_USERNAME", "Locust User").strip()
ROLE = os.getenv("SHELOOK_ROLE", "viewer").strip()
TENANT_ID = os.getenv("SHELOOK_TENANT_ID", "").strip()
IMAGE_ID = int(os.getenv("SHELOOK_IMAGE_ID", "0") or 0)
SCHEME_ID = int(os.getenv("SHELOOK_SCHEME_ID", "0") or 0)
ENABLE_MUTATIONS = _is_true(os.getenv("SHELOOK_ENABLE_MUTATIONS"))


class AuthenticatedUser(HttpUser):
    abstract = True
    wait_time = between(0.8, 2.5)

    def on_start(self) -> None:
        token = TOKEN
        if not token:
            with self.client.post(
                "/api/auth/token",
                json={"user_id": USER_ID, "username": USERNAME, "role": ROLE},
                name="AUTH development-login",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(
                        "无法取得开发 token；生产/OIDC 环境请设置 SHELOOK_TOKEN"
                    )
                    raise StopUser()
                try:
                    token = str(response.json()["access_token"])
                except (KeyError, TypeError, ValueError):
                    response.failure("登录响应缺少 access_token")
                    raise StopUser()

        self.client.headers.update({"Authorization": f"Bearer {token}"})
        if TENANT_ID:
            self.client.headers["X-Tenant-ID"] = TENANT_ID

    @staticmethod
    def expect(response, expected: set[int]) -> None:
        if response.status_code in expected:
            response.success()
        else:
            response.failure(
                f"HTTP {response.status_code}，预期 {sorted(expected)}"
            )


class ReadOnlyUser(AuthenticatedUser):
    """默认场景：看板、列表和轻量健康检查，不修改业务数据。"""

    abstract = False
    weight = 8

    @task(1)
    def health(self) -> None:
        with self.client.get(
            "/api/health", name="GET /api/health", catch_response=True
        ) as response:
            self.expect(response, {200})

    @task(4)
    def dashboard_summary(self) -> None:
        with self.client.get(
            "/api/dashboard/summary",
            name="GET /api/dashboard/summary",
            catch_response=True,
        ) as response:
            self.expect(response, {200})

    @task(3)
    def dashboard_ctr(self) -> None:
        with self.client.get(
            "/api/dashboard/ctr_trend?days=7",
            name="GET /api/dashboard/ctr_trend",
            catch_response=True,
        ) as response:
            self.expect(response, {200})

    @task(3)
    def products(self) -> None:
        with self.client.get(
            "/api/products?page=1&page_size=20",
            name="GET /api/products",
            catch_response=True,
        ) as response:
            self.expect(response, {200})

    @task(2)
    def experiments(self) -> None:
        with self.client.get(
            "/api/experiments?limit=20",
            name="GET /api/experiments",
            catch_response=True,
        ) as response:
            self.expect(response, {200})

    @task(2)
    def review_queue(self) -> None:
        with self.client.get(
            "/api/review/queue?limit=20",
            name="GET /api/review/queue",
            catch_response=True,
        ) as response:
            self.expect(response, {200})

    @task(1)
    def audit_logs(self) -> None:
        with self.client.get(
            "/api/audit/logs?limit=20",
            name="GET /api/audit/logs",
            catch_response=True,
        ) as response:
            self.expect(response, {200})

    @task(1)
    def model_versions(self) -> None:
        with self.client.get(
            "/api/prediction/model-versions",
            name="GET /api/prediction/model-versions",
            catch_response=True,
        ) as response:
            self.expect(response, {200})


class PredictionUser(AuthenticatedUser):
    """可选预测写入场景。"""

    abstract = not (ENABLE_MUTATIONS and IMAGE_ID > 0)
    weight = 2

    @task
    def predict(self) -> None:
        with self.client.post(
            "/api/prediction",
            json={"image_id": IMAGE_ID},
            name="POST /api/prediction",
            catch_response=True,
        ) as response:
            self.expect(response, {200})


class GenerationUser(AuthenticatedUser):
    """可选生图提交场景；限流、容量不足和服务不可用均记为失败。"""

    abstract = not (ENABLE_MUTATIONS and SCHEME_ID > 0)
    weight = 1
    wait_time = between(5, 12)

    @task
    def generate(self) -> None:
        with self.client.post(
            "/api/generation",
            json={"scheme_id": SCHEME_ID, "market_variant": "us"},
            name="POST /api/generation",
            catch_response=True,
        ) as response:
            self.expect(response, {202})
