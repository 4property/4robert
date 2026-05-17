"""Domain value objects + status constants for the notifications module."""

from __future__ import annotations

from modules.notifications.domain.email_record import EmailRecord
from modules.notifications.domain.status import (
    EMAIL_STATUSES,
    STATUS_BOUNCED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_SENT,
)


__all__ = [
    "EMAIL_STATUSES",
    "EmailRecord",
    "STATUS_BOUNCED",
    "STATUS_FAILED",
    "STATUS_QUEUED",
    "STATUS_SENT",
]
