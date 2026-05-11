"""Helpers for the WordPress webhook router: payload parsing, error builders, log emitters."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import Request

from apps.api.admin_auth import format_client
from modules.ingestion.application.use_cases.ingest_wordpress_property import (
    AcceptedWebhookDelivery,
)
from shared.errors import extract_error_details
from shared.observability import (
    format_console_block,
    format_context_line,
    format_detail_line,
    log_persistent_event,
)

logger = logging.getLogger(__name__)


def _parse_content_length(raw_value: str | None) -> int | None:
    if raw_value is None:
        return 0
    try:
        content_length = int(raw_value)
    except ValueError:
        return None
    return max(content_length, 0)


def _extract_property_id(payload: dict[str, Any]) -> int | None:
    value = payload.get("id")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _get_header_value(request: Request, *names: str) -> str | None:
    for name in names:
        value = request.headers.get(name)
        if value:
            return value
    return None


def _parse_webhook_payload(raw_body: bytes) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return (
            None,
            f"Request body must be valid JSON. {exc.msg} at line {exc.lineno}, "
            f"column {exc.colno}.",
        )

    if isinstance(parsed, list):
        if len(parsed) != 1:
            return None, "Webhook payload array must contain exactly one JSON object."
        parsed = parsed[0]

    if not isinstance(parsed, dict):
        return None, "Request body must be a JSON object."

    return parsed, None


def _resolve_site_id(payload: dict[str, Any]) -> str | None:
    rest_domain = payload.get("rest_domain")
    if isinstance(rest_domain, str) and rest_domain.strip():
        return _hostname_from_value(rest_domain)

    direct_site_id = payload.get("site_id")
    if isinstance(direct_site_id, str) and direct_site_id.strip():
        return _hostname_from_value(direct_site_id)

    link_candidates: list[str] = []
    link = payload.get("link")
    if isinstance(link, str) and link.strip():
        link_candidates.append(link)

    guid = payload.get("guid")
    if isinstance(guid, dict):
        rendered = guid.get("rendered")
        if isinstance(rendered, str) and rendered.strip():
            link_candidates.append(rendered)

    for candidate in link_candidates:
        parsed = urlparse(candidate)
        if parsed.netloc:
            return parsed.netloc.strip().lower()

    return None


def _hostname_from_value(raw_value: str) -> str:
    value = str(raw_value or "").strip().lower()
    if "://" in value:
        parsed = urlparse(value)
        value = parsed.hostname or parsed.netloc or parsed.path or ""
    else:
        value = value.split("/", 1)[0]
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        if port.isdigit():
            value = host
    return value.strip().lower()


def _get_request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    if value in (None, ""):
        return None
    return str(value)


def _acceptance_error_details(
    *,
    request_id: str | None,
    dispatcher_accepting_jobs: bool,
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    details: dict[str, object] = {
        "dispatcher_accepting_jobs": dispatcher_accepting_jobs,
    }
    if request_id:
        details["request_id"] = request_id
    if context:
        details["context"] = context
    return details


def _log_authentication_failure(
    *,
    request: Request,
    site_id: str | None,
    reason: str,
    hint: str | None,
) -> None:
    logger.warning(
        format_console_block(
            "Webhook Authentication Failed",
            format_detail_line("Client", format_client(request)),
            format_detail_line("Site ID", site_id or "<unresolved>"),
            format_detail_line("Reason", reason),
            format_detail_line("Hint", hint),
        )
    )
    log_persistent_event(
        "webhook.authentication_failed",
        site_id=site_id,
        client=format_client(request),
        reason=reason,
    )


def _log_acceptance_failure(
    *,
    request: Request,
    request_id: str | None,
    site_id: str | None,
    property_id: int | None,
    dispatcher_accepting_jobs: bool,
    error: Exception,
    title: str,
    persistent_event_type: str,
    tone: str,
) -> None:
    error_details = extract_error_details(error)
    log_lines = [
        format_detail_line("Request ID", request_id or "<unknown>"),
        format_detail_line("Client", format_client(request)),
        format_detail_line("Site ID", site_id or "<unresolved>"),
        format_detail_line("Property ID", property_id),
        format_detail_line(
            "Dispatcher accepting jobs", "Yes" if dispatcher_accepting_jobs else "No"
        ),
        format_detail_line("Reason", error_details.get("message") or error, highlight=True),
        format_detail_line("Error type", error_details.get("type")),
        format_detail_line("Error code", error_details.get("code")),
        format_detail_line("Hint", error_details.get("hint")),
        format_context_line(
            error_details.get("context")
            if isinstance(error_details.get("context"), dict)
            else None
        ),
    ]
    if tone == "warning":
        logger.warning(format_console_block(title, *log_lines, tone=tone))
    else:
        logger.error(format_console_block(title, *log_lines, tone=tone), exc_info=error)

    log_persistent_event(
        persistent_event_type,
        request_id=request_id,
        client=format_client(request),
        site_id=site_id,
        property_id=property_id,
        dispatcher_accepting_jobs=dispatcher_accepting_jobs,
        error_type=error_details.get("type"),
        error_code=error_details.get("code"),
        error_message=error_details.get("message") or str(error),
        hint=error_details.get("hint"),
        context=(
            error_details.get("context")
            if isinstance(error_details.get("context"), dict)
            else None
        ),
    )


def _log_acceptance_success(
    *,
    request_id: str | None,
    accepted_delivery: AcceptedWebhookDelivery,
    site_id: str,
    property_id: int | None,
    raw_payload_hash: str,
    dispatcher_accepting_jobs: bool,
) -> None:
    logger.info(
        format_console_block(
            "Webhook Accepted",
            format_detail_line("Request ID", request_id or "<unknown>"),
            format_detail_line("Event ID", accepted_delivery.event_id),
            format_detail_line("Job ID", accepted_delivery.job_id),
            format_detail_line("Site ID", site_id),
            format_detail_line("Property ID", property_id),
            format_detail_line(
                "Dispatcher accepting jobs",
                "Yes" if dispatcher_accepting_jobs else "No",
            ),
            format_detail_line(
                "Site auto-provisioned for testing",
                "Yes" if accepted_delivery.tenant_auto_provisioned else "No",
            ),
            "The payload was queued for background processing.",
        )
    )
    log_persistent_event(
        "webhook.accepted",
        request_id=request_id,
        event_id=accepted_delivery.event_id,
        job_id=accepted_delivery.job_id,
        site_id=site_id,
        property_id=property_id,
        raw_payload_hash=raw_payload_hash,
        dispatcher_accepting_jobs=dispatcher_accepting_jobs,
        tenant_auto_provisioned=accepted_delivery.tenant_auto_provisioned,
    )


__all__ = [
    "_acceptance_error_details",
    "_extract_property_id",
    "_get_header_value",
    "_get_request_id",
    "_hostname_from_value",
    "_log_acceptance_failure",
    "_log_acceptance_success",
    "_log_authentication_failure",
    "_parse_content_length",
    "_parse_webhook_payload",
    "_resolve_site_id",
]
