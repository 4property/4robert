"""Host filter and docs gating helpers for the API process.

These helpers were moved here from
``services/transport/http/server.py`` when feature 9 retired the god-class.
They power three responsibilities:

- ``resolve_allowed_hosts(...)``: build the ordered tuple of hostnames that
  ``starlette.middleware.trustedhost.TrustedHostMiddleware`` should accept.
- ``should_enable_docs(...)``: decide whether ``/docs`` and ``/openapi.json``
  are exposed in this environment (production gating).
- ``looks_like_hostname(...)`` / ``normalise_allowed_host(...)``: shared
  primitives used by both helpers above and by the webhook layer when
  resolving site identifiers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from urllib.parse import urlparse


def resolve_allowed_hosts(
    *,
    allowed_hosts: Iterable[str],
    site_secrets: Mapping[str, str],
) -> tuple[str, ...]:
    """Return the deduplicated ordered tuple of hosts to trust.

    The configured ``WEBHOOK_ALLOWED_HOSTS`` come first, followed by any
    ``site_id`` values from ``WEBHOOK_SITE_SECRETS`` that look like
    hostnames (so per-tenant webhooks pass the trusted-host check), and
    finally ``127.0.0.1`` and ``localhost`` for local tooling. Duplicates
    are removed case-insensitively while preserving the first occurrence.
    """
    candidates: list[str] = []
    candidates.extend(allowed_hosts or ())
    candidates.extend(
        site_id for site_id in (site_secrets or {}) if looks_like_hostname(site_id)
    )
    candidates.extend(("127.0.0.1", "localhost"))

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized_candidate = normalise_allowed_host(candidate)
        if not normalized_candidate:
            continue
        lowered = normalized_candidate.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(normalized_candidate)
    return tuple(normalized)


def should_enable_docs(*, host: str, enable_docs: bool) -> bool:
    """Return True when the environment may safely expose ``/docs``."""
    if enable_docs:
        return True
    return is_local_docs_host(host)


def is_local_docs_host(host: str) -> bool:
    """Return True when the configured host is local-only (``127.0.0.1``, ``localhost``, ``::1``)."""
    normalized_host = str(host or "").strip().lower()
    if not normalized_host:
        return False
    if "://" in normalized_host:
        parsed = urlparse(normalized_host)
        normalized_host = parsed.hostname or parsed.path or ""
    if normalized_host.startswith("[") and normalized_host.endswith("]"):
        normalized_host = normalized_host[1:-1]
    return normalized_host in {"127.0.0.1", "localhost", "::1"}


def normalise_allowed_host(value: str) -> str | None:
    """Strip schemes, paths and explicit ports from a candidate hostname."""
    raw_value = str(value or "").strip().lower()
    if not raw_value:
        return None
    if raw_value == "*":
        return raw_value
    if "://" in raw_value:
        parsed = urlparse(raw_value)
        raw_value = parsed.hostname or parsed.path or ""
    else:
        raw_value = raw_value.split("/", 1)[0]
        if raw_value.count(":") == 1 and raw_value not in {"localhost", "127.0.0.1"}:
            raw_value = raw_value.split(":", 1)[0]
    return raw_value or None


def looks_like_hostname(value: str) -> bool:
    """Return True when ``value`` looks like a hostname (``foo.bar``, ``localhost``, ``*.foo``)."""
    normalized_value = normalise_allowed_host(value)
    if not normalized_value:
        return False
    return (
        normalized_value in {"localhost", "127.0.0.1"}
        or normalized_value.startswith("*.")
        or "." in normalized_value
    )


__all__ = [
    "is_local_docs_host",
    "looks_like_hostname",
    "normalise_allowed_host",
    "resolve_allowed_hosts",
    "should_enable_docs",
]
