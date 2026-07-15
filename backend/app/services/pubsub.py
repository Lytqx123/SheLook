"""Redis Pub/Sub 服务 —— WebSocket 消息广播

替代 generation.py 中的内存字典 _ws_connections，
支持多 worker 横向扩展下的 WebSocket 消息推送。

架构：
  Celery Task (generation_task.py)
    → Redis PUBLISH channel="generation:{image_id}"
  FastAPI WebSocket endpoint (generation.py)
    → Redis SUBSCRIBE channel="generation:{image_id}"
    → 转发到客户端 WebSocket
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.core.logging import logger


class RedisPubSub:
    """Redis 发布/订阅客户端

    用法：
        pubsub = RedisPubSub()
        await pubsub.connect()

        # 发布端（Celery task）
        await pubsub.publish(image_id, {"status": "completed", "image_url": "..."})

        # 订阅端（WebSocket endpoint）
        await pubsub.subscribe(image_id, callback=send_to_client)
    """

    def __init__(self):
        self._redis_url = settings.REDIS_URL
        self._pub_client: aioredis.Redis | None = None
        self._sub_client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """建立 Redis 连接"""
        if self._pub_client is None:
            self._pub_client = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        if self._sub_client is None:
            self._sub_client = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

    async def disconnect(self) -> None:
        """关闭 Redis 连接"""
        if self._pub_client:
            await self._pub_client.close()
            self._pub_client = None
        if self._sub_client:
            await self._sub_client.close()
            self._sub_client = None

    def _channel_name(self, image_id: int) -> str:
        return f"generation:{image_id}"

    async def publish(self, image_id: int, data: dict[str, Any]) -> int:
        """发布消息到指定图片的 channel

        Returns:
            收到消息的订阅者数量
        """
        if self._pub_client is None:
            await self.connect()

        channel = self._channel_name(image_id)
        message = json.dumps(data, ensure_ascii=False)
        count = await self._pub_client.publish(channel, message)
        logger.debug(
            "Pub/Sub 消息已发布",
            channel=channel,
            subscribers=count,
            image_id=image_id,
        )
        return count

    async def subscribe(
        self,
        image_id: int,
        callback: Callable[[dict[str, Any]], Awaitable[None]],
        timeout: float = 300.0,
    ) -> None:
        """订阅指定图片的消息 channel

        Args:
            image_id: 图片 ID
            callback: 异步回调函数 callback(data: dict)
            timeout: 订阅超时（秒），超时后自动取消
        """
        if self._sub_client is None:
            await self.connect()

        channel = self._channel_name(image_id)
        pubsub = self._sub_client.pubsub()
        await pubsub.subscribe(channel)
        logger.debug("Pub/Sub 已订阅", channel=channel, timeout=timeout)

        async def _listen():
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await callback(data)
                    except json.JSONDecodeError:
                        logger.warning("Pub/Sub 消息解析失败", raw=message["data"])
                    # 收到消息后取消订阅（一次生成只通知一次）
                    break
                elif message["type"] == "subscribe":
                    continue

        try:
            await asyncio.wait_for(_listen(), timeout=timeout)
        except TimeoutError:
            logger.warning("Pub/Sub 订阅超时", channel=channel, timeout=timeout)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            logger.debug("Pub/Sub 已取消订阅", channel=channel)


# 全局单例（在 lifespan 中初始化）
pubsub: RedisPubSub | None = None
_lock = asyncio.Lock()


async def get_pubsub() -> RedisPubSub:
    """获取 Redis Pub/Sub 全局单例"""
    global pubsub
    async with _lock:
        if pubsub is None:
            pubsub = RedisPubSub()
            await pubsub.connect()
    return pubsub


async def notify_generation_completed(image_id: int, data: dict[str, Any]) -> int:
    """通知前端某张图片生成完成

    由 Celery 任务在生成完成后调用。
    """
    ps = await get_pubsub()
    return await ps.publish(image_id, data)
