"""MinIO 图片存储：草稿私有、发布后复制到公开桶。"""

import asyncio
import io
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import quote, urlsplit

from minio import Minio
from minio.commonconfig import CopySource

from app.config import settings


@dataclass(frozen=True, slots=True)
class StoredObject:
    bucket: str
    object_key: str
    url: str
    is_public: bool


def get_minio_client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def get_minio_presign_client() -> Minio:
    """使用浏览器可访问的公开 origin 离线生成签名 URL。"""
    parsed = urlsplit(settings.MINIO_PUBLIC_BASE_URL)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("MINIO_PUBLIC_BASE_URL 必须是完整的 http(s) origin")
    if parsed.path not in {"", "/"}:
        raise ValueError("MINIO_PUBLIC_BASE_URL 不支持路径前缀")
    return Minio(
        parsed.netloc,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=parsed.scheme == "https",
        region=settings.MINIO_REGION,
    )


def public_object_url(object_key: str) -> str:
    base = settings.MINIO_PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/{quote(settings.MINIO_BUCKET, safe='')}/{quote(object_key, safe='/')}"


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


async def store_image(
    data: bytes,
    object_key: str,
    content_type: str,
    *,
    public: bool = False,
) -> StoredObject:
    bucket = settings.MINIO_BUCKET if public else settings.MINIO_PRIVATE_BUCKET
    client = get_minio_client()

    def _put() -> str:
        _ensure_bucket(client, bucket)
        client.put_object(
            bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return (
            public_object_url(object_key)
            if public
            else get_minio_presign_client().presigned_get_object(
                bucket,
                object_key,
                expires=timedelta(seconds=settings.MINIO_PRESIGNED_URL_EXPIRY_SECONDS),
            )
        )

    url = await asyncio.to_thread(_put)
    return StoredObject(bucket=bucket, object_key=object_key, url=url, is_public=public)


async def publish_object(bucket: str, object_key: str) -> StoredObject:
    """幂等地把私有对象复制进公开桶，并返回稳定 URL。

    私有源对象由调用方在数据库提交成功后清理，避免“对象已移动、事务却回滚”。
    """
    client = get_minio_client()

    def _publish() -> None:
        _ensure_bucket(client, settings.MINIO_BUCKET)
        if bucket != settings.MINIO_BUCKET:
            client.copy_object(
                settings.MINIO_BUCKET,
                object_key,
                CopySource(bucket, object_key),
            )

    await asyncio.to_thread(_publish)
    return StoredObject(
        bucket=settings.MINIO_BUCKET,
        object_key=object_key,
        url=public_object_url(object_key),
        is_public=True,
    )


async def presign_object(bucket: str, object_key: str) -> str:
    """为私有对象签发新的短期读取 URL；公开对象始终返回稳定 URL。"""
    if bucket == settings.MINIO_BUCKET:
        return public_object_url(object_key)
    client = get_minio_presign_client()
    return await asyncio.to_thread(
        client.presigned_get_object,
        bucket,
        object_key,
        expires=timedelta(seconds=settings.MINIO_PRESIGNED_URL_EXPIRY_SECONDS),
    )


async def resolve_image_url(image: Any) -> str:
    """按对象定位信息解析可用 URL，避免数据库里的私有签名 URL 过期。"""
    bucket = getattr(image, "storage_bucket", None)
    object_key = getattr(image, "storage_object_key", None)
    if bucket and object_key:
        url = await presign_object(bucket, object_key)
        image.image_url = url
        return url
    return str(getattr(image, "image_url", "") or "")


async def remove_object(bucket: str, object_key: str) -> None:
    """删除已确认不再需要的对象。"""
    client = get_minio_client()
    await asyncio.to_thread(client.remove_object, bucket, object_key)
