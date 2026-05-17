"""Worker handler for ``kind='email_send'`` jobs.

Lives in the notifications module so the wire-up in
``apps.worker.runtime.build_default_dispatcher`` stays a one-liner.
The handler is wire-compatible with the
:class:`apps.worker.runtime.JobHandler` Protocol (callable that takes a
:class:`modules.delivery.domain.Job`).

Contract with the dispatcher
============================

The payload produced by
:class:`modules.notifications.application.use_cases.dispatch_review_requested_email.DispatchReviewRequestedEmailUseCase`
carries:

* ``event_kind``: ``"review_requested"`` or ``"review_requested_resent"``.
* ``recipient_emails``: list of canonical lowercased addresses; all
  appear on the visible ``To:`` header.
* ``email_notification_ids``: list of UUIDs to update on success/failure
  (one per recipient, same length as ``recipient_emails``).
* ``context``: dict with ``agency_name``, ``property_title``,
  ``property_address``, ``reel_url`` — passed verbatim into the
  template renderer.

The handler renders the template, calls the injected
:class:`shared.email.sender.EmailSender`, and writes the provider id +
``sent_at`` (or the error message) back onto every
``email_notifications`` row in one UoW.
"""

from __future__ import annotations

import logging
from typing import Mapping

from modules.delivery.domain import Job
from shared.db import DatabaseUnitOfWork
from shared.email.sender import EmailMessage, EmailSender
from shared.email.templates import EmailTemplateRenderer
from settings.notifications import NotificationSettings

logger = logging.getLogger(__name__)


_TEMPLATE_NAME = "review_requested"


class SendEmailJobHandler:
    """Render + send + persist for one ``email_send`` job."""

    def __init__(
        self,
        *,
        sender: EmailSender,
        notification_settings: NotificationSettings,
        template_renderer: EmailTemplateRenderer | None = None,
        database_locator: str | None = None,
    ) -> None:
        self._sender = sender
        self._settings = notification_settings
        self._renderer = template_renderer or EmailTemplateRenderer()
        self._database_locator = database_locator

    def __call__(self, job: Job) -> object | None:
        return self.handle(job)

    def handle(self, job: Job) -> object | None:
        payload = dict(job.payload or {})
        recipient_emails = _coerce_str_list(payload.get("recipient_emails"))
        email_ids = _coerce_str_list(payload.get("email_notification_ids"))
        if not recipient_emails or not email_ids:
            logger.warning(
                "email_send job %s missing recipients/email_ids; payload=%r",
                job.job_id,
                payload,
            )
            return None

        context_raw = payload.get("context")
        context: dict[str, object] = (
            dict(context_raw) if isinstance(context_raw, Mapping) else {}
        )
        # Ensure every placeholder has a string value (templates assume
        # ``str.format`` semantics; ``None`` would render as the
        # literal "None").
        context.setdefault("agency_name", "")
        context.setdefault("property_title", "")
        context.setdefault("property_address", "")
        context.setdefault("reel_url", "")

        subject = f"Reel ready for review — {context.get('property_title') or 'your reel'}"
        body_text = self._renderer.render_plain(_TEMPLATE_NAME, context)
        body_html = self._renderer.render_html(_TEMPLATE_NAME, context)

        message = EmailMessage(
            to=tuple(recipient_emails),
            subject=subject,
            body_text=body_text,
            from_address=self._settings.smtp_from_address,
            body_html=body_html,
            from_name=self._settings.smtp_from_name,
        )

        try:
            sent = self._sender.send(message)
        except Exception as exc:  # noqa: BLE001 - surfaced as job failure
            self._mark_all_failed(email_ids, error_message=str(exc) or exc.__class__.__name__)
            raise

        with self._unit_of_work() as uow:
            assert uow.notifications is not None
            for email_id in email_ids:
                uow.notifications.emails.mark_sent(
                    email_id=email_id,
                    provider_message_id=sent.provider_message_id,
                    sent_at=sent.sent_at,
                )
        logger.info(
            "email_send job %s delivered to %d recipient(s) via %s "
            "(provider_message_id=%s)",
            job.job_id,
            len(recipient_emails),
            self._sender.__class__.__name__,
            sent.provider_message_id,
        )
        return {
            "recipients": list(recipient_emails),
            "provider_message_id": sent.provider_message_id,
        }

    def _mark_all_failed(self, email_ids: list[str], *, error_message: str) -> None:
        with self._unit_of_work() as uow:
            assert uow.notifications is not None
            for email_id in email_ids:
                uow.notifications.emails.mark_failed(
                    email_id=email_id,
                    error_message=error_message,
                )

    def _unit_of_work(self) -> DatabaseUnitOfWork:
        return DatabaseUnitOfWork(database_locator=self._database_locator)


def _coerce_str_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            out.append(item)
    return out


__all__ = ["SendEmailJobHandler"]
