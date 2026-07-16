"""AI 视频生成服务 —— Kling AI 优先，Runway 降级。

首选 Kling AI 3.0（成本/中文/质量综合最优），失败后降级 Runway Gen-4.5，
都不行时明确返回不可用，不伪造结果。
"""

import asyncio
import time

import httpx

from app.config import settings
from app.core.logging import logger

# --- Kling API 配置
KLING_API_BASE_DEFAULT = "https://api.klingai.com/v1"


def _get_kling_base_url() -> str:
    return settings.KLING_API_BASE_URL or KLING_API_BASE_DEFAULT


def _get_kling_headers() -> dict:
    """生成 Kling API 请求头

    优先级：KLING_API_KEY (快手版) > KLING_ACCESS_KEY + KLING_SECRET_KEY (国际版 JWT)
    """
    headers = {"Content-Type": "application/json"}

    if settings.KLING_API_KEY:
        headers["Authorization"] = f"Bearer {settings.KLING_API_KEY}"
        return headers

    if settings.KLING_ACCESS_KEY and settings.KLING_SECRET_KEY:
        import jwt

        now = int(time.time())
        payload = {
            "iss": settings.KLING_ACCESS_KEY,
            "exp": now + 1800,
            "nbf": now - 5,
        }
        token = jwt.encode(payload, settings.KLING_SECRET_KEY, algorithm="HS256")
        headers["Authorization"] = f"Bearer {token}"
        return headers

    return headers


def _normalize_resolution(resolution: str) -> str:
    """将分辨率标准化为 API 接受的格式"""
    r = resolution.lower().strip()
    if r in ("4k", "2160p"):
        return "4K"
    if r in ("1080p", "2k"):
        return "1080p"
    return "720p"


async def generate_product_video(
    image_url: str,
    prompt: str = "",
    duration_seconds: int = 5,
    resolution: str = "720p",
    style: str = "product_showcase",
) -> dict:
    """生成电商商品展示短视频

    三级降级：Kling → Runway → 显式不可用。
    """
    start_time = time.time()
    norm_resolution = _normalize_resolution(resolution)

    # 第一级：Kling API
    if settings.KLING_API_KEY or (settings.KLING_ACCESS_KEY and settings.KLING_SECRET_KEY):
        try:
            result = await _generate_with_kling(
                image_url=image_url,
                prompt=prompt,
                duration_seconds=duration_seconds,
                resolution=norm_resolution,
                style=style,
            )
            if result.get("video_url"):
                result["provider"] = "kling"
                result["duration_ms"] = (time.time() - start_time) * 1000
                logger.info("Kling 视频生成成功", duration=result["duration_ms"])
                return result
            if result.get("status") == "pending":
                result["provider"] = "kling"
                result["model"] = result.get("model", "kling-v3-master")
                result["duration_ms"] = (time.time() - start_time) * 1000
                result["message"] = "Kling 视频生成超时，任务可能仍在处理中，请稍后重试"
                return result
        except Exception as e:
            logger.warning("Kling 视频生成失败，尝试降级", error=str(e))

    # 第二级：Runway API
    runway_key = settings.RUNWAY_API_KEY
    if runway_key:
        try:
            result = await _generate_with_runway(
                image_url=image_url,
                prompt=prompt,
                duration_seconds=duration_seconds,
                resolution=norm_resolution,
            )
            if result.get("video_url"):
                result["provider"] = "runway"
                result["duration_ms"] = (time.time() - start_time) * 1000
                logger.info("Runway 视频降级生成成功")
                return result
            if result.get("status") == "pending":
                result["provider"] = "runway"
                result["model"] = result.get("model", "runway-gen4")
                result["duration_ms"] = (time.time() - start_time) * 1000
                result["message"] = "Runway 视频生成超时，任务可能仍在处理中，请稍后重试"
                return result
        except Exception as e:
            logger.warning("Runway 视频生成失败", error=str(e))

    logger.warning("所有视频通道失败，显式返回不可用")
    return {
        "video_url": "",
        "status": "failed",
        "model": "none",
        "provider": "unavailable",
        "duration_ms": (time.time() - start_time) * 1000,
        "message": "视频生成不可用，请检查 API 配置（KLING_API_KEY 或 KLING_ACCESS_KEY+KLING_SECRET_KEY / RUNWAY_API_KEY）",
    }


async def _generate_with_kling(
    image_url: str,
    prompt: str = "",
    duration_seconds: int = 5,
    resolution: str = "720p",
    style: str = "product_showcase",
) -> dict:
    """通过 Kling AI API 生成视频（图生视频）

    Kling 流程：POST 提交任务 → 轮询 GET status → 获取视频 URL。
    """
    headers = _get_kling_headers()

    style_prompts = {
        "product_showcase": "Smooth 360-degree product rotation with soft lighting, e-commerce showcase style",
        "lifestyle": "Natural lifestyle scene, model interacting with product in real environment",
        "unboxing": "Clean unboxing sequence on white background, cinematic slow motion",
    }

    final_prompt = prompt or style_prompts.get(style, style_prompts["product_showcase"])

    payload = {
        "model_name": "kling-v3-master",
        "image": image_url,
        "prompt": final_prompt,
        "duration": str(duration_seconds),
        "resolution": resolution,
        "mode": "std",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{_get_kling_base_url()}/videos/image2video",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            logger.error("Kling 任务提交失败", code=data.get("code"), msg=data.get("message"))
            return {"video_url": "", "status": "failed"}

        task_id = data["data"]["task_id"]

        # 轮询结果（最多 5 分钟）
        for _ in range(30):
            await asyncio.sleep(10)
            status_resp = await client.get(
                f"{_get_kling_base_url()}/videos/image2video/{task_id}",
                headers=headers,
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()

            if status_data.get("code") != 0:
                continue

            task_status = status_data["data"]["task_status"]
            if task_status == "succeed":
                video_url = status_data["data"]["task_result"]["videos"][0]["url"]
                return {
                    "video_url": video_url,
                    "status": "completed",
                    "model": "kling-v3-master",
                    "task_id": task_id,
                }
            elif task_status == "failed":
                return {"video_url": "", "status": "failed"}

        return {"video_url": "", "status": "pending"}


async def _generate_with_runway(
    image_url: str,
    prompt: str = "",
    duration_seconds: int = 5,
    resolution: str = "720p",
) -> dict:
    """通过 Runway API 生成视频（图生视频）

    Runway Gen-4.5 最高支持 1080p，4K 请求自动降级。
    """
    runway_key = settings.RUNWAY_API_KEY

    headers = {
        "Authorization": f"Bearer {runway_key}",
        "Content-Type": "application/json",
    }

    runway_resolution = "1080p" if resolution in ("4K", "1080p") else "720p"

    payload = {
        "model": "gen4",
        "first_frame_image": image_url,
        "text_prompt": prompt or "Smooth product showcase video, professional lighting",
        "seconds": duration_seconds,
        "resolution": runway_resolution,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://api.runwayml.com/v1/image_to_video",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        task_id = data.get("id")
        if not task_id:
            return {"video_url": "", "status": "failed", "model": "runway-gen4"}

        # 轮询等待（最多 10 分钟）
        for _ in range(60):
            await asyncio.sleep(10)
            status_resp = await client.get(
                f"https://api.runwayml.com/v1/tasks/{task_id}",
                headers=headers,
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()

            task_status = status_data.get("status", "")
            if task_status == "SUCCEEDED":
                video_url = status_data.get("output", {}).get("url", "")
                return {
                    "video_url": video_url,
                    "status": "completed" if video_url else "failed",
                    "model": "runway-gen4",
                    "task_id": task_id,
                }
            elif task_status in ("FAILED", "CANCELLED"):
                return {"video_url": "", "status": "failed", "model": "runway-gen4"}

        return {"video_url": "", "status": "pending", "model": "runway-gen4"}
