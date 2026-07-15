"""统一且抗 SSRF 的远程图片获取与 PIL 解析入口。"""

import asyncio
import ipaddress
import socket
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from app.config import settings

_REDIRECT_CODES = {301, 302, 303, 307, 308}


class ImageFetchError(ValueError):
    """远程图片不符合安全或内容约束。"""


@dataclass(frozen=True, slots=True)
class FetchedImage:
    data: bytes
    content_type: str
    final_url: str


def _host_matches(host: str, pattern: str) -> bool:
    pattern = pattern.lower().rstrip(".")
    host = host.lower().rstrip(".")
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return host.endswith(suffix) and host != suffix[1:]
    return host == pattern


def _is_allowed_host(host: str) -> bool:
    return any(_host_matches(host, pattern) for pattern in settings.IMAGE_FETCH_ALLOWED_HOSTS)


def _is_trusted_private_host(host: str) -> bool:
    return any(
        _host_matches(host, pattern) for pattern in settings.IMAGE_FETCH_TRUSTED_PRIVATE_HOSTS
    )


def _validate_ip(host: str, value: str) -> None:
    ip = ipaddress.ip_address(value)
    unsafe = (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
    if unsafe and not _is_trusted_private_host(host):
        raise ImageFetchError(f"目标主机 {host} 解析到受限网络地址")


def validate_remote_image_url(url: str) -> str:
    """校验 scheme、凭据、allowlist 与 DNS 解析结果。"""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ImageFetchError("图片 URL 仅支持 http/https")
    if parsed.username or parsed.password:
        raise ImageFetchError("图片 URL 不允许包含凭据")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or not _is_allowed_host(host):
        raise ImageFetchError(f"图片主机不在 allowlist: {host or '<empty>'}")
    try:
        _validate_ip(host, host)
    except ValueError:
        try:
            addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror as exc:
            raise ImageFetchError(f"图片主机无法解析: {host}") from exc
        for address in {entry[4][0] for entry in addresses}:
            _validate_ip(host, address)
    return url


def _validate_image_response(content_type: str, data: bytes) -> str:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if not media_type.startswith("image/"):
        raise ImageFetchError(f"响应 Content-Type 不是图片: {media_type or '<missing>'}")
    if not data:
        raise ImageFetchError("图片响应为空")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageFetchError("响应内容不是可解析图片") from exc
    return media_type


def _configured_minio_location(url: str) -> tuple[str, str] | None:
    """把公开 MinIO URL 安全映射为配置桶对象，不开放任意内网 HTTP。"""
    base = urlsplit(settings.MINIO_PUBLIC_BASE_URL)
    target = urlsplit(url)
    if target.username or target.password:
        return None

    def _port(parsed) -> int | None:
        return parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None)

    if (
        target.scheme != base.scheme
        or (target.hostname or "").lower() != (base.hostname or "").lower()
        or _port(target) != _port(base)
    ):
        return None

    base_path = base.path.rstrip("/")
    prefix = f"{base_path}/" if base_path else "/"
    if not target.path.startswith(prefix):
        return None
    relative = target.path[len(prefix):]
    bucket_part, separator, object_part = relative.partition("/")
    bucket = unquote(bucket_part)
    object_key = unquote(object_part)
    if not separator or not object_key:
        return None
    if bucket not in {settings.MINIO_BUCKET, settings.MINIO_PRIVATE_BUCKET}:
        return None
    return bucket, object_key


def _fetch_configured_minio_sync(url: str, limit: int) -> FetchedImage:
    location = _configured_minio_location(url)
    if location is None:
        raise ImageFetchError("URL 不是配置的 MinIO 对象地址")

    from app.services.storage_service import get_minio_client

    bucket, object_key = location
    response = None
    try:
        response = get_minio_client().get_object(bucket, object_key)
        declared = int(response.headers.get("content-length", "0") or 0)
        if declared > limit:
            raise ImageFetchError(f"图片超过大小限制 {limit} bytes")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ImageFetchError(f"图片超过大小限制 {limit} bytes")
        content_type = _validate_image_response(response.headers.get("content-type", ""), data)
        return FetchedImage(data=data, content_type=content_type, final_url=url)
    except ImageFetchError:
        raise
    except Exception as exc:
        raise ImageFetchError("MinIO 图片读取失败") from exc
    finally:
        if response is not None:
            response.close()
            response.release_conn()


async def fetch_image(
    url: str,
    *,
    max_bytes: int | None = None,
    timeout: float | None = None,
) -> FetchedImage:
    """异步下载图片；逐跳校验重定向并限制响应体大小。"""
    limit = max_bytes or settings.IMAGE_FETCH_MAX_BYTES
    if _configured_minio_location(url) is not None:
        return await asyncio.to_thread(_fetch_configured_minio_sync, url, limit)
    current = url
    async with httpx.AsyncClient(
        timeout=timeout or settings.IMAGE_FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
    ) as client:
        for _ in range(settings.IMAGE_FETCH_MAX_REDIRECTS + 1):
            await asyncio.to_thread(validate_remote_image_url, current)
            async with client.stream("GET", current, headers={"Accept": "image/*"}) as response:
                if response.status_code in _REDIRECT_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise ImageFetchError("重定向响应缺少 Location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                declared = int(response.headers.get("content-length", "0") or 0)
                if declared > limit:
                    raise ImageFetchError(f"图片超过大小限制 {limit} bytes")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ImageFetchError(f"图片超过大小限制 {limit} bytes")
                    chunks.append(chunk)
                data = b"".join(chunks)
                content_type = _validate_image_response(response.headers.get("content-type", ""), data)
                return FetchedImage(data=data, content_type=content_type, final_url=current)
    raise ImageFetchError("图片重定向次数过多")


def fetch_image_sync(
    url: str,
    *,
    max_bytes: int | None = None,
    timeout: float | None = None,
) -> FetchedImage:
    """同步版本，供 Celery/CLIP 同步推理路径使用。"""
    limit = max_bytes or settings.IMAGE_FETCH_MAX_BYTES
    if _configured_minio_location(url) is not None:
        return _fetch_configured_minio_sync(url, limit)
    current = url
    with httpx.Client(
        timeout=timeout or settings.IMAGE_FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
    ) as client:
        for _ in range(settings.IMAGE_FETCH_MAX_REDIRECTS + 1):
            validate_remote_image_url(current)
            with client.stream("GET", current, headers={"Accept": "image/*"}) as response:
                if response.status_code in _REDIRECT_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise ImageFetchError("重定向响应缺少 Location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                declared = int(response.headers.get("content-length", "0") or 0)
                if declared > limit:
                    raise ImageFetchError(f"图片超过大小限制 {limit} bytes")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ImageFetchError(f"图片超过大小限制 {limit} bytes")
                    chunks.append(chunk)
                data = b"".join(chunks)
                content_type = _validate_image_response(response.headers.get("content-type", ""), data)
                return FetchedImage(data=data, content_type=content_type, final_url=current)
    raise ImageFetchError("图片重定向次数过多")


def open_image_source(source: str | Path | bytes) -> Image.Image:
    """统一解析 URL、本地路径或字节，并返回已脱离底层流的 RGB 图像。"""
    if isinstance(source, bytes):
        data = source
    elif isinstance(source, str) and source.startswith(("http://", "https://")):
        data = fetch_image_sync(source).data
    else:
        try:
            with Image.open(Path(source)) as image:
                image.load()
                return image.convert("RGB").copy()
        except (UnidentifiedImageError, OSError) as exc:
            raise ImageFetchError("无法解析图片") from exc
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            return image.convert("RGB").copy()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageFetchError("无法解析图片") from exc


def fetch_image_to_temp_sync(url: str) -> str:
    fetched = fetch_image_sync(url)
    suffix = ".png" if fetched.content_type == "image/png" else ".webp" if fetched.content_type == "image/webp" else ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(fetched.data)
        return handle.name
