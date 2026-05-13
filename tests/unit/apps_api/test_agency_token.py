"""Unit tests for ``apps.api.agency_token``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from apps.api.agency_token import (
    AgencyTokenExpired,
    AgencyTokenInvalid,
    decode_agency_token,
    issue_agency_token,
)


def test_issue_and_decode_round_trip() -> None:
    secret = "test-secret"
    now = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    token, expires_at = issue_agency_token(
        agency_id="agency-1",
        location_id="loc-1",
        user_id="user-1",
        secret=secret,
        ttl_seconds=3600,
        now=now,
    )

    assert isinstance(token, str) and token
    assert expires_at == now + timedelta(seconds=3600)

    claims = decode_agency_token(token, secret=secret, now=now)
    assert claims.agency_id == "agency-1"
    assert claims.location_id == "loc-1"
    assert claims.user_id == "user-1"
    assert claims.scope == "agency"
    assert claims.jti
    assert claims.issued_at == now
    assert claims.expires_at == expires_at


def test_decode_raises_expired_when_token_past_exp() -> None:
    secret = "test-secret"
    now = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    token, _expires = issue_agency_token(
        agency_id="agency-1",
        location_id="loc-1",
        user_id="user-1",
        secret=secret,
        ttl_seconds=60,
        now=now,
    )

    later = now + timedelta(seconds=120)
    with pytest.raises(AgencyTokenExpired):
        decode_agency_token(token, secret=secret, now=later)


def test_decode_raises_invalid_when_signature_does_not_match() -> None:
    token, _expires = issue_agency_token(
        agency_id="agency-1",
        location_id="loc-1",
        user_id="user-1",
        secret="real-secret",
        ttl_seconds=3600,
    )

    with pytest.raises(AgencyTokenInvalid):
        decode_agency_token(token, secret="other-secret")


def test_decode_rejects_tokens_signed_with_different_algorithm() -> None:
    """Defence against an attacker swapping the alg to ``none`` or HS512."""
    payload = {
        "iss": "4reels-back",
        "sub": "user-1",
        "agency_id": "agency-1",
        "location_id": "loc-1",
        "scope": "agency",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "jti": "deadbeef",
    }
    # PyJWT 2.x rejects ``alg=none`` by default at encode time, so we use
    # HS512 — a different valid algorithm — and expect ``decode`` to refuse it
    # because we only allowed HS256.
    forged = jwt.encode(payload, "test-secret", algorithm="HS512")
    with pytest.raises(AgencyTokenInvalid):
        decode_agency_token(forged, secret="test-secret")


def test_decode_rejects_token_missing_required_claims() -> None:
    payload = {
        "iss": "4reels-back",
        "sub": "user-1",
        # missing agency_id, location_id, scope, jti, exp, iat
    }
    forged = jwt.encode(payload, "test-secret", algorithm="HS256")
    with pytest.raises(AgencyTokenInvalid):
        decode_agency_token(forged, secret="test-secret")


def test_decode_rejects_alg_none_token() -> None:
    """Forge a JWT with ``alg=none`` and verify it is rejected.

    PyJWT's ``encode`` refuses ``algorithm="none"`` since 2.x, so we craft the
    token manually: ``base64url(header).base64url(payload).`` with an empty
    signature segment is a valid alg=none JWT. ``decode_agency_token`` must
    reject it because the call only allows HS256.
    """
    import base64

    def _b64url(payload_bytes: bytes) -> str:
        return base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")

    header = {"alg": "none", "typ": "JWT"}
    body = {
        "iss": "4reels-back",
        "sub": "user-1",
        "agency_id": "agency-1",
        "location_id": "loc-1",
        "scope": "agency",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "jti": "deadbeef",
    }
    import json as _json

    encoded_header = _b64url(_json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_body = _b64url(_json.dumps(body, separators=(",", ":")).encode("utf-8"))
    forged = f"{encoded_header}.{encoded_body}."

    with pytest.raises(AgencyTokenInvalid):
        decode_agency_token(forged, secret="test-secret")


def test_decode_rejects_token_with_non_agency_scope() -> None:
    """A JWT signed with our secret but with ``scope!=agency`` is invalid."""
    payload = {
        "iss": "4reels-back",
        "sub": "user-1",
        "agency_id": "agency-1",
        "location_id": "loc-1",
        "scope": "super-admin",  # wrong scope
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "jti": "deadbeef",
    }
    forged = jwt.encode(payload, "test-secret", algorithm="HS256")
    with pytest.raises(AgencyTokenInvalid):
        decode_agency_token(forged, secret="test-secret")


def test_decode_rejects_token_with_wrong_issuer() -> None:
    """A JWT with ``iss != '4reels-back'`` is rejected even when otherwise valid."""
    payload = {
        "iss": "some-other-issuer",
        "sub": "user-1",
        "agency_id": "agency-1",
        "location_id": "loc-1",
        "scope": "agency",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "jti": "deadbeef",
    }
    forged = jwt.encode(payload, "test-secret", algorithm="HS256")
    with pytest.raises(AgencyTokenInvalid):
        decode_agency_token(forged, secret="test-secret")


def test_issue_requires_non_empty_secret() -> None:
    with pytest.raises(AgencyTokenInvalid):
        issue_agency_token(
            agency_id="agency-1",
            location_id="loc-1",
            user_id="user-1",
            secret="",
            ttl_seconds=3600,
        )


def test_decode_requires_non_empty_token_and_secret() -> None:
    with pytest.raises(AgencyTokenInvalid):
        decode_agency_token("", secret="test-secret")
    token, _ = issue_agency_token(
        agency_id="agency-1",
        location_id="loc-1",
        user_id="user-1",
        secret="test-secret",
        ttl_seconds=3600,
    )
    with pytest.raises(AgencyTokenInvalid):
        decode_agency_token(token, secret="")
