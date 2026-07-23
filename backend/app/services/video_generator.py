"""Tenant-configured AI video generation: Kling primary, Runway fallback."""

import asyncio
import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.services.provider_config_service import (
    ProviderRuntimeConfig,
    resolve_provider_runtime_config,
)

KLING_API_BASE_DEFAULT = "https://api.klingai.com/v1"
RUNWAY_API_BASE_DEFAULT = "https://api.runwayml.com/v1"


def _kling_headers(config: ProviderRuntimeConfig) -> dict[str, str]:
    """Construct credentials in memory only; they are never logged or returned."""
    headers = {"Content-Type": "application/json"}
    api_key = config.credentials.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        return headers

    access_key = config.credentials.get("access_key")
    secret_key = config.credentials.get("secret_key")
    if access_key and secret_key:
        import jwt

        now = int(time.time())
        token = jwt.encode(
            {"iss": access_key, "exp": now + 1800, "nbf": now - 5},
            secret_key,
            algorithm="HS256",
        )
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _normalize_resolution(resolution: str) -> str:
    value = resolution.lower().strip()
    if value in ("4k", "2160p"):
        return "4K"
    if value in ("1080p", "2k"):
        return "1080p"
    return "720p"


async def generate_product_video(
    db: AsyncSession,
    *,
    tenant_id: str,
    image_url: str,
    prompt: str = "",
    duration_seconds: int = 5,
    resolution: str = "720p",
    style: str = "product_showcase",
) -> dict:
    """Generate a video using only Web-managed tenant provider configurations."""
    started_at = time.time()
    normalized_resolution = _normalize_resolution(resolution)

    kling = await resolve_provider_runtime_config(db, "kling", tenant_id)
    if kling is not None:
        try:
            result = await _generate_with_kling(
                config=kling,
                image_url=image_url,
                prompt=prompt,
                duration_seconds=duration_seconds,
                resolution=normalized_resolution,
                style=style,
            )
            if result.get("video_url") or result.get("status") == "pending":
                result.update(
                    provider="kling",
                    model=result.get("model", "kling-v3-master"),
                    duration_ms=(time.time() - started_at) * 1000,
                )
                if result.get("status") == "pending":
                    result["message"] = "Kling 任务仍在处理，请稍后重试或到供应商控制台查询。"
                return result
        except Exception as exc:
            logger.warning("Kling 视频生成失败，尝试降级通道", error=str(exc))

    runway = await resolve_provider_runtime_config(db, "runway", tenant_id)
    if runway is not None:
        try:
            result = await _generate_with_runway(
                config=runway,
                image_url=image_url,
                prompt=prompt,
                duration_seconds=duration_seconds,
                resolution=normalized_resolution,
            )
            if result.get("video_url") or result.get("status") == "pending":
                result.update(
                    provider="runway",
                    model=result.get("model", "runway-gen4"),
                    duration_ms=(time.time() - started_at) * 1000,
                )
                if result.get("status") == "pending":
                    result["message"] = "Runway 任务仍在处理，请稍后重试或到供应商控制台查询。"
                return result
        except Exception as exc:
            logger.warning("Runway 视频生成失败", error=str(exc))

    return {
        "video_url": "",
        "status": "failed",
        "model": "none",
        "provider": "unavailable",
        "duration_ms": (time.time() - started_at) * 1000,
        "message": "没有可用的视频生成服务。请由管理员在“系统集成 / 外部 API 配置”中配置并启用 Kling 或 Runway。",
    }


async def _generate_with_kling(
    *,
    config: ProviderRuntimeConfig,
    image_url: str,
    prompt: str,
    duration_seconds: int,
    resolution: str,
    style: str,
) -> dict:
    style_prompts = {
        "product_showcase": "Smooth 360-degree product rotation with soft lighting, e-commerce showcase style",
        "lifestyle": "Natural lifestyle scene, model interacting with product in real environment",
        "unboxing": "Clean unboxing sequence on white background, cinematic slow motion",
    }
    payload = {
        "model_name": "kling-v3-master",
        "image": image_url,
        "prompt": prompt or style_prompts.get(style, style_prompts["product_showcase"]),
        "duration": str(duration_seconds),
        "resolution": resolution,
        "mode": "std",
    }
    base_url = config.config.get("api_base_url", KLING_API_BASE_DEFAULT).rstrip("/")
    headers = _kling_headers(config)
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(f"{base_url}/videos/image2video", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            logger.warning("Kling 任务提交失败", code=data.get("code"))
            return {"video_url": "", "status": "failed"}
        task_id = data["data"]["task_id"]
        for _ in range(30):
            await asyncio.sleep(10)
            status_response = await client.get(f"{base_url}/videos/image2video/{task_id}", headers=headers)
            status_response.raise_for_status()
            status_data = status_response.json()
            if status_data.get("code") != 0:
                continue
            task_status = status_data["data"].get("task_status")
            if task_status == "succeed":
                videos = status_data["data"].get("task_result", {}).get("videos", [])
                return {
                    "video_url": videos[0].get("url", "") if videos else "",
                    "status": "completed" if videos else "failed",
                    "model": "kling-v3-master",
                    "task_id": task_id,
                }
            if task_status == "failed":
                return {"video_url": "", "status": "failed", "model": "kling-v3-master"}
    return {"video_url": "", "status": "pending", "model": "kling-v3-master"}


async def _generate_with_runway(
    *,
    config: ProviderRuntimeConfig,
    image_url: str,
    prompt: str,
    duration_seconds: int,
    resolution: str,
) -> dict:
    api_key = config.credentials["api_key"]
    base_url = config.config.get("api_base_url", RUNWAY_API_BASE_DEFAULT).rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "gen4",
        "first_frame_image": image_url,
        "text_prompt": prompt or "Smooth product showcase video, professional lighting",
        "seconds": duration_seconds,
        "resolution": "1080p" if resolution in ("4K", "1080p") else "720p",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{base_url}/image_to_video", headers=headers, json=payload)
        response.raise_for_status()
        task_id = response.json().get("id")
        if not task_id:
            return {"video_url": "", "status": "failed", "model": "runway-gen4"}
        for _ in range(60):
            await asyncio.sleep(10)
            status_response = await client.get(f"{base_url}/tasks/{task_id}", headers=headers)
            status_response.raise_for_status()
            status_data = status_response.json()
            task_status = status_data.get("status", "")
            if task_status == "SUCCEEDED":
                video_url = status_data.get("output", {}).get("url", "")
                return {
                    "video_url": video_url,
                    "status": "completed" if video_url else "failed",
                    "model": "runway-gen4",
                    "task_id": task_id,
                }
            if task_status in ("FAILED", "CANCELLED"):
                return {"video_url": "", "status": "failed", "model": "runway-gen4"}
    return {"video_url": "", "status": "pending", "model": "runway-gen4"}
