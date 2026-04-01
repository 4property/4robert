from __future__ import annotations

from settings.app import APP_SETTINGS


OUTBOUND_HTTP_TIMEOUT_SECONDS = APP_SETTINGS.outbound_http_timeout_seconds
HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; CPIHED/1.0)",
}


__all__ = [
    "HTTP_HEADERS",
    "OUTBOUND_HTTP_TIMEOUT_SECONDS",
]
