"""Admin bearer-token authorization helper for the API process.

Two kinds of tokens are accepted by ``/v1/admin/*`` endpoints:

* **Super-admin** — the static ``ADMIN_API_TOKEN``. Compared in constant
  time. Allowed on every admin route, including the global routes such as
  ``/v1/admin/agencies`` and ``/v1/admin/wordpress-sources``.
* **Agency-scoped JWT** — minted by ``POST /v1/sessions/gohighlevel/session``
  (HS256, see :mod:`apps.api.agency_token`). Allowed only on routes whose
  path matches ``/v1/admin/agencies/{agency_id}/...`` and whose ``agency_id``
  in the URL equals the ``agency_id`` claim in the token.

The matrix is documented in
``progress/explore_feature_5_back_auth.md`` §2.4.
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

from shared.observability import (
    format_console_block,
    format_detail_line,
    log_persistent_event,
)

from apps.api.agency_token import (
    AgencyTokenClaims,
    AgencyTokenExpired,
    AgencyTokenInvalid,
    decode_agency_token,
)
from apps.api.error_handlers import json_error

logger = logging.getLogger(__name__)


_AGENCY_ID_RE = re.compile(
    r"^/v1/admin/agencies/(?P<agency_id>[0-9a-fA-F-]{1,64})(?:/|$)"
)


@dataclass(frozen=True, slots=True)
class AdminAccessPolicy:
    """Configuration for the admin API authorization layer."""

    enabled: bool
    base_path: str
    bearer_token: str
    disable_auth_for_testing: bool
    agency_token_secret: str = ""
    agency_token_ttl_seconds: int = 3600


def build_admin_access_policy(
    *,
    enabled: bool,
    base_path: str,
    bearer_token: str | None,
    disable_auth_for_testing: bool,
    agency_token_secret: str | None = None,
    agency_token_ttl_seconds: int | None = None,
) -> AdminAccessPolicy:
    """Build the admin access policy used by every admin-scoped router.

    Wraps the dataclass constructor with normalisation: the bearer token is
    coerced to a string (an unset env var arrives as ``None``), and the
    base path is taken verbatim. ``agency_token_secret``/``agency_token_ttl_seconds``
    were added in feature 5 (frontend admin auth lockstep) so the
    agency-scoped JWT branch of :func:`authorize_admin_request` can be
    configured without globals.
    """
    return AdminAccessPolicy(
        enabled=bool(enabled),
        base_path=str(base_path),
        bearer_token=str(bearer_token or ""),
        disable_auth_for_testing=bool(disable_auth_for_testing),
        agency_token_secret=str(agency_token_secret or ""),
        agency_token_ttl_seconds=int(
            agency_token_ttl_seconds if agency_token_ttl_seconds is not None else 3600
        ),
    )


def extract_bearer_token(header_value: str | None) -> str | None:
    """Return the `<token>` part of an `Authorization: Bearer <token>` header."""
    normalized_value = str(header_value or "").strip()
    if not normalized_value:
        return None
    parts = normalized_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def format_client(request: Request) -> str:
    """Render the request peer as `host:port` for log lines."""
    if request.client is None:
        return "<unknown>"
    return f"{request.client.host}:{request.client.port}"


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    if value in (None, ""):
        return None
    return str(value)


def _extract_path_agency_id(path: str) -> str | None:
    """Extract the ``{agency_id}`` segment from ``/v1/admin/agencies/{id}/...``.

    Returns ``None`` for global admin paths such as ``/v1/admin/agencies``
    (list/create), ``/v1/admin/wordpress-sources`` and any other route that
    does not address a specific agency. Agency-scoped JWTs are forbidden on
    those paths.
    """
    if not path:
        return None
    match = _AGENCY_ID_RE.match(path)
    if not match:
        return None
    agency_id = match.group("agency_id").strip()
    return agency_id or None


def authorize_admin_request(
    request: Request,
    policy: AdminAccessPolicy,
) -> JSONResponse | None:
    """Validate the admin bearer token. Return a JSON error or `None` if allowed."""
    request_id = _request_id(request)
    if not policy.enabled:
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=format_client(request),
            reason="disabled",
            path=request.url.path,
        )
        return json_error(
            404,
            "The admin API is disabled.",
            code="ADMIN_API_DISABLED",
            hint="Enable ADMIN_API_ENABLED before using the admin management endpoints.",
            details={"request_id": request_id, "path": request.url.path},
        )

    if policy.disable_auth_for_testing:
        logger.warning(
            format_console_block(
                "Admin Authentication Bypassed For Testing",
                format_detail_line("Request ID", request_id or "<unknown>"),
                format_detail_line("Client", format_client(request)),
                format_detail_line("Path", request.url.path),
                "The request was allowed without verifying an admin bearer token.",
            )
        )
        log_persistent_event(
            "admin.authorization_bypassed_for_testing",
            request_id=request_id,
            client=format_client(request),
            path=request.url.path,
        )
        return None

    if not policy.bearer_token and not policy.agency_token_secret:
        logger.warning(
            format_console_block(
                "Admin API Not Configured",
                format_detail_line("Request ID", request_id or "<unknown>"),
                format_detail_line("Client", format_client(request)),
                format_detail_line("Path", request.url.path),
                "Set ADMIN_API_TOKEN before exposing the admin endpoints.",
            )
        )
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=format_client(request),
            reason="not_configured",
            path=request.url.path,
        )
        return json_error(
            503,
            "The admin API is not configured.",
            code="ADMIN_API_NOT_CONFIGURED",
            hint=(
                "Set ADMIN_API_TOKEN in the environment and restart the service "
                "before using the admin endpoints."
            ),
            details={"request_id": request_id, "path": request.url.path},
        )

    provided_token = extract_bearer_token(request.headers.get("Authorization"))
    if not provided_token:
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=format_client(request),
            reason="missing_bearer_token",
            path=request.url.path,
        )
        return json_error(
            401,
            "Admin authentication is required.",
            code="ADMIN_AUTH_REQUIRED",
            hint="Send Authorization: Bearer <ADMIN_API_TOKEN> on admin requests.",
            details={"request_id": request_id, "path": request.url.path},
        )

    if policy.bearer_token and secrets.compare_digest(
        provided_token, policy.bearer_token
    ):
        return None

    if not policy.agency_token_secret:
        return _reject_invalid_admin_token(request, request_id)

    try:
        claims = decode_agency_token(
            provided_token,
            secret=policy.agency_token_secret,
        )
    except AgencyTokenExpired:
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=format_client(request),
            reason="agency_token_expired",
            path=request.url.path,
        )
        return _reject_invalid_admin_token(request, request_id, log=False)
    except AgencyTokenInvalid:
        return _reject_invalid_admin_token(request, request_id)

    if claims.scope != "agency":
        return _reject_invalid_admin_token(request, request_id)

    path_agency_id = _extract_path_agency_id(request.url.path)
    if path_agency_id is None:
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=format_client(request),
            reason="agency_global_route",
            path=request.url.path,
            agency_id=claims.agency_id,
        )
        return json_error(
            403,
            "Agency tokens cannot access global admin routes.",
            code="AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE",
            hint=(
                "Use the platform super-admin token for routes that are not "
                "scoped to a single agency."
            ),
            details={"request_id": request_id, "path": request.url.path},
        )

    if path_agency_id != claims.agency_id:
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=format_client(request),
            reason="agency_mismatch",
            path=request.url.path,
            agency_id=claims.agency_id,
            path_agency_id=path_agency_id,
        )
        return json_error(
            403,
            "The agency token does not match the requested agency.",
            code="AGENCY_TOKEN_AGENCY_MISMATCH",
            hint=(
                "Issue a fresh session token for the target agency or use the "
                "platform super-admin token."
            ),
            details={"request_id": request_id, "path": request.url.path},
        )

    _annotate_request_state(request, claims)
    return None


def _annotate_request_state(request: Request, claims: AgencyTokenClaims) -> None:
    """Stamp the resolved agency id on ``request.state`` for downstream logs."""
    try:
        request.state.agency_id = claims.agency_id
    except Exception:  # pragma: no cover - request.state should always exist
        pass


def _reject_invalid_admin_token(
    request: Request,
    request_id: str | None,
    *,
    log: bool = True,
) -> JSONResponse:
    if log:
        logger.warning(
            format_console_block(
                "Admin Authentication Failed",
                format_detail_line("Request ID", request_id or "<unknown>"),
                format_detail_line("Client", format_client(request)),
                format_detail_line("Path", request.url.path),
                "The provided admin bearer token is invalid.",
            )
        )
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=format_client(request),
            reason="invalid_bearer_token",
            path=request.url.path,
        )
    return json_error(
        401,
        "The admin bearer token is invalid.",
        code="INVALID_ADMIN_TOKEN",
        hint=(
            "Send the token configured in ADMIN_API_TOKEN, or a fresh agency "
            "token from POST /v1/sessions/gohighlevel/session."
        ),
        details={"request_id": request_id, "path": request.url.path},
    )


__all__ = [
    "AdminAccessPolicy",
    "authorize_admin_request",
    "build_admin_access_policy",
    "extract_bearer_token",
    "format_client",
]
