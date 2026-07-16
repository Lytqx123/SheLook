"""电商平台数据采集适配器 —— Shopee / Lazada / Amazon 三平台。

所有适配器使用 httpx 异步 HTTP 客户端，支持代理和超时配置。
"""

import asyncio
import gzip
import hashlib
import hmac
import json
import time
from abc import ABC, abstractmethod
from datetime import date
from typing import Literal

import httpx

from app.config import settings
from app.core.logging import logger
from app.schemas.metrics import MetricsBatchItem, MetricsRawItem

DEFAULT_TIMEOUT = 30.0


class PlatformMetricsCollector(ABC):
    """电商平台数据采集适配器抽象基类"""

    platform: str = "unknown"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self._client: httpx.AsyncClient | None = None
        self.timeout = timeout

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    @abstractmethod
    async def fetch_daily_metrics(self, date_range: tuple[date, date]) -> list[MetricsRawItem]:
        """从平台拉取指定日期范围的原始指标"""
        ...

    def map_to_internal_schema(
        self,
        raw_item: MetricsRawItem,
        image_id: int,
    ) -> MetricsBatchItem:
        """将平台原始数据映射为内部 upsert schema"""
        return MetricsBatchItem(
            image_id=image_id,
            date=raw_item.date,
            source_platform=self.platform,
            impressions=raw_item.impressions,
            clicks=raw_item.clicks,
            ctr=raw_item.ctr,
            cvr=raw_item.cvr,
            add_to_cart_rate=raw_item.add_to_cart_rate,
            return_rate=raw_item.return_rate,
            revenue=raw_item.revenue,
        )


# --- Shopee 适配器

class ShopeeCollector(PlatformMetricsCollector):
    """Shopee Open API v2 数据采集适配器"""

    platform = "shopee"

    def __init__(self, region: str = "sg", timeout: float = DEFAULT_TIMEOUT):
        super().__init__(timeout)
        self.region = region
        self.partner_id = settings.SHOPEE_PARTNER_ID
        self.partner_key = settings.SHOPEE_PARTNER_KEY
        self.shop_id = settings.SHOPEE_SHOP_ID
        self.access_token = settings.SHOPEE_ACCESS_TOKEN

        API_HOSTS = {
            "sg": "https://partner.shopeemobile.com",
            "my": "https://partner.shopeemobile.com",
            "th": "https://partner.shopeemobile.com",
            "tw": "https://partner.shopeemobile.com",
            "id": "https://partner.shopeemobile.com",
            "vn": "https://partner.shopeemobile.com",
            "ph": "https://partner.shopeemobile.com",
            "br": "https://partner.shopeemobile.com",
            "mx": "https://partner.shopeemobile.com",
        }
        self.api_host = API_HOSTS.get(self.region, "https://partner.shopeemobile.com")

    async def fetch_daily_metrics(self, date_range: tuple[date, date]) -> list[MetricsRawItem]:
        """从 Shopee API 拉取指标数据"""
        from datetime import timedelta

        if not all((self.partner_id, self.partner_key, self.shop_id, self.access_token)):
            raise RuntimeError("Shopee Partner/Shop/Access Token 凭据未完整配置")

        client = await self._get_client()
        api_path = "/api/v2/product/get_item_performance"

        items: list[MetricsRawItem] = []
        failures: list[str] = []

        current = date_range[0]
        while current <= date_range[1]:
            timestamp = int(time.time())
            sign = self._generate_sign(api_path, timestamp, self.access_token, self.shop_id)

            params = {
                "partner_id": self.partner_id,
                "timestamp": timestamp,
                "sign": sign,
                "access_token": self.access_token,
                "shop_id": self.shop_id,
                "date": current.isoformat(),
                "page_size": 100,
                "page_no": 0,
            }

            try:
                response = await client.get(
                    f"{self.api_host}{api_path}",
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

                if data.get("error"):
                    failures.append(f"{current}: {data['error']}")
                    current += timedelta(days=1)
                    continue

                performance_list = data.get("response", {}).get("performance_list", [])
                for perf in performance_list:
                    items.append(MetricsRawItem(
                        external_id=str(perf.get("item_id", "")),
                        date=current,
                        impressions=int(perf.get("impressions", 0)),
                        clicks=int(perf.get("clicks", 0)),
                        ctr=float(perf.get("ctr", 0)) if perf.get("ctr") else None,
                        cvr=float(perf.get("cvr", 0)) if perf.get("cvr") else None,
                        add_to_cart_rate=float(perf.get("add_to_cart_conversion_rate", 0)) if perf.get("add_to_cart_conversion_rate") else None,
                        return_rate=None,
                        revenue=float(perf.get("revenue", 0)) if perf.get("revenue") else None,
                    ))

            except httpx.HTTPError as e:
                failures.append(f"{current}: {e}")

            current += timedelta(days=1)

        if failures:
            raise RuntimeError("Shopee 指标同步未完整成功: " + "; ".join(failures[:5]))
        logger.info(f"Shopee 数据拉取完成 region={self.region}", fetched=len(items))
        return items

    def map_to_internal_schema(self, raw_item: MetricsRawItem, image_id: int) -> MetricsBatchItem:
        """Shopee 字段映射到内部 schema"""
        return super().map_to_internal_schema(raw_item, image_id)

    def _generate_sign(
        self,
        api_path: str,
        timestamp: int,
        access_token: str,
        shop_id: str,
    ) -> str:
        """生成 Shopee API 请求签名（HMAC-SHA256）"""
        base_string = f"{self.partner_id}{api_path}{timestamp}{access_token}{shop_id}"
        return hmac.new(
            self.partner_key.encode(),
            base_string.encode(),
            hashlib.sha256,
        ).hexdigest()


# --- Lazada 适配器

class LazadaCollector(PlatformMetricsCollector):
    """Lazada Open Platform API 数据采集适配器

    Lazada 公开接口只提供商品资料，不提供 listing 级 impressions/clicks/CTR。
    数据应通过 /api/metrics/batch 从获授权的 Business Advisor 导入。
    """

    platform = "lazada"

    async def fetch_daily_metrics(self, date_range: tuple[date, date]) -> list[MetricsRawItem]:
        raise RuntimeError(
            "Lazada Open Platform 未提供已验证的 listing CTR 公共接口；"
            "请将获授权的数据通过 /api/metrics/batch 导入"
        )

    def map_to_internal_schema(self, raw_item: MetricsRawItem, image_id: int) -> MetricsBatchItem:
        """Lazada SkuId → image_id 映射"""
        return super().map_to_internal_schema(raw_item, image_id)


# --- Amazon 适配器

class AmazonCollector(PlatformMetricsCollector):
    """Amazon SP-API (Selling Partner API) 数据采集适配器"""

    platform = "amazon"

    API_BASE_URLS = {
        "na": "https://sellingpartnerapi-na.amazon.com",
        "eu": "https://sellingpartnerapi-eu.amazon.com",
        "fe": "https://sellingpartnerapi-fe.amazon.com",
    }

    def __init__(self, region: str = "na", timeout: float = DEFAULT_TIMEOUT):
        super().__init__(timeout)
        self.region = region
        self.refresh_token = settings.AMAZON_REFRESH_TOKEN
        self.client_id = settings.AMAZON_CLIENT_ID
        self.client_secret = settings.AMAZON_CLIENT_SECRET
        self.marketplace_id = settings.AMAZON_MARKETPLACE_ID
        self.api_base_url = self.API_BASE_URLS.get(region, self.API_BASE_URLS["na"])
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    async def _get_access_token(self) -> str:
        """获取 Amazon SP-API 访问令牌（LWA OAuth 2.0）"""
        if self._access_token and time.monotonic() < self._access_token_expires_at:
            return self._access_token
        if not all((self.refresh_token, self.client_id, self.client_secret)):
            raise RuntimeError("Amazon LWA 凭据未完整配置")

        client = await self._get_client()
        response = await client.post(
            "https://api.amazon.com/auth/o2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        self._access_token_expires_at = time.monotonic() + max(
            int(payload.get("expires_in", 3600)) - 60,
            60,
        )
        return self._access_token

    async def _request_daily_report(self, report_date: date, access_token: str) -> dict:
        """请求、轮询并下载单日 Sales and Traffic JSON 报告。"""
        client = await self._get_client()
        headers = {"x-amz-access-token": access_token, "Content-Type": "application/json"}
        response = await client.post(
            f"{self.api_base_url}/reports/2021-06-30/reports",
            headers=headers,
            json={
                "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
                "dataStartTime": report_date.isoformat(),
                "dataEndTime": report_date.isoformat(),
                "marketplaceIds": [self.marketplace_id],
                "reportOptions": {"dateGranularity": "DAY", "asinGranularity": "CHILD"},
            },
        )
        response.raise_for_status()
        report_id = response.json()["reportId"]

        deadline = time.monotonic() + settings.AMAZON_REPORT_TIMEOUT_SECONDS
        report_document_id: str | None = None
        while time.monotonic() < deadline:
            status_response = await client.get(
                f"{self.api_base_url}/reports/2021-06-30/reports/{report_id}",
                headers=headers,
            )
            status_response.raise_for_status()
            status_payload = status_response.json()
            status = status_payload.get("processingStatus")
            if status == "DONE":
                report_document_id = status_payload.get("reportDocumentId")
                break
            if status in {"CANCELLED", "FATAL"}:
                raise RuntimeError(f"Amazon 报告 {report_id} 生成失败: {status}")
            await asyncio.sleep(settings.AMAZON_REPORT_POLL_SECONDS)
        if not report_document_id:
            raise TimeoutError(f"Amazon 报告 {report_id} 等待超时")

        document_response = await client.get(
            f"{self.api_base_url}/reports/2021-06-30/documents/{report_document_id}",
            headers=headers,
        )
        document_response.raise_for_status()
        document = document_response.json()
        download = await client.get(document["url"])
        download.raise_for_status()
        content = download.content
        if document.get("compressionAlgorithm") == "GZIP":
            content = gzip.decompress(content)
        return json.loads(content.decode("utf-8"))

    @staticmethod
    def _parse_daily_report(payload: dict, report_date: date) -> list[MetricsRawItem]:
        """把官方报告 schema 映射为内部记录，不伪造 Amazon 未提供的点击量。"""
        items: list[MetricsRawItem] = []
        for record in payload.get("salesAndTrafficByAsin", []):
            external_id = str(record.get("childAsin") or record.get("sku") or "").strip()
            if not external_id:
                continue
            sales = record.get("salesByAsin") or {}
            traffic = record.get("trafficByAsin") or {}
            unit_session_percentage = traffic.get("unitSessionPercentage")
            cvr = None
            if unit_session_percentage is not None:
                cvr = min(1.0, max(0.0, float(unit_session_percentage) / 100))
            revenue = (sales.get("orderedProductSales") or {}).get("amount")
            items.append(
                MetricsRawItem(
                    external_id=external_id,
                    date=report_date,
                    # Sales & Traffic 报告没有 listing click count
                    impressions=0,
                    clicks=0,
                    ctr=None,
                    cvr=cvr,
                    revenue=float(revenue) if revenue is not None else None,
                )
            )
        return items

    async def fetch_daily_metrics(self, date_range: tuple[date, date]) -> list[MetricsRawItem]:
        """按日拉取 Amazon Sales and Traffic 报告。"""
        from datetime import timedelta

        total_days = (date_range[1] - date_range[0]).days + 1
        if total_days > settings.AMAZON_SYNC_MAX_DAYS:
            raise ValueError(
                f"Amazon 单次同步最多 {settings.AMAZON_SYNC_MAX_DAYS} 天，"
                "请缩短日期范围或使用每日调度"
            )
        if not self.marketplace_id:
            raise RuntimeError("AMAZON_MARKETPLACE_ID 未配置")
        access_token = await self._get_access_token()

        items: list[MetricsRawItem] = []

        current = date_range[0]
        while current <= date_range[1]:
            payload = await self._request_daily_report(current, access_token)
            items.extend(self._parse_daily_report(payload, current))
            current += timedelta(days=1)

        logger.info(f"Amazon 数据拉取完成 region={self.region}", fetched=len(items))
        return items

    def map_to_internal_schema(self, raw_item: MetricsRawItem, image_id: int) -> MetricsBatchItem:
        """Amazon ASIN → image_id 映射"""
        return super().map_to_internal_schema(raw_item, image_id)


# --- 工厂函数

def get_collector(platform: Literal["shopee", "lazada", "amazon"]) -> PlatformMetricsCollector:
    """获取平台数据采集器实例"""
    collectors = {
        "shopee": ShopeeCollector,
        "lazada": LazadaCollector,
        "amazon": AmazonCollector,
    }

    cls = collectors.get(platform)
    if cls is None:
        raise ValueError(f"不支持的平台: {platform}，可选值: {list(collectors.keys())}")

    return cls()
