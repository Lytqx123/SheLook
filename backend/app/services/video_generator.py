"""AI 视频生成服务 —— Kling AI + 三级降级

2026 视频模型市场格局（2026-07）：
  - Sora 2 已于 2026.03.24 关闭（月亏损 $8-12M）
  - Kling AI 3.0 成为电商短视频首选：
    - Native 4K 分辨率，最长 2 分钟
    - $0.08-0.15/秒（API 直连或第三方平台）
    - 中文文字渲染业界领先
  - Runway Gen-4.5：电影级画质，但 $0.30-0.40/次
  - Seedance 2.0：成本模型复杂，按分辨率×时长乘法

本项目选择 Kling AI 3.0 作为首选（成本/质量/中文支持综合最佳）。

三级降级：
  Kling API → Runway API → 显式不可用

使用方式：
  from app.services.video_generator import generate_product_video
"""

import asyncio
import time

import httpx

from app.config import settings
from app.core.logging import logger

# ---- Kling API 配置 ----
KLING_API_BASE_DEFAULT = "https://api.klingai.com/v1"


def _get_kling_base_url() -> str:
    return settings.KLING_API_BASE_URL or KLING_API_BASE_DEFAULT


def _get_kling_headers() -> dict:
    """生成 Kling API 请求头，自动选择认证模式

    优先级：
    1. 快手版：KLING_API_KEY（单一 API Key，Bearer token）
    2. 国际版：KLING_ACCESS_KEY + KLING_SECRET_KEY（JWT 签名）
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

    Args:
        image_url: 商品图片 URL（作为首帧参考）
        prompt: 视频动作描述（中英文均可）
        duration_seconds: 视频时长（5/10秒）
        resolution: 分辨率（"720p" / "1080p" / "4K"）
        style: 风格（"product_showcase" / "lifestyle" / "unboxing"）

    Returns:
        {
            "video_url": str,
            "status": "completed" | "failed" | "pending",
            "model": str,
            "provider": str,
            "duration_ms": float,
            "message": str (可选),
        }
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
            # 超时（pending）—— 返回状态而非降级，避免浪费 Runway 配额
            if result.get("status") == "pending":
                result["provider"] = "kling"
                result["model"] = result.get("model", "kling-v3-master")
                result["duration_ms"] = (time.time() - start_time) * 1000
                result["message"] = "Kling 视频生成超时，任务可能仍在处理中，请稍后重试"
                return result
            # status == "failed" → 降级到 Runway
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

    # 不伪造第三方结果：所有通道失败时明确返回不可用。
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

    Kling API 流程：
      1. POST /v1/videos/image2video 提交任务 → 获得 task_id
      2. GET  /v1/videos/image2video/{task_id} 轮询状态 → 获得视频 URL
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
        # 提交任务
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

        # 轮询结果
        for _ in range(30):  # 最多 5 分钟
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

    Note: Runway Gen-4.5 最高支持 1080p，4K 请求自动降级为 1080p。
    """
    runway_key = settings.RUNWAY_API_KEY

    headers = {
        "Authorization": f"Bearer {runway_key}",
        "Content-Type": "application/json",
    }

    # Runway Gen-4.5 最高 1080p，4K 自动降级
    runway_resolution = "1080p" if resolution in ("4K", "1080p") else "720p"

    payload = {
        "model": "gen4",
        "first_frame_image": image_url,
        "text_prompt": prompt or "Smooth product showcase video, professional lighting",
        "seconds": duration_seconds,
        "resolution": runway_resolution,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        # 提交任务
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

        # 轮询等待任务完成
        for _ in range(60):  # 最多 10 分钟
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
