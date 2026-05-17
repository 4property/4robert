"""Email sender Protocol + value objects for the notifications layer.

The interface is deliberately tiny: callers build an :class:`EmailMessage`
and hand it to any :class:`EmailSender` implementation, which returns a
:class:`SentEmail` with the provider-side identifier (``Message-ID`` for
SMTP, ``None`` for the console backend used in dev/tests).

Layer rule: this module must NOT import from ``settings/`` or
``modules/``. The factory in ``shared.email.factory`` is the only
coupling point with settings, so the protocol stays pure infra.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """Immutable value object describing one outbound email.

    ``to`` is a tuple of recipient addresses; all of them appear on the
    visible ``To:`` header (no ``Bcc:`` masking) per the design decision
    in ``progress/design_email_notifications_and_brand_customisation.md``
    §D. ``headers`` is a free-form mapping for custom RFC 5322 headers
    (e.g. ``X-4Reels-Event``).
    """

    to: tuple[str, ...]
    subject: str
    body_text: str
    from_address: str
    body_html: str | None = None
    from_name: str | None = None
    reply_to: str | None = None
    headers: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class SentEmail:
    """Result returned by an :class:`EmailSender` after a successful send.

    ``provider_message_id`` is the canonical id the back end persists in
    ``email_notifications.provider_message_id``. The console backend
    returns ``None``; the SMTP backend returns the locally-generated
    RFC 5322 ``Message-ID``.
    """

    provider_message_id: str | None
    recipients: tuple[str, ...]
    sent_at: datetime


class EmailSender(Protocol):
    """Send one :class:`EmailMessage` and return a :class:`SentEmail`.

    Implementations live in :mod:`shared.email.backends`. The factory
    in :mod:`shared.email.factory` chooses one at runtime based on the
    ``EMAIL_BACKEND`` env var.
    """

    def send(self, message: EmailMessage) -> SentEmail: ...


__all__ = ["EmailMessage", "EmailSender", "SentEmail"]
