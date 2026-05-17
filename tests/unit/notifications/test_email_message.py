"""Shape + immutability of :class:`EmailMessage` / :class:`SentEmail`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shared.email import EmailMessage, SentEmail


def test_email_message_defaults_to_text_only_envelope() -> None:
    message = EmailMessage(
        to=("a@example.com", "b@example.com"),
        subject="Subject",
        body_text="hello",
        from_address="notifications@4reels.ie",
    )
    assert message.body_html is None
    assert message.from_name is None
    assert message.reply_to is None
    assert message.headers is None


def test_email_message_accepts_full_envelope() -> None:
    message = EmailMessage(
        to=("a@example.com",),
        subject="Subject",
        body_text="hello",
        from_address="notifications@4reels.ie",
        body_html="<p>hello</p>",
        from_name="4Reels Notifications",
        reply_to="ops@4pm.ie",
        headers={"X-4Reels-Event": "review_requested"},
    )
    assert message.body_html == "<p>hello</p>"
    assert message.from_name == "4Reels Notifications"
    assert message.reply_to == "ops@4pm.ie"
    assert message.headers == {"X-4Reels-Event": "review_requested"}


def test_email_message_is_immutable() -> None:
    message = EmailMessage(
        to=("a@example.com",),
        subject="Subject",
        body_text="hello",
        from_address="notifications@4reels.ie",
    )
    with pytest.raises(AttributeError):
        message.subject = "Other"  # type: ignore[misc]


def test_sent_email_carries_provider_id_and_recipients() -> None:
    timestamp = datetime.now(timezone.utc)
    sent = SentEmail(
        provider_message_id="<abc@example.com>",
        recipients=("a@example.com",),
        sent_at=timestamp,
    )
    assert sent.provider_message_id == "<abc@example.com>"
    assert sent.recipients == ("a@example.com",)
    assert sent.sent_at is timestamp
