from __future__ import annotations

import hashlib
import hmac
import time


def build_raw_payload_hash(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def _build_signature_message(
    *,
    timestamp: str,
    site_id: str,
    location_id: str,
    access_token: str,
    raw_body: bytes,
) -> bytes:
    return (
        timestamp.encode("utf-8")
        + b"\n"
        + site_id.encode("utf-8")
        + b"\n"
        + location_id.encode("utf-8")
        + b"\n"
        + access_token.encode("utf-8")
        + b"\n"
        + raw_body
    )


def build_signature(
    secret: str,
    timestamp: str,
    site_id: str,
    location_id: str,
    access_token: str,
    raw_body: bytes,
) -> str:
    message = _build_signature_message(
        timestamp=timestamp,
        site_id=site_id,
        location_id=location_id,
        access_token=access_token,
        raw_body=raw_body,
    )
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def is_signature_valid(
    *,
    secret: str,
    timestamp: str,
    site_id: str,
    location_id: str,
    access_token: str,
    raw_body: bytes,
    signature: str,
) -> bool:
    expected_signature = build_signature(
        secret,
        timestamp,
        site_id,
        location_id,
        access_token,
        raw_body,
    )
    return hmac.compare_digest(expected_signature, signature)


def is_timestamp_fresh(timestamp: str, *, tolerance_seconds: int, now: int | None = None) -> bool:
    try:
        timestamp_value = int(timestamp)
    except ValueError:
        return False

    current_time = int(time.time()) if now is None else int(now)
    return abs(current_time - timestamp_value) <= tolerance_seconds


__all__ = [
    "build_raw_payload_hash",
    "build_signature",
    "is_signature_valid",
    "is_timestamp_fresh",
]
