"""Factory that materialises an :class:`EmailSender` from settings.

This is the only module in :mod:`shared.email` that may import from
:mod:`settings`. Keeping the coupling here means the protocol layer and
both backends remain pure infra and trivially unit-testable.
"""

from __future__ import annotations

from settings.notifications import NotificationSettings
from shared.email.backends.console_sender import ConsoleEmailSender
from shared.email.backends.smtp_sender import SmtpEmailSender
from shared.email.sender import EmailSender


def build_email_sender(settings: NotificationSettings) -> EmailSender:
    backend = settings.email_backend.strip().lower()
    if backend == "console":
        return ConsoleEmailSender()
    if backend == "smtp":
        return SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
        )
    raise ValueError(f"unknown EMAIL_BACKEND: {settings.email_backend!r}")


__all__ = ["build_email_sender"]
