"""HMAC verification helpers for inbound webhooks.

Pure functions, no I/O. Moved from `services/transport/http/security.py` so the
ingestion module can share them without crossing layer boundaries.

The signed message includes `location_id` and `access_token` (defaults
empty strings) for backward compatibility with the WordPress sender that
predates Phase 1. Changing the formula breaks signatures in production.
"""

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


def verify_webhook_signature(
    *,
    secret: str,
    timestamp: str,
    site_id: str,
    raw_body: bytes,
    signature: str,
    tolerance_seconds: int,
    location_id: str = "",
    access_token: str = "",
    now: int | None = None,
) -> tuple[bool, str | None, str | None]:
    """One-shot HMAC + timestamp validation.

    Returns ``(ok, message, hint)``. ``message`` and ``hint`` are populated
    only on failure so the caller can surface them in the HTTP response.
    """
    if not is_timestamp_fresh(timestamp, tolerance_seconds=tolerance_seconds, now=now):
        return (
            False,
            "The webhook timestamp is outside the accepted tolerance window.",
            (
                "Check clock drift between WordPress and the API host or "
                "increase WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS if needed."
            ),
        )
    signature_valid = is_signature_valid(
        secret=secret,
        timestamp=timestamp,
        site_id=site_id,
        location_id=location_id,
        access_token=access_token,
        raw_body=raw_body,
        signature=signature,
    )
    if not signature_valid:
        return (
            False,
            "The webhook signature does not match the configured site secret.",
            (
                "Ensure WordPress signs the raw JSON body with the same secret "
                "and the same header values received by this service."
            ),
        )
    return True, None, None


__all__ = [
    "build_raw_payload_hash",
    "build_signature",
    "is_signature_valid",
    "is_timestamp_fresh",
    "verify_webhook_signature",
]
