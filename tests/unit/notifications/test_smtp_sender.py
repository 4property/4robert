"""Unit tests for :class:`SmtpEmailSender` using a MagicMock SMTP client."""

from __future__ import annotations

from email.message import EmailMessage as StdlibEmailMessage
from unittest.mock import MagicMock, patch

import pytest

from shared.email import EmailMessage, SmtpEmailSender


def _build_sender(**overrides) -> SmtpEmailSender:
    defaults = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "alice",
        "password": "s3cret",
        "use_tls": True,
    }
    defaults.update(overrides)
    return SmtpEmailSender(**defaults)


def _basic_message() -> EmailMessage:
    return EmailMessage(
        to=("a@example.com", "b@example.com"),
        subject="Reel ready",
        body_text="hello",
        from_address="notifications@4reels.ie",
        from_name="4Reels Notifications",
    )


@patch("shared.email.backends.smtp_sender.smtplib.SMTP")
def test_smtp_sender_uses_starttls_and_login_when_configured(
    smtp_class: MagicMock,
) -> None:
    smtp_client = smtp_class.return_value
    sender = _build_sender()

    result = sender.send(_basic_message())

    smtp_class.assert_called_once_with("smtp.example.com", 587)
    smtp_client.starttls.assert_called_once_with()
    smtp_client.login.assert_called_once_with("alice", "s3cret")
    smtp_client.send_message.assert_called_once()
    smtp_client.quit.assert_called_once()
    assert result.provider_message_id is not None
    assert result.provider_message_id.startswith("<") and result.provider_message_id.endswith(">")
    assert result.recipients == ("a@example.com", "b@example.com")


@patch("shared.email.backends.smtp_sender.smtplib.SMTP")
def test_smtp_sender_skips_starttls_and_login_when_not_configured(
    smtp_class: MagicMock,
) -> None:
    smtp_client = smtp_class.return_value
    sender = _build_sender(username=None, password=None, use_tls=False)

    sender.send(_basic_message())

    smtp_client.starttls.assert_not_called()
    smtp_client.login.assert_not_called()
    smtp_client.send_message.assert_called_once()


@patch("shared.email.backends.smtp_sender.smtplib.SMTP")
def test_smtp_sender_sets_plain_text_body_by_default(
    smtp_class: MagicMock,
) -> None:
    smtp_client = smtp_class.return_value
    sender = _build_sender()

    sender.send(_basic_message())

    envelope = smtp_client.send_message.call_args.args[0]
    assert isinstance(envelope, StdlibEmailMessage)
    assert envelope.get_content_type() == "text/plain"
    assert envelope.get_content().strip() == "hello"


@patch("shared.email.backends.smtp_sender.smtplib.SMTP")
def test_smtp_sender_sets_alternative_html_body_when_provided(
    smtp_class: MagicMock,
) -> None:
    smtp_client = smtp_class.return_value
    sender = _build_sender()
    message = EmailMessage(
        to=("a@example.com",),
        subject="Subject",
        body_text="plain body",
        body_html="<p>rich</p>",
        from_address="notifications@4reels.ie",
    )

    sender.send(message)

    envelope = smtp_client.send_message.call_args.args[0]
    assert envelope.is_multipart()
    payloads = envelope.iter_parts()
    content_types = {part.get_content_type() for part in payloads}
    assert content_types == {"text/plain", "text/html"}


@patch("shared.email.backends.smtp_sender.smtplib.SMTP")
def test_smtp_sender_propagates_reply_to_and_custom_headers(
    smtp_class: MagicMock,
) -> None:
    smtp_client = smtp_class.return_value
    sender = _build_sender()
    message = EmailMessage(
        to=("a@example.com",),
        subject="Subject",
        body_text="hello",
        from_address="notifications@4reels.ie",
        reply_to="ops@4pm.ie",
        headers={"X-4Reels-Event": "review_requested"},
    )

    sender.send(message)

    envelope = smtp_client.send_message.call_args.args[0]
    assert envelope["Reply-To"] == "ops@4pm.ie"
    assert envelope["X-4Reels-Event"] == "review_requested"
    assert envelope["To"] == "a@example.com"


@patch("shared.email.backends.smtp_sender.smtplib.SMTP")
def test_smtp_sender_returned_message_id_matches_envelope_header(
    smtp_class: MagicMock,
) -> None:
    smtp_client = smtp_class.return_value
    sender = _build_sender()

    result = sender.send(_basic_message())

    envelope = smtp_client.send_message.call_args.args[0]
    assert result.provider_message_id == envelope["Message-ID"]


@patch("shared.email.backends.smtp_sender.smtplib.SMTP")
def test_smtp_sender_closes_connection_on_send_failure(
    smtp_class: MagicMock,
) -> None:
    smtp_client = smtp_class.return_value
    smtp_client.send_message.side_effect = RuntimeError("boom")
    sender = _build_sender()

    with pytest.raises(RuntimeError, match="boom"):
        sender.send(_basic_message())

    smtp_client.quit.assert_called_once()
