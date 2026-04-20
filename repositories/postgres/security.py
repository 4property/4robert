from __future__ import annotations

from cryptography.fernet import Fernet

from config import DATABASE_ENCRYPTION_KEY


def _fernet() -> Fernet:
    return Fernet(DATABASE_ENCRYPTION_KEY.encode("utf-8"))


def encrypt_text(value: str) -> bytes:
    normalized_value = str(value or "")
    if not normalized_value:
        return b""
    return _fernet().encrypt(normalized_value.encode("utf-8"))


def decrypt_text(value: bytes | bytearray | memoryview | None) -> str:
    if not value:
        return ""
    return _fernet().decrypt(bytes(value)).decode("utf-8")


__all__ = ["decrypt_text", "encrypt_text"]
