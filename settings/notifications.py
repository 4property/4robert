"""Notification settings — SMTP credentials + frontend deep-link base URL.

Loaded from process env via :func:`load_notification_settings`. The
factory in :mod:`shared.email.factory` consumes the resulting
:class:`NotificationSettings` to choose a backend at runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_EMAIL_BACKEND = "console"
DEFAULT_SMTP_HOST = "localhost"
DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_USE_TLS = True
DEFAULT_SMTP_FROM_ADDRESS = "notifications@4reels.ie"
DEFAULT_SMTP_FROM_NAME = "4Reels Notifications"
DEFAULT_FRONTEND_BASE_URL = "http://localhost:5173"


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    email_backend: str
    smtp_host: str
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_use_tls: bool
    smtp_from_address: str
    smtp_from_name: str
    frontend_base_url: str


def _truthy(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def load_notification_settings(
    environ: Mapping[str, str] | None = None,
) -> NotificationSettings:
    env = environ if environ is not None else os.environ
    return NotificationSettings(
        email_backend=(env.get("EMAIL_BACKEND") or DEFAULT_EMAIL_BACKEND)
        .strip()
        .lower(),
        smtp_host=(env.get("SMTP_HOST") or DEFAULT_SMTP_HOST).strip(),
        smtp_port=_int(env.get("SMTP_PORT"), DEFAULT_SMTP_PORT),
        smtp_username=_optional(env.get("SMTP_USER")),
        smtp_password=_optional(env.get("SMTP_PASSWORD")),
        smtp_use_tls=_truthy(env.get("SMTP_USE_TLS"), DEFAULT_SMTP_USE_TLS),
        smtp_from_address=(
            env.get("SMTP_FROM_ADDRESS") or DEFAULT_SMTP_FROM_ADDRESS
        ).strip(),
        smtp_from_name=(
            env.get("SMTP_FROM_NAME") or DEFAULT_SMTP_FROM_NAME
        ).strip(),
        frontend_base_url=(
            env.get("FRONTEND_BASE_URL") or DEFAULT_FRONTEND_BASE_URL
        ).strip(),
    )


__all__ = [
    "DEFAULT_EMAIL_BACKEND",
    "DEFAULT_FRONTEND_BASE_URL",
    "DEFAULT_SMTP_FROM_ADDRESS",
    "DEFAULT_SMTP_FROM_NAME",
    "DEFAULT_SMTP_HOST",
    "DEFAULT_SMTP_PORT",
    "DEFAULT_SMTP_USE_TLS",
    "NotificationSettings",
    "load_notification_settings",
]
