"""Concrete email backends selected by :func:`shared.email.factory.build_email_sender`."""

from __future__ import annotations

from shared.email.backends.console_sender import ConsoleEmailSender
from shared.email.backends.smtp_sender import SmtpEmailSender


__all__ = ["ConsoleEmailSender", "SmtpEmailSender"]
