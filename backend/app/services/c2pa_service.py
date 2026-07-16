"""用官方 C2PA SDK 签名、嵌入并验证 Content Credentials。"""

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.logging import logger

AI_SOURCE_TYPE = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"


@dataclass(frozen=True, slots=True)
class SignedAsset:
    data: bytes
    manifest_store: str | None
    signed: bool


def build_manifest_definition(
    *,
    prompt: str,
    model_name: str,
    width: int,
    height: int,
    generation_params: dict | None = None,
    product_id: int | None = None,
    scheme_id: int | None = None,
) -> dict[str, Any]:
    """构建 C2PA manifest 定义，prompt 只存哈希不存明文。"""
    generated_at = datetime.now(UTC).isoformat()
    params = generation_params or {}
    return {
        "claim_generator_info": [{"name": "SheLook", "version": "1.0.0"}],
        "title": "SheLook AI-generated product image",
        "assertions": [
            {
                "label": "c2pa.actions.v2",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": AI_SOURCE_TYPE,
                            "softwareAgent": f"SheLook/{model_name}",
                            "when": generated_at,
                        }
                    ]
                },
            },
            {
                "label": "com.shelook.ai-generation",
                "data": {
                    "ai_generated": True,
                    "generation_model": model_name,
                    "generation_timestamp": generated_at,
                    "prompt_hash_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "negative_prompt_hash_sha256": hashlib.sha256(
                        str(params.get("negative_prompt", "")).encode("utf-8")
                    ).hexdigest(),
                    "image_dimensions": {"width": width, "height": height},
                    "product_id": product_id,
                    "scheme_id": scheme_id,
                },
            },
        ],
    }


def _active_manifest(store: dict[str, Any]) -> dict[str, Any]:
    manifests = store.get("manifests", {})
    active_label = store.get("active_manifest")
    if active_label and isinstance(manifests, dict):
        return manifests.get(active_label, {})
    return store


def _assertions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    raw = manifest.get("assertions", [])
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [
            {"label": label, "data": value.get("data", value) if isinstance(value, dict) else value}
            for label, value in raw.items()
        ]
    return []


def sign_generated_asset(
    data: bytes,
    mime_type: str,
    *,
    prompt: str,
    model_name: str,
    width: int,
    height: int,
    generation_params: dict | None = None,
    product_id: int | None = None,
    scheme_id: int | None = None,
) -> SignedAsset:
    """签名并嵌入 manifest store，签名后立即用 Reader 验证。
    
    FIXME: callback_signer 的算法分支不够优雅，后续统一成 JOSE 格式。
    """
    if not settings.C2PA_ENABLED:
        if settings.C2PA_REQUIRED:
            raise RuntimeError("C2PA_REQUIRED=true 但 C2PA_ENABLED=false")
        return SignedAsset(data=data, manifest_store=None, signed=False)

    cert_path = Path(settings.C2PA_CERT_PATH)
    key_path = Path(settings.C2PA_PRIVATE_KEY_PATH)
    if not cert_path.is_file() or not key_path.is_file():
        message = "C2PA 签名证书或私钥文件不存在"
        if settings.C2PA_REQUIRED:
            raise RuntimeError(message)
        logger.warning(message)
        return SignedAsset(data=data, manifest_store=None, signed=False)

    try:
        from c2pa import Builder, C2paSigningAlg, Context, Reader, Signer
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, padding

        algorithm = getattr(C2paSigningAlg, settings.C2PA_SIGNING_ALGORITHM.upper())
        algorithm_name = settings.C2PA_SIGNING_ALGORITHM.upper()
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)

        def callback_signer(payload: bytes) -> bytes:
            """callback 形式便于后续换成 KMS/HSM。"""
            hash_by_algorithm = {
                "ES256": hashes.SHA256,
                "ES384": hashes.SHA384,
                "ES512": hashes.SHA512,
                "PS256": hashes.SHA256,
                "PS384": hashes.SHA384,
                "PS512": hashes.SHA512,
            }
            if algorithm_name.startswith("ES"):
                return private_key.sign(payload, ec.ECDSA(hash_by_algorithm[algorithm_name]()))
            if algorithm_name.startswith("PS"):
                digest = hash_by_algorithm[algorithm_name]()
                return private_key.sign(
                    payload,
                    padding.PSS(mgf=padding.MGF1(digest), salt_length=digest.digest_size),
                    digest,
                )
            if algorithm_name == "ED25519":
                return private_key.sign(payload)
            raise ValueError(f"不支持的 C2PA 签名算法: {algorithm_name}")
        definition = build_manifest_definition(
            prompt=prompt,
            model_name=model_name,
            width=width,
            height=height,
            generation_params=generation_params,
            product_id=product_id,
            scheme_id=scheme_id,
        )
        source = io.BytesIO(data)
        destination = io.BytesIO()
        with Context.from_dict({"builder": {"thumbnail": {"enabled": True}}}) as context:
            with (
                Signer.from_callback(
                    callback_signer,
                    algorithm,
                    cert_path.read_text(encoding="utf-8"),
                    settings.C2PA_TIMESTAMP_AUTHORITY_URL or None,
                ) as signer,
                Builder(json.dumps(definition), context) as builder,
            ):
                builder.sign(signer, mime_type, source, destination)
            signed_data = destination.getvalue()
            with Reader(mime_type, io.BytesIO(signed_data), context=context) as reader:
                manifest_store = reader.json()
        verification = verify_c2pa_manifest_v2(manifest_store)
        if not verification["passed"]:
            raise RuntimeError(f"C2PA 签名后验证失败: {verification['issues']}")
        return SignedAsset(data=signed_data, manifest_store=manifest_store, signed=True)
    except Exception:
        if settings.C2PA_REQUIRED:
            raise
        logger.exception("C2PA 签名失败，开发环境保留未签名资产")
        return SignedAsset(data=data, manifest_store=None, signed=False)


def generate_c2pa_manifest(*args: Any, **kwargs: Any) -> str:
    """旧接口，不再生成伪凭证。请用 sign_generated_asset()。"""
    raise RuntimeError("请使用 sign_generated_asset() 对真实资产签名并嵌入凭证")


def verify_c2pa_manifest_v2(manifest_str: str | None) -> dict[str, Any]:
    """解析并校验 C2PA manifest：JSON 结构 + 加密验证 + AI 来源声明。"""
    checks: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    if not manifest_str:
        return {
            "passed": False,
            "manifest_valid": False,
            "checks": checks,
            "issues": [{"field": "manifest", "severity": "error", "message": "C2PA manifest 缺失"}],
        }
    try:
        store = json.loads(manifest_str)
    except json.JSONDecodeError as exc:
        return {
            "passed": False,
            "manifest_valid": False,
            "checks": checks,
            "issues": [{"field": "manifest", "severity": "error", "message": f"无效 JSON: {exc}"}],
        }

    validation_status = store.get("validation_status") or []
    validation_errors = [
        status for status in validation_status
        if isinstance(status, dict) and str(status.get("code", "")).lower().endswith(("mismatch", "error", "invalid"))
    ]
    checks.append({"field": "cryptographic_validation", "passed": not validation_errors})
    if validation_errors:
        issues.append({"field": "validation_status", "severity": "error", "message": "C2PA SDK 报告验证错误"})

    manifest = _active_manifest(store)
    assertions = _assertions(manifest)
    action_data = next((item.get("data", {}) for item in assertions if item.get("label", "").startswith("c2pa.actions")), {})
    actions = action_data.get("actions", []) if isinstance(action_data, dict) else []
    ai_action = any(action.get("digitalSourceType") == AI_SOURCE_TYPE for action in actions if isinstance(action, dict))
    checks.append({"field": "trained_algorithmic_media", "passed": ai_action})
    if not ai_action:
        issues.append({"field": "c2pa.actions", "severity": "error", "message": "缺少 AI 生成来源声明"})

    ai_data = next((item.get("data", {}) for item in assertions if item.get("label") == "com.shelook.ai-generation"), None)
    required = ("ai_generated", "generation_model", "generation_timestamp", "prompt_hash_sha256")
    ai_ok = isinstance(ai_data, dict) and all(ai_data.get(field) not in (None, "") for field in required)
    checks.append({"field": "shelook_ai_generation", "passed": ai_ok})
    if not ai_ok:
        issues.append({"field": "com.shelook.ai-generation", "severity": "error", "message": "AI 生成断言不完整"})
    return {
        "passed": not any(issue["severity"] == "error" for issue in issues),
        "manifest_valid": bool(manifest),
        "checks": checks,
        "issues": issues,
    }


def extract_disclosure_metadata(c2pa_manifest: str | None) -> dict[str, Any]:
    """从 manifest 中提取 AI 生成断言数据。"""
    if not c2pa_manifest:
        return {}
    try:
        manifest = _active_manifest(json.loads(c2pa_manifest))
    except json.JSONDecodeError:
        return {}
    return next(
        (item.get("data", {}) for item in _assertions(manifest) if item.get("label") == "com.shelook.ai-generation"),
        {},
    )
