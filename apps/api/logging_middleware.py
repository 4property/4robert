"""HTTP request/response logging middleware for the API process."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI, Request

from shared.observability import log_persistent_event

logger = logging.getLogger(__name__)

DEFAULT_SENSITIVE_HEADER_NAMES: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "set-cookie",
        "x-ghl-token",
        "x-gohighlevel-access-token",
        "x-wordpress-signature",
    }
)
DEFAULT_SENSITIVE_BODY_FIELDS: frozenset[str] = frozenset(
    {
        "access_token",
        "refresh_token",
        "token",
        "encrypted_data",
        "encryptedData",
        "client_secret",
        "authorization",
    }
)


def _format_client(request: Request) -> str:
    if request.client is None:
        return "<unknown>"
    return f"{request.client.host}:{request.client.port}"


def sanitize_headers_for_logging(
    headers: Any,
    *,
    sensitive_header_names: Iterable[str] = DEFAULT_SENSITIVE_HEADER_NAMES,
) -> dict[str, str]:
    """Return a header dict with sensitive values replaced by `<redacted>`."""
    sensitive = frozenset(name.lower() for name in sensitive_header_names)
    normalized_headers: dict[str, str] = {}
    for key, value in headers.items():
        normalized_key = str(key)
        lowered_key = normalized_key.lower()
        normalized_headers[normalized_key] = (
            "<redacted>" if lowered_key in sensitive else str(value)
        )
    return normalized_headers


def _redact_sensitive_json_values(
    value: object,
    *,
    sensitive_body_fields: frozenset[str],
) -> object:
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if str(key).strip().lower() in sensitive_body_fields
                else _redact_sensitive_json_values(item, sensitive_body_fields=sensitive_body_fields)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_sensitive_json_values(item, sensitive_body_fields=sensitive_body_fields)
            for item in value
        ]
    return value


def decode_body_for_logging(
    raw_body: bytes | None,
    *,
    sensitive_body_fields: Iterable[str] = DEFAULT_SENSITIVE_BODY_FIELDS,
) -> str | None:
    """Decode a request/response body for the persistent log, redacting secrets."""
    if not raw_body:
        return None
    sensitive = frozenset(field.strip().lower() for field in sensitive_body_fields)
    raw_text = raw_body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text
    redacted = _redact_sensitive_json_values(parsed, sensitive_body_fields=sensitive)
    return json.dumps(redacted, ensure_ascii=False)


def extract_response_body(response: object) -> bytes | None:
    body = getattr(response, "body", None)
    if body is None:
        return None
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, str):
        return body.encode("utf-8", errors="replace")
    return str(body).encode("utf-8", errors="replace")


def rebuild_request_with_body(request: Request, raw_body: bytes) -> Request:
    """Return a new `Request` whose ASGI receive replays `raw_body`."""

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": raw_body, "more_body": False}

    return Request(request.scope, receive)


def register_logging_middleware(app: FastAPI) -> None:
    """Install the persistent HTTP traffic middleware on `app`.

    The middleware emits three persistent events per request:

    * `http.request` — method, path, query, client, sanitised headers and body.
    * `http.response` — status code, duration, sanitised headers and body.
    * `http.exception` — only when the downstream handler raised.

    It also assigns `request.state.request_id` so downstream code (admin
    auth, error handlers, route handlers) can correlate log lines.
    """

    @app.middleware("http")
    async def persist_http_traffic(request: Request, call_next):  # type: ignore[no-untyped-def]
        started_at = time.perf_counter()
        request_id = str(time.time_ns())
        raw_body = b""
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            raw_body = await request.body()
            request = rebuild_request_with_body(request, raw_body)
        request.state.request_id = request_id

        log_persistent_event(
            "http.request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            client=_format_client(request),
            headers=sanitize_headers_for_logging(request.headers),
            body=decode_body_for_logging(raw_body),
            body_size_bytes=len(raw_body),
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            log_persistent_event(
                "http.exception",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                query=request.url.query,
                client=_format_client(request),
                duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise

        response_body = extract_response_body(response)
        log_persistent_event(
            "http.response",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
            headers=sanitize_headers_for_logging(response.headers),
            body=decode_body_for_logging(response_body),
            body_size_bytes=(len(response_body) if response_body is not None else None),
        )
        return response


__all__ = [
    "DEFAULT_SENSITIVE_BODY_FIELDS",
    "DEFAULT_SENSITIVE_HEADER_NAMES",
    "decode_body_for_logging",
    "extract_response_body",
    "rebuild_request_with_body",
    "register_logging_middleware",
    "sanitize_headers_for_logging",
]
