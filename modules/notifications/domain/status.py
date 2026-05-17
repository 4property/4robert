"""Canonical values for ``email_notifications.status``."""

from __future__ import annotations


STATUS_QUEUED = "queued"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_BOUNCED = "bounced"

EMAIL_STATUSES: frozenset[str] = frozenset(
    {STATUS_QUEUED, STATUS_SENT, STATUS_FAILED, STATUS_BOUNCED}
)


__all__ = [
    "EMAIL_STATUSES",
    "STATUS_BOUNCED",
    "STATUS_FAILED",
    "STATUS_QUEUED",
    "STATUS_SENT",
]
