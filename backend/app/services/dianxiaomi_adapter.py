"""Contract boundary for Dianxiaomi; never guess undocumented endpoints or signatures."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from app.models.integration import DianxiaomiConnection


class ProviderContractUnavailable(RuntimeError):
    """Raised until the enterprise supplies its authorized vendor contract."""


@dataclass(frozen=True, slots=True)
class ProviderFact:
    scope: str
    external_id: str
    payload: dict
    shop_reference: str | None = None
    marketplace: str | None = None
    source_updated_at: datetime | None = None
    occurred_at: datetime | None = None
    deleted: bool = False


class DianxiaomiAdapter:
    """Future implementation point for the vendor-specific authentication and paging protocol.

    A generic HTTP fallback would be unsafe: the public help material does not
    define the merchant endpoint paths, signing fields, field contract, or
    cursor semantics granted to this enterprise.
    """

    async def fetch(
        self,
        connection: DianxiaomiConnection,
        *,
        scopes: list[str],
        cursor: str | None,
    ) -> AsyncIterator[ProviderFact]:
        _ = (connection, scopes, cursor)
        raise ProviderContractUnavailable(
            "店小秘真实同步尚待贵司提供已授权开放平台的接口地址、签名规则、字段契约、"
            "分页/增量游标和测试授权；系统不会猜测接口并伪造同步结果。"
        )
        yield  # pragma: no cover - keeps this method an async generator for the future adapter


def get_dianxiaomi_adapter() -> DianxiaomiAdapter:
    return DianxiaomiAdapter()
