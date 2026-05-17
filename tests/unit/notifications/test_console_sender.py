"""Behavioural tests for :class:`ConsoleEmailSender`."""

from __future__ import annotations

import io
import sys
from datetime import datetime, timezone

from shared.email import ConsoleEmailSender, EmailMessage


def test_console_sender_prints_message_with_prefix_and_returns_sent_email() -> None:
    stream = io.StringIO()
    sender = ConsoleEmailSender(stream=stream)
    message = EmailMessage(
        to=("a@example.com", "b@example.com"),
        subject="Reel ready",
        body_text="line one\nline two",
        from_address="notifications@4reels.ie",
        from_name="4Reels Notifications",
    )

    result = sender.send(message)

    output = stream.getvalue()
    assert "[email/console]" in output
    assert "From: 4Reels Notifications <notifications@4reels.ie>" in output
    assert "To: a@example.com, b@example.com" in output
    assert "Subject: Reel ready" in output
    assert "line one" in output
    assert "line two" in output
    assert result.provider_message_id is None
    assert result.recipients == ("a@example.com", "b@example.com")
    assert result.sent_at.tzinfo == timezone.utc


def test_console_sender_renders_html_alternative_when_provided() -> None:
    stream = io.StringIO()
    sender = ConsoleEmailSender(stream=stream)
    message = EmailMessage(
        to=("a@example.com",),
        subject="Subject",
        body_text="plain",
        body_html="<p>html</p>",
        from_address="notifications@4reels.ie",
        reply_to="ops@4pm.ie",
        headers={"X-4Reels-Event": "review_requested"},
    )

    sender.send(message)

    output = stream.getvalue()
    assert "BODY (text)" in output
    assert "BODY (html)" in output
    assert "<p>html</p>" in output
    assert "Reply-To: ops@4pm.ie" in output
    assert "X-4Reels-Event: review_requested" in output


def test_console_sender_defaults_to_stdout_when_no_stream() -> None:
    captured = io.StringIO()
    original = sys.stdout
    sys.stdout = captured
    try:
        sender = ConsoleEmailSender()
        sender.send(
            EmailMessage(
                to=("a@example.com",),
                subject="Subject",
                body_text="hello",
                from_address="notifications@4reels.ie",
            )
        )
    finally:
        sys.stdout = original
    assert "[email/console]" in captured.getvalue()


def test_console_sender_returns_sent_at_close_to_now() -> None:
    sender = ConsoleEmailSender(stream=io.StringIO())
    before = datetime.now(timezone.utc)
    result = sender.send(
        EmailMessage(
            to=("a@example.com",),
            subject="Subject",
            body_text="hello",
            from_address="notifications@4reels.ie",
        )
    )
    after = datetime.now(timezone.utc)
    assert before <= result.sent_at <= after
