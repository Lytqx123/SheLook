"""统一生图编排、供应商适配、C2PA 签名与对象存储。"""

import asyncio
import base64
import io
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image, ImageDraw

from app.config import settings
from app.core.logging import logger
from app.services.c2pa_service import sign_generated_asset
from app.services.image_fetcher import fetch_image
from app.services.storage_service import store_image

CATEGORY_MODEL_MAP: dict[str, tuple[str, str]] = {
    "promo": ("google", "gemini-3.1-flash-image"),
    "banner": ("google", "gemini-3.1-flash-image"),
}
DEFAULT_MODEL = ("replicate", "black-forest-labs/flux-2-pro")


class GenerationUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderAsset:
    data: bytes
    mime_type: str
    model: str
    provider: str


def route_model(category: str | None = None) -> dict[str, str]:
    provider, model = CATEGORY_MODEL_MAP.get((category or "").lower(), DEFAULT_MODEL)
    return {"provider": provider, "model": model}


async def _replicate_asset(prompt: str, model: str, negative_prompt: str, width: int, height: int) -> ProviderAsset:
    import replicate

    params: dict[str, Any] = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_outputs": 1,
        "num_inference_steps": 28,
        "guidance_scale": 3.5,
    }
    if negative_prompt:
        params["negative_prompt"] = negative_prompt
    output = await asyncio.to_thread(replicate.run, model, input=params)
    source = output[0] if isinstance(output, list) and output else output
    if not source:
        raise GenerationUnavailableError("Replicate 未返回图片")
    fetched = await fetch_image(str(source), timeout=settings.REPLICATE_TIMEOUT)
    return ProviderAsset(fetched.data, fetched.content_type, model, "replicate")


async def _google_asset(prompt: str, model: str, negative_prompt: str) -> ProviderAsset:
    from google import genai
    from google.genai import types

    http_options = types.HttpOptions(base_url=settings.GEMINI_BASE_URL) if settings.GEMINI_BASE_URL else None
    client = genai.Client(api_key=settings.GEMINI_API_KEY, http_options=http_options)
    full_prompt = prompt + (f"\n\nDo not include: {negative_prompt}" if negative_prompt else "")
    response = await client.aio.models.generate_content(
        model=model,
        contents=full_prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    for part in response.parts or []:
        if part.inline_data and part.inline_data.data:
            return ProviderAsset(
                bytes(part.inline_data.data),
                part.inline_data.mime_type or "image/png",
                model,
                "google",
            )
    raise GenerationUnavailableError("Google Gen AI 未返回图片")


async def _sd_webui_asset(prompt: str, negative_prompt: str, width: int, height: int) -> ProviderAsset:
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{settings.SD_WEBUI_URL.rstrip('/')}/sdapi/v1/txt2img",
            json={
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "width": width,
                "height": height,
                "steps": 25,
                "cfg_scale": 7,
            },
        )
        response.raise_for_status()
        images = response.json().get("images", [])
    if not images:
        raise GenerationUnavailableError("SD WebUI 未返回图片")
    return ProviderAsset(base64.b64decode(images[0]), "image/png", "sd-webui", "sd-webui")


def _development_mock(width: int, height: int) -> ProviderAsset:
    image = Image.new("RGB", (width, height), "#eeeeee")
    draw = ImageDraw.Draw(image)
    draw.text((width // 2 - 70, height // 2), "Development mock", fill="#666666")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return ProviderAsset(buffer.getvalue(), "image/png", "development-mock", "mock")


class GenerationService:
    async def _generate_provider_asset(
        self,
        prompt: str,
        category: str | None,
        negative_prompt: str,
        width: int,
        height: int,
    ) -> ProviderAsset:
        route = route_model(category)
        failures: list[str] = []
        try:
            if route["provider"] == "replicate" and settings.REPLICATE_API_TOKEN:
                return await _replicate_asset(prompt, route["model"], negative_prompt, width, height)
            if route["provider"] == "google" and settings.GEMINI_API_KEY:
                return await _google_asset(prompt, route["model"], negative_prompt)
            failures.append(f"{route['provider']} 未配置")
        except Exception as exc:
            failures.append(f"{route['provider']}: {exc}")
            logger.warning("主生图通道失败", provider=route["provider"], error=str(exc))

        try:
            return await _sd_webui_asset(prompt, negative_prompt, width, height)
        except Exception as exc:
            failures.append(f"sd-webui: {exc}")

        if settings.APP_ENV != "production" and settings.ALLOW_GENERATION_MOCKS:
            # 开发环境保底，productions 不允许
            return _development_mock(width, height)
        raise GenerationUnavailableError("所有生图通道失败；" + " | ".join(failures))

    async def generate(
        self,
        prompt: str,
        negative_prompt: str = "blurry, low quality, distorted, watermark",
        width: int = 1024,
        height: int = 1024,
        category: str | None = None,
        *,
        public: bool = False,
        product_id: int | None = None,
        scheme_id: int | None = None,
        generation_params: dict | None = None,
    ) -> dict[str, Any]:
        """生成图片 + C2PA 签名 + 存入对象存储"""
        asset = await self._generate_provider_asset(prompt, category, negative_prompt, width, height)
        # C2PA 签名里面嵌了 prompt 和 product_id，调 sign_generated_asset 同步
        signed = await asyncio.to_thread(
            sign_generated_asset,
            asset.data,
            asset.mime_type,
            prompt=prompt,
            model_name=asset.model,
            width=width,
            height=height,
            generation_params={**(generation_params or {}), "negative_prompt": negative_prompt},
            product_id=product_id,
            scheme_id=scheme_id,
        )
        extension = "png" if "png" in asset.mime_type else "webp" if "webp" in asset.mime_type else "jpg"
        stored = await store_image(
            signed.data,
            f"generated/{product_id or 'unbound'}/{uuid.uuid4().hex}.{extension}",
            asset.mime_type,
            public=public,
        )
        return {
            "image_url": stored.url,
            "storage_bucket": stored.bucket,
            "storage_object_key": stored.object_key,
            "is_public": stored.is_public,
            "c2pa_manifest": signed.manifest_store,
            "c2pa_signed": signed.signed,
            "model": asset.model,
            "provider": asset.provider,
        }

    async def generate_batch(self, schemes: list[dict], **kwargs: Any) -> list[dict[str, Any]]:
        async def _one(index: int, scheme: dict) -> dict[str, Any]:
            result = await self.generate(
                prompt=scheme.get("prompt", ""),
                category=scheme.get("category"),
                **kwargs,
            )
            return {**result, "index": index}

        # TODO: 并发太高容易触发供应商限流，后面加个 semaphore
        results = await asyncio.gather(
            *(_one(index, scheme) for index, scheme in enumerate(schemes)),
            return_exceptions=True,
        )
        return [
            {"index": index, "error": str(result), "image_url": "", "provider": "error", "model": "error"}
            if isinstance(result, Exception)
            else result
            for index, result in enumerate(results)
        ]
