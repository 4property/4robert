"""Agency-scoped JWT (HS256) issuance and validation.

Stateless tokens emitted by ``POST /v1/sessions/gohighlevel/session`` when a
GoHighLevel location has an agency connected. The frontend stores the token
in memory/sessionStorage and sends it as ``Authorization: Bearer <jwt>`` when
hitting ``/v1/admin/agencies/{agency_id}/...`` endpoints.

The module deliberately stays decoupled from FastAPI — it owns the JWT
contract (claims shape, algorithm, issuer) and re-raises every PyJWT
exception as one of the project's own ``AgencyTokenError`` subclasses so
``apps/api/admin_auth.py`` does not have to import ``jwt`` directly.

See ``progress/explore_feature_5_back_auth.md`` §2 for the rationale (JWT
HS256 stateless, no ``agency_sessions`` table, TTL 3600s default).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

_ALGORITHM = "HS256"
_ISSUER = "4reels-back"
_SCOPE = "agency"


class AgencyTokenError(Exception):
    """Base class for any failure decoding an agency-scoped JWT."""


class AgencyTokenExpired(AgencyTokenError):
    """The agency token's ``exp`` claim is in the past."""


class AgencyTokenInvalid(AgencyTokenError):
    """The token signature, structure or required claim shape is invalid."""


@dataclass(frozen=True, slots=True)
class AgencyTokenClaims:
    agency_id: str
    location_id: str
    user_id: str
    scope: str
    jti: str
    issued_at: datetime
    expires_at: datetime


def issue_agency_token(
    *,
    agency_id: str,
    location_id: str,
    user_id: str,
    secret: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Mint a new agency-scoped JWT and return ``(token, expires_at)``.

    The token is signed with HS256 using ``secret``. ``expires_at`` is
    timezone-aware UTC so the caller can serialise it as ISO-8601 without
    further wrangling.
    """
    if not secret:
        raise AgencyTokenInvalid("An agency token secret is required to issue a token.")
    if ttl_seconds <= 0:
        raise AgencyTokenInvalid("ttl_seconds must be positive.")

    issued_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires_at = issued_at + timedelta(seconds=int(ttl_seconds))
    jti = uuid4().hex

    payload = {
        "iss": _ISSUER,
        "sub": str(user_id or "").strip(),
        "agency_id": str(agency_id or "").strip(),
        "location_id": str(location_id or "").strip(),
        "scope": _SCOPE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
    }
    token = jwt.encode(payload, secret, algorithm=_ALGORITHM)
    return token, expires_at


def decode_agency_token(
    token: str,
    *,
    secret: str,
    now: datetime | None = None,
) -> AgencyTokenClaims:
    """Validate and decode an agency-scoped JWT.

    Raises :class:`AgencyTokenExpired` when the token is past its ``exp``
    claim, :class:`AgencyTokenInvalid` for any other failure (bad signature,
    wrong algorithm, malformed claims, missing required fields, mismatched
    issuer). PyJWT exceptions never escape this module.
    """
    if not token:
        raise AgencyTokenInvalid("An agency token is required.")
    if not secret:
        raise AgencyTokenInvalid("An agency token secret is required to decode a token.")

    decode_kwargs: dict[str, object] = {
        "algorithms": [_ALGORITHM],
        "issuer": _ISSUER,
        # ``iat`` is informational; disable PyJWT's not-yet-valid check so a
        # token issued slightly ahead of the verifier's clock (or with a
        # caller-supplied ``now``) is accepted as long as ``exp`` still holds.
        "options": {
            "require": ["exp", "iat", "iss", "sub", "jti"],
            "verify_iat": False,
        },
    }
    if now is not None:
        # PyJWT does not accept a ``now`` override directly; we replicate the
        # behaviour by disabling its ``exp`` check and re-validating below
        # against ``now``.
        decode_kwargs["options"] = {
            "require": ["exp", "iat", "iss", "sub", "jti"],
            "verify_exp": False,
            "verify_iat": False,
        }

    try:
        payload = jwt.decode(token, secret, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise AgencyTokenExpired("The agency token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AgencyTokenInvalid(str(exc) or "The agency token is invalid.") from exc
    except Exception as exc:  # pragma: no cover - defensive net
        raise AgencyTokenInvalid("The agency token is invalid.") from exc

    try:
        agency_id = str(payload["agency_id"]).strip()
        location_id = str(payload["location_id"]).strip()
        user_id = str(payload["sub"]).strip()
        scope = str(payload["scope"]).strip()
        jti = str(payload["jti"]).strip()
        issued_at = datetime.fromtimestamp(int(payload["iat"]), tz=timezone.utc)
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise AgencyTokenInvalid("The agency token is missing required claims.") from exc

    if not agency_id or not location_id or not user_id or not scope or not jti:
        raise AgencyTokenInvalid("The agency token has empty required claims.")

    if scope != _SCOPE:
        raise AgencyTokenInvalid("The agency token has an unexpected scope.")

    if now is not None:
        reference = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
        if expires_at <= reference:
            raise AgencyTokenExpired("The agency token has expired.")

    return AgencyTokenClaims(
        agency_id=agency_id,
        location_id=location_id,
        user_id=user_id,
        scope=scope,
        jti=jti,
        issued_at=issued_at,
        expires_at=expires_at,
    )


__all__ = [
    "AgencyTokenClaims",
    "AgencyTokenError",
    "AgencyTokenExpired",
    "AgencyTokenInvalid",
    "decode_agency_token",
    "issue_agency_token",
]
