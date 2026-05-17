"""Factory: env → :class:`EmailSender` subclass selection."""

from __future__ import annotations

import pytest

from settings.notifications import NotificationSettings, load_notification_settings
from shared.email import ConsoleEmailSender, SmtpEmailSender, build_email_sender


def _settings(**overrides) -> NotificationSettings:
    base = load_notification_settings(environ={})
    base_kwargs = {
        "email_backend": base.email_backend,
        "smtp_host": base.smtp_host,
        "smtp_port": base.smtp_port,
        "smtp_username": base.smtp_username,
        "smtp_password": base.smtp_password,
        "smtp_use_tls": base.smtp_use_tls,
        "smtp_from_address": base.smtp_from_address,
        "smtp_from_name": base.smtp_from_name,
        "frontend_base_url": base.frontend_base_url,
    }
    base_kwargs.update(overrides)
    return NotificationSettings(**base_kwargs)


def test_load_notification_settings_uses_defaults_when_env_empty() -> None:
    settings = load_notification_settings(environ={})
    assert settings.email_backend == "console"
    assert settings.smtp_host == "localhost"
    assert settings.smtp_port == 587
    assert settings.smtp_username is None
    assert settings.smtp_password is None
    assert settings.smtp_use_tls is True
    assert settings.smtp_from_address == "notifications@4reels.ie"
    assert settings.smtp_from_name == "4Reels Notifications"
    assert settings.frontend_base_url == "http://localhost:5173"


def test_load_notification_settings_reads_env_overrides() -> None:
    settings = load_notification_settings(
        environ={
            "EMAIL_BACKEND": "SMTP",
            "SMTP_HOST": "mail.example.com",
            "SMTP_PORT": "2525",
            "SMTP_USER": "alice",
            "SMTP_PASSWORD": "secret",
            "SMTP_USE_TLS": "false",
            "SMTP_FROM_ADDRESS": "ops@example.com",
            "SMTP_FROM_NAME": "Ops",
            "FRONTEND_BASE_URL": "https://admin.example.com",
        }
    )
    assert settings.email_backend == "smtp"
    assert settings.smtp_host == "mail.example.com"
    assert settings.smtp_port == 2525
    assert settings.smtp_username == "alice"
    assert settings.smtp_password == "secret"
    assert settings.smtp_use_tls is False
    assert settings.smtp_from_address == "ops@example.com"
    assert settings.smtp_from_name == "Ops"
    assert settings.frontend_base_url == "https://admin.example.com"


def test_build_email_sender_returns_console_when_backend_is_console() -> None:
    sender = build_email_sender(_settings(email_backend="console"))
    assert isinstance(sender, ConsoleEmailSender)


def test_build_email_sender_returns_smtp_when_backend_is_smtp() -> None:
    sender = build_email_sender(_settings(email_backend="smtp"))
    assert isinstance(sender, SmtpEmailSender)


def test_build_email_sender_raises_for_unknown_backend() -> None:
    with pytest.raises(ValueError, match="unknown EMAIL_BACKEND"):
        build_email_sender(_settings(email_backend="postmark"))
