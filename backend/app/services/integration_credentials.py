"""Encryption helpers for tenant-managed integration credentials."""

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class CredentialCipherError(ValueError):
    """Raised when stored credentials cannot be encrypted or read safely."""


def _credential_key_material() -> str:
    material = settings.INTEGRATION_CREDENTIALS_ENCRYPTION_KEY.strip()
    if material:
        return material
    if settings.APP_ENV.lower() == "production":
        raise CredentialCipherError(
            "生产环境必须配置 INTEGRATION_CREDENTIALS_ENCRYPTION_KEY 才能保存集成凭据"
        )
    return settings.SECRET_KEY


def _fernet() -> Fernet:
    digest = hashlib.sha256(_credential_key_material().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credentials(credentials: dict[str, Any]) -> tuple[str, str]:
    """Encrypt JSON credentials and return a non-reversible content fingerprint."""
    normalized = {key: value for key, value in credentials.items() if value not in (None, "")}
    if not normalized:
        raise CredentialCipherError("没有可保存的集成凭据")
    plaintext = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(plaintext).decode("ascii"), hashlib.sha256(plaintext).hexdigest()


def decrypt_credentials(ciphertext: str) -> dict[str, str]:
    """Decrypt only inside backend processes; callers must never log the result."""
    try:
        decoded = _fernet().decrypt(ciphertext.encode("ascii"))
        value = json.loads(decoded.decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CredentialCipherError("集成凭据无法解密；请重新保存授权信息") from exc
    if not isinstance(value, dict) or not value:
        raise CredentialCipherError("集成凭据格式无效；请重新保存授权信息")
    return {str(key): str(item) for key, item in value.items()}
