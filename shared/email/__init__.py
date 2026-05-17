"""Email infrastructure layer (feature 26).

Public surface:

* :class:`EmailMessage` / :class:`SentEmail` — frozen value objects.
* :class:`EmailSender` — the Protocol every backend implements.
* :class:`ConsoleEmailSender` / :class:`SmtpEmailSender` — concrete backends.
* :func:`build_email_sender` — picks a backend from
  :class:`settings.notifications.NotificationSettings`.
"""

from __future__ import annotations

from shared.email.backends.console_sender import ConsoleEmailSender
from shared.email.backends.smtp_sender import SmtpEmailSender
from shared.email.factory import build_email_sender
from shared.email.sender import EmailMessage, EmailSender, SentEmail
from shared.email.templates import EmailTemplateRenderer
from shared.email.url_builder import build_reel_editor_url
from shared.email.validators import (
    EMAIL_PATTERN,
    is_valid_email,
    normalise_email,
    normalise_review_emails,
)


__all__ = [
    "ConsoleEmailSender",
    "EMAIL_PATTERN",
    "EmailMessage",
    "EmailSender",
    "EmailTemplateRenderer",
    "SentEmail",
    "SmtpEmailSender",
    "build_email_sender",
    "build_reel_editor_url",
    "is_valid_email",
    "normalise_email",
    "normalise_review_emails",
]
