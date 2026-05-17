"""Dispatch the ``review_requested`` outbox event into ``email_send`` jobs.

This use case is the bridge between the reel pipeline (which emits the
outbox event in ``PublishReelUseCase``) and the worker queue (which
processes ``email_send`` jobs through
:class:`SendEmailJobHandler`). It owns three responsibilities:

1. **Recipient resolution** — reads
   ``agency_reel_defaults.settings['automation.reviewEmails']`` for the
   target agency and normalises the value (CSV-string OR ``list[str]``)
   into a deduped tuple of valid lowercased emails via
   :func:`shared.email.validators.normalise_review_emails`.
2. **Throttling** — for each recipient, skips it if there is a
   ``status='sent'`` row in ``email_notifications`` with
   ``sent_at >= now - throttle_window`` (default 60 seconds).
3. **Persistence + enqueue** — inserts one ``queued`` row in
   ``email_notifications`` per surviving recipient (using the
   idempotent ``insert_pending`` + ``UNIQUE`` constraint of feature 26)
   and pushes a **single** ``email_send`` job carrying all recipient
   ids + the rendered context. Multi-recipient policy is one SMTP
   envelope with N visible ``To:`` headers (decision §D.3 of
   ``progress/design_email_notifications_and_brand_customisation.md``).

The use case never commits the UoW directly — the caller owns the
session boundary. On exit, the outbox row is transitioned via
:meth:`OutboxRepository.mark_status` to either ``dispatched`` (happy
path, including the "no recipients / fully throttled" no-op) or
``failed`` (any unrecoverable error during dispatch, re-raised after
the status update).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import uuid4

from modules.delivery.domain import JobEnqueueRequest
from modules.delivery.domain.outbox_event import OutboxEvent
from shared.db import DatabaseUnitOfWork
from shared.email.url_builder import build_reel_editor_url
from shared.email.validators import normalise_review_emails

logger = logging.getLogger(__name__)


_DEFAULT_THROTTLE_SECONDS = 60
_EMAIL_SEND_KIND = "email_send"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Summary of what one call to the dispatcher produced.

    ``recipients_queued`` is the count of fresh rows added to
    ``email_notifications``; ``recipients_throttled`` is the count of
    recipients that were dropped by the throttle window;
    ``event_kind`` is ``'review_requested'`` for the first dispatch on
    a slot, ``'review_requested_resent'`` for subsequent dispatches
    (which is also how the UNIQUE constraint is bypassed legally).
    """

    job_id: str | None
    event_kind: str
    recipients_queued: int
    recipients_throttled: int
    skipped: bool

    @property
    def queued_any(self) -> bool:
        return self.recipients_queued > 0


class DispatchReviewRequestedEmailUseCase:
    """Convert a ``review_requested`` outbox row into N email rows + 1 job."""

    def __init__(
        self,
        *,
        frontend_base_url: str,
        throttle_seconds: int = _DEFAULT_THROTTLE_SECONDS,
        job_max_attempts: int = 3,
        now_factory=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.frontend_base_url = frontend_base_url
        self.throttle_seconds = max(0, int(throttle_seconds))
        self.job_max_attempts = max(1, int(job_max_attempts))
        self._now_factory = now_factory

    def execute(self, event: OutboxEvent, *, uow: DatabaseUnitOfWork) -> DispatchResult:
        """Run the dispatch within the caller-provided UoW.

        Always returns a :class:`DispatchResult`. Raises only if the
        outbox row cannot be transitioned (e.g. session error); in that
        case the caller is responsible for rolling back.
        """

        assert uow.configuration is not None
        assert uow.notifications is not None
        assert uow.delivery is not None
        assert uow.tenancy is not None
        assert uow.catalog is not None

        agency_id = event.agency_id
        site_id = event.external_source_id
        property_id = event.source_property_id
        if not agency_id or not site_id or property_id is None:
            logger.warning(
                "dispatch_review_requested: outbox event %s missing required fields "
                "(agency_id=%r site_id=%r property_id=%r); marking dispatched as no-op",
                event.event_id,
                agency_id,
                site_id,
                property_id,
            )
            uow.delivery.outbox.mark_status(
                event_id=event.event_id,
                status="dispatched",
                published_at=self._now_factory().isoformat(),
            )
            return DispatchResult(
                job_id=None,
                event_kind="review_requested",
                recipients_queued=0,
                recipients_throttled=0,
                skipped=True,
            )

        defaults = uow.configuration.defaults.get(agency_id)
        review_emails_raw: Any = None
        if defaults is not None:
            settings_blob = defaults.settings or {}
            review_emails_raw = _extract_review_emails(settings_blob)

        recipients = normalise_review_emails(review_emails_raw)
        if not recipients:
            logger.info(
                "dispatch_review_requested: no recipients configured for "
                "agency=%s site=%s property=%s — marking dispatched as no-op",
                agency_id,
                site_id,
                property_id,
            )
            uow.delivery.outbox.mark_status(
                event_id=event.event_id,
                status="dispatched",
                published_at=self._now_factory().isoformat(),
            )
            return DispatchResult(
                job_id=None,
                event_kind="review_requested",
                recipients_queued=0,
                recipients_throttled=0,
                skipped=True,
            )

        # Throttle: drop any recipient that received a 'sent' email within
        # the last ``throttle_seconds``. Decision matrix lives in
        # ``progress/design_email_notifications_and_brand_customisation.md``
        # §D.5.
        now_ts = self._now_factory()
        since = now_ts - timedelta(seconds=self.throttle_seconds)
        surviving: list[str] = []
        throttled_count = 0
        for recipient in recipients:
            recent = uow.notifications.emails.find_recent_sent(
                agency_id=agency_id,
                recipient_email=recipient,
                since=since,
            )
            if recent is not None:
                throttled_count += 1
                logger.info(
                    "dispatch_review_requested: throttle hit — agency=%s "
                    "recipient=%s last_sent_at=%s within %ss window",
                    agency_id,
                    recipient,
                    recent.sent_at,
                    self.throttle_seconds,
                )
                continue
            surviving.append(recipient)

        if not surviving:
            uow.delivery.outbox.mark_status(
                event_id=event.event_id,
                status="dispatched",
                published_at=now_ts.isoformat(),
            )
            return DispatchResult(
                job_id=None,
                event_kind="review_requested",
                recipients_queued=0,
                recipients_throttled=throttled_count,
                skipped=True,
            )

        # event_kind: review_requested (first time) vs review_requested_resent
        # (subsequent times) — keyed on whether ANY recipient already has
        # a 'review_requested' row for this slot.
        event_kind = _resolve_event_kind(
            uow=uow,
            agency_id=agency_id,
            site_id=site_id,
            property_id=property_id,
            recipients=surviving,
        )

        # Build email context from agency + property + outbox payload.
        agency = uow.tenancy.agencies.get_by_id(agency_id)
        agency_name = (
            (event.payload.get("agency_name") if isinstance(event.payload, dict) else None)
            or (agency.name if agency is not None else "")
            or "your agency"
        )
        property_title, property_address = _resolve_property_summary(
            uow=uow,
            site_id=site_id,
            property_id=property_id,
            payload=event.payload,
        )
        reel_url = build_reel_editor_url(
            self.frontend_base_url,
            site_id=site_id,
            property_id=property_id,
        )
        context = {
            "agency_name": str(agency_name),
            "property_title": str(property_title),
            "property_address": str(property_address),
            "reel_url": reel_url,
        }

        # Insert one queued row per surviving recipient. The UNIQUE
        # constraint on (agency, site, property, recipient, event_kind)
        # keeps a re-dispatch of the same kind idempotent; the resent
        # kind is what allows the second send to coexist with the first.
        email_ids: list[str] = []
        for recipient in surviving:
            record = uow.notifications.emails.insert_pending(
                agency_id=agency_id,
                event_kind=event_kind,
                site_id=site_id,
                source_property_id=property_id,
                recipient_email=recipient,
            )
            email_ids.append(record.id)

        # Enqueue the single email_send job carrying every recipient.
        job_id = uuid4().hex
        now_iso = now_ts.isoformat()
        payload = {
            "event_kind": event_kind,
            "agency_id": agency_id,
            "site_id": site_id,
            "source_property_id": property_id,
            "email_notification_ids": email_ids,
            "recipient_emails": surviving,
            "context": context,
        }

        # The worker dispatcher always pairs a job with a webhook_events
        # row (the UPDATE in ``apps/worker/runtime.py`` references
        # ``event_id``). For notification jobs we synthesise a row with
        # ``source_kind='notification'`` so the worker can transition it
        # without colliding with WordPress webhook semantics.
        webhook_event_id = uuid4().hex
        uow.delivery.webhook_events.create_event(
            event_id=webhook_event_id,
            agency_id=agency_id,
            ingestion_source_id=event.ingestion_source_id,
            external_source_id=site_id,
            property_id=property_id,
            received_at=now_iso,
            raw_payload_hash="",
            status="queued",
            source_kind="notification",
        )
        uow.delivery.jobs.enqueue_job(
            JobEnqueueRequest(
                job_id=job_id,
                event_id=webhook_event_id,
                agency_id=agency_id,
                ingestion_source_id=event.ingestion_source_id,
                kind=_EMAIL_SEND_KIND,
                external_source_id=site_id,
                property_id=property_id,
                received_at=now_iso,
                raw_payload_hash="",
                payload=payload,
                publish_context={},
                provider_secret_bundle="",
                max_attempts=self.job_max_attempts,
                available_at=now_iso,
                created_at=now_iso,
            )
        )

        uow.delivery.outbox.mark_status(
            event_id=event.event_id,
            status="dispatched",
            published_at=now_iso,
        )
        return DispatchResult(
            job_id=job_id,
            event_kind=event_kind,
            recipients_queued=len(surviving),
            recipients_throttled=throttled_count,
            skipped=False,
        )


def _extract_review_emails(settings_blob: Mapping[str, Any]) -> Any:
    """Pull ``reviewEmails`` from a defaults settings dict.

    Two shapes are tolerated for forwards compatibility with the design
    doc §D.4: the canonical flat-key form
    ``"automation.reviewEmails"`` (what the front sends today and what
    the current integration tests assert) and a nested form
    ``automation.reviewEmails`` under an ``"automation"`` sub-mapping
    (planned migration). Either shape resolves to the same raw value
    that :func:`normalise_review_emails` then sanitises.
    """

    if not isinstance(settings_blob, Mapping):
        return None
    if "automation.reviewEmails" in settings_blob:
        return settings_blob["automation.reviewEmails"]
    automation = settings_blob.get("automation")
    if isinstance(automation, Mapping):
        return automation.get("reviewEmails")
    return None


def _resolve_event_kind(
    *,
    uow: DatabaseUnitOfWork,
    agency_id: str,
    site_id: str,
    property_id: int,
    recipients: list[str],
) -> str:
    """Return ``'review_requested'`` if no previous row exists for the
    slot, else ``'review_requested_resent'``.

    "Previous row" means any ``email_notifications`` row matching the
    slot + a recipient in the candidate list + the
    ``'review_requested'`` event kind, regardless of status. This keeps
    the UNIQUE constraint happy on the resent insert: the new rows go
    in with ``event_kind='review_requested_resent'`` so they do not
    collide with the original ones.
    """

    assert uow.notifications is not None
    for recipient in recipients:
        rows = uow.notifications.emails.list_by_agency(agency_id=agency_id, limit=200)
        for row in rows:
            if (
                row.site_id == site_id
                and row.source_property_id == property_id
                and row.recipient_email == recipient
                and row.event_kind == "review_requested"
            ):
                return "review_requested_resent"
        break  # one query against list_by_agency is enough; loop exits on first iter
    return "review_requested"


def _resolve_property_summary(
    *,
    uow: DatabaseUnitOfWork,
    site_id: str,
    property_id: int,
    payload: Mapping[str, Any] | None,
) -> tuple[str, str]:
    """Return ``(property_title, property_address)`` strings, using the
    outbox payload first (when populated by the publisher in a future
    iteration) and the ``properties.raw_json`` blob as fallback.

    Falls back to empty strings if the row is missing — the renderer
    will still produce a valid email body, just with blank fields.
    """

    title = ""
    address = ""

    if isinstance(payload, Mapping):
        candidate_title = payload.get("property_title")
        if isinstance(candidate_title, str) and candidate_title.strip():
            title = candidate_title.strip()
        candidate_address = payload.get("property_address")
        if isinstance(candidate_address, str) and candidate_address.strip():
            address = candidate_address.strip()

    if title and address:
        return title, address

    assert uow.catalog is not None
    raw_payload = uow.catalog.properties.get_raw_payload(
        external_source_id=site_id,
        source_property_id=property_id,
    )
    if raw_payload:
        try:
            parsed: Any = json.loads(raw_payload)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, Mapping):
            if not title:
                title = _extract_title(parsed)
            if not address:
                address = _extract_address(parsed)

    return title, address


def _extract_title(parsed: Mapping[str, Any]) -> str:
    title = parsed.get("title")
    if isinstance(title, Mapping):
        rendered = title.get("rendered")
        if isinstance(rendered, str) and rendered.strip():
            return rendered.strip()
    if isinstance(title, str) and title.strip():
        return title.strip()
    slug = parsed.get("slug")
    if isinstance(slug, str) and slug.strip():
        return slug.strip()
    return ""


def _extract_address(parsed: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("property_area_label", "property_county_label", "country"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if parts:
        return ", ".join(parts)
    eircode = parsed.get("eircode")
    if isinstance(eircode, str) and eircode.strip():
        return eircode.strip()
    return ""


__all__ = [
    "DispatchResult",
    "DispatchReviewRequestedEmailUseCase",
]
