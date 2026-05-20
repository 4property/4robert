"""Unit tests for agent contact resolution in ``Property.from_api_payload``.

Covers the precedence rule for ``agent_mobile`` (explicit > ``agent_phone``),
the discarding of non-email values in ``agent_email``, and the defensive
promotion of a malformed email-shaped-as-phone to ``agent_mobile`` when no
other phone slot was supplied. Triggered by a real-world Century 21 webhook
where the source put the agent phone under ``agent_phone`` *and* repeated
it inside ``agent_email``.
"""

from __future__ import annotations

from modules.catalog.domain.wordpress_property import Property


def test_from_payload_uses_agent_mobile_when_present() -> None:
    payload = {"id": 1, "slug": "p", "agent_mobile": "111", "agent_phone": "222"}
    prop = Property.from_api_payload(payload)

    assert prop.agent_mobile == "111"
    assert prop.agent_email is None
    assert prop.agent_number is None


def test_from_payload_falls_back_to_agent_phone_when_mobile_missing() -> None:
    payload = {"id": 1, "slug": "p", "agent_phone": "843 300 7077"}
    prop = Property.from_api_payload(payload)

    assert prop.agent_mobile == "843 300 7077"
    assert prop.agent_email is None


def test_from_payload_discards_malformed_email_without_at_sign() -> None:
    payload = {"id": 1, "slug": "p", "agent_email": "(843) 300 7077"}
    prop = Property.from_api_payload(payload)

    assert prop.agent_email is None
    # Defensive promotion: no agent_phone/agent_mobile, but the email-shaped
    # field contained 6+ digits, so it backfills agent_mobile.
    assert prop.agent_mobile == "(843) 300 7077"


def test_from_payload_preserves_valid_email() -> None:
    payload = {"id": 1, "slug": "p", "agent_email": "agent@example.com"}
    prop = Property.from_api_payload(payload)

    assert prop.agent_email == "agent@example.com"
    assert prop.agent_mobile is None


def test_from_payload_real_world_dev76_property_1234() -> None:
    """Reproduces the bug report payload (Suzanne Russo / Century 21)."""

    payload = {
        "id": 1234,
        "slug": "dev76-1234",
        "agent_name": "Suzanne Russo",
        "agent_phone": "843 300 7077",
        "agent_email": "(843) 300 7077",
    }
    prop = Property.from_api_payload(payload)

    assert prop.agent_name == "Suzanne Russo"
    assert prop.agent_mobile == "843 300 7077"
    assert prop.agent_email is None


def test_from_payload_explicit_mobile_blocks_email_promotion() -> None:
    """If the operator filled agent_mobile, do NOT touch agent_email's value
    (still discarded if invalid, but no promotion happens).
    """

    payload = {
        "id": 1,
        "slug": "p",
        "agent_mobile": "555 111 2222",
        "agent_email": "(843) 300 7077",
    }
    prop = Property.from_api_payload(payload)

    assert prop.agent_mobile == "555 111 2222"
    assert prop.agent_email is None


def test_from_payload_does_not_promote_short_digit_string() -> None:
    """A non-email value with fewer than 6 digits is just dropped — it is
    almost certainly not a phone number we want to render."""

    payload = {"id": 1, "slug": "p", "agent_email": "ABC-12"}
    prop = Property.from_api_payload(payload)

    assert prop.agent_email is None
    assert prop.agent_mobile is None


def test_from_payload_preserves_agent_number_independently() -> None:
    payload = {
        "id": 1,
        "slug": "p",
        "agent_phone": "111 222 3333",
        "agent_number": "01 555 0000",
    }
    prop = Property.from_api_payload(payload)

    assert prop.agent_mobile == "111 222 3333"
    assert prop.agent_number == "01 555 0000"
