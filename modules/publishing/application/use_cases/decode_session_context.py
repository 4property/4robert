"""Decode GoHighLevel embedded-app session context."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from shared.errors import ApplicationError, ValidationError


class DecodeSessionContextUseCase:
    def __init__(self, *, shared_secret: str) -> None:
        self.shared_secret = str(shared_secret or "").strip()

    def execute(self, *, encrypted_data: str) -> dict[str, Any]:
        if not self.shared_secret:
            raise ApplicationError(
                "GoHighLevel app shared secret is not configured.",
                hint=(
                    "Set GO_HIGH_LEVEL_APP_SHARED_SECRET to the Marketplace app Shared "
                    "Secret from Advanced Settings > Auth, then restart the backend."
                ),
            )

        try:
            encrypted_bytes = base64.b64decode(str(encrypted_data).strip(), validate=True)
        except Exception as exc:
            raise ValidationError(
                "The GoHighLevel user context payload is not valid base64.",
                code="GHL_CONTEXT_INVALID_BASE64",
                hint=(
                    "Send the raw payload returned by REQUEST_USER_DATA_RESPONSE "
                    "as encryptedData."
                ),
                cause=exc,
            ) from exc

        if len(encrypted_bytes) <= 16 or not encrypted_bytes.startswith(b"Salted__"):
            raise ValidationError(
                "The GoHighLevel user context payload is not in the expected encrypted format.",
                code="GHL_CONTEXT_INVALID_FORMAT",
                hint=(
                    "Send the encrypted string returned by HighLevel postMessage, "
                    "not a parsed object."
                ),
            )

        salt = encrypted_bytes[8:16]
        ciphertext = encrypted_bytes[16:]
        key, iv = _derive_cryptojs_key_and_iv(
            password=self.shared_secret.encode("utf-8"),
            salt=salt,
        )

        try:
            decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
            padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
            parsed = json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise ValidationError(
                "Failed to decrypt the GoHighLevel user context payload.",
                code="GHL_CONTEXT_DECRYPT_FAILED",
                hint=(
                    "Verify GO_HIGH_LEVEL_APP_SHARED_SECRET matches the Shared Secret "
                    "on the same Marketplace app/version that renders the custom page."
                ),
                cause=exc,
            ) from exc

        if not isinstance(parsed, dict):
            raise ValidationError(
                "The decrypted GoHighLevel user context payload is not a JSON object.",
                code="GHL_CONTEXT_INVALID_JSON",
            )

        return parsed


def extract_gohighlevel_user_context_fields(user_data: dict[str, Any]) -> dict[str, str]:
    return {
        "location_id": str(
            user_data.get("activeLocation")
            or user_data.get("locationId")
            or user_data.get("location_id")
            or ""
        ).strip(),
        "user_id": str(
            user_data.get("userId")
            or user_data.get("user_id")
            or user_data.get("id")
            or ""
        ).strip(),
        "user_name": str(user_data.get("userName") or user_data.get("user_name") or "").strip(),
        "email": str(user_data.get("email") or "").strip(),
        "company_id": str(user_data.get("companyId") or user_data.get("company_id") or "").strip(),
        "type": str(user_data.get("type") or "").strip(),
        "role": str(user_data.get("role") or "").strip(),
    }


def _derive_cryptojs_key_and_iv(*, password: bytes, salt: bytes) -> tuple[bytes, bytes]:
    derived = b""
    previous = b""
    while len(derived) < 48:
        previous = hashlib.md5(previous + password + salt).digest()  # noqa: S324
        derived += previous
    return derived[:32], derived[32:48]


__all__ = [
    "DecodeSessionContextUseCase",
    "extract_gohighlevel_user_context_fields",
]
