"""FastAPI router for the inbound WordPress property webhook."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import format_client
from apps.api.error_handlers import json_error
from modules.ingestion.application.use_cases.ingest_wordpress_property import (
    IngestWordPressPropertyInput,
    IngestWordPressPropertyUseCase,
)
from modules.ingestion.transport.http.wordpress_webhook_payloads import (
    _acceptance_error_details,
    _extract_property_id,
    _get_header_value,
    _get_request_id,
    _log_acceptance_failure,
    _log_acceptance_success,
    _log_authentication_failure,
    _parse_content_length,
    _parse_webhook_payload,
    _resolve_site_id,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import (
    ApplicationError,
    ResourceNotFoundError,
    ValidationError,
)
from shared.http.webhook_signature import (
    build_raw_payload_hash,
    verify_webhook_signature,
)
from shared.observability import (
    format_console_block,
    format_detail_line,
    log_persistent_event,
)

logger = logging.getLogger(__name__)

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]
DispatcherStateProvider = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class WordPressWebhookSettings:
    path: str = "/v1/ingest/wordpress/property"
    site_id_header: str = "X-WP-Site-Id"
    timestamp_header: str = "X-WP-Timestamp"
    signature_header: str = "X-WP-Signature"
    max_payload_bytes: int = 1_048_576
    timestamp_tolerance_seconds: int = 300
    security_disabled: bool = False
    site_secrets: dict[str, str] = field(default_factory=dict)
    default_platforms: tuple[str, ...] = ()


def create_wordpress_webhook_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    settings: WordPressWebhookSettings,
    job_max_attempts: int,
    dispatcher_state: DispatcherStateProvider | None = None,
    ingest_wordpress_property: IngestWordPressPropertyUseCase | None = None,
) -> APIRouter:
    router = APIRouter(tags=["Webhooks"])
    ingest_wordpress_property = ingest_wordpress_property or IngestWordPressPropertyUseCase(
        job_max_attempts=job_max_attempts,
    )
    is_accepting_jobs = dispatcher_state or (lambda: True)

    @router.post(
        settings.path,
        summary="Receive a property webhook from a WordPress site",
        description=(
            "Resolves the agency from the body's `rest_domain` (or "
            "`X-WP-Site-Id` header), validates security headers/HMAC, and "
            "enqueues a `reel_publish` job. Returns 202 with the new "
            "`event_id`/`job_id`."
        ),
    )
    async def ingest_wordpress_property_endpoint(request: Request) -> JSONResponse:
        site_id = _get_header_value(request, settings.site_id_header)
        timestamp = request.headers.get(settings.timestamp_header)
        signature = request.headers.get(settings.signature_header)

        content_type = request.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            return json_error(
                400,
                "Content-Type must be application/json.",
                code="INVALID_CONTENT_TYPE",
                hint=(
                    "Configure the WordPress sender to post raw JSON with "
                    "Content-Type: application/json."
                ),
                details={"received_content_type": content_type or "<empty>"},
            )

        content_length = _parse_content_length(request.headers.get("Content-Length"))
        if content_length is None:
            return json_error(
                400,
                "Invalid Content-Length header.",
                code="INVALID_CONTENT_LENGTH",
                hint=(
                    "Send a numeric Content-Length header or let the HTTP client "
                    "populate it automatically."
                ),
            )
        if content_length > settings.max_payload_bytes:
            return json_error(
                413,
                "Request body is too large.",
                code="PAYLOAD_TOO_LARGE",
                hint=(
                    "Reduce the payload size or increase WEBHOOK_MAX_PAYLOAD_BYTES "
                    "on the API host."
                ),
                details={"max_payload_bytes": settings.max_payload_bytes},
            )

        raw_body = await request.body()
        if len(raw_body) > settings.max_payload_bytes:
            return json_error(
                413,
                "Request body is too large.",
                code="PAYLOAD_TOO_LARGE",
                hint=(
                    "Reduce the payload size or increase WEBHOOK_MAX_PAYLOAD_BYTES "
                    "on the API host."
                ),
                details={"max_payload_bytes": settings.max_payload_bytes},
            )

        payload, payload_error = _parse_webhook_payload(raw_body)
        if payload_error is not None:
            return json_error(400, payload_error)

        if not site_id:
            site_id = _resolve_site_id(payload or {})

        if not site_id:
            return json_error(
                400,
                "The webhook site_id could not be resolved.",
                code="SITE_ID_REQUIRED",
                hint=(
                    f"Send the {settings.site_id_header} header or include a "
                    "property link/guid whose hostname matches the source site."
                ),
            )
        if not settings.security_disabled and (not timestamp or not signature):
            missing_headers = []
            if not timestamp:
                missing_headers.append(settings.timestamp_header)
            if not signature:
                missing_headers.append(settings.signature_header)
            return json_error(
                400,
                "Missing required webhook security headers.",
                code="MISSING_SECURITY_HEADERS",
                hint=(
                    "Send both timestamp and signature headers when webhook "
                    "security is enabled."
                ),
                details={"missing_headers": missing_headers},
            )

        if not settings.security_disabled:
            expected_secret = settings.site_secrets.get(site_id)
            if expected_secret is None:
                _log_authentication_failure(
                    request=request,
                    site_id=site_id,
                    reason=f"No webhook secret is configured for site_id '{site_id}'.",
                    hint=(
                        "Add the site to WEBHOOK_SITE_SECRETS on the deployed "
                        "service and restart it."
                    ),
                )
                return json_error(
                    401,
                    "Invalid webhook credentials.",
                    code="INVALID_WEBHOOK_CREDENTIALS",
                    hint=(
                        "Check the webhook signing secret, timestamp, and required "
                        "security headers."
                    ),
                    details={"site_id": site_id},
                )
            ok, auth_message, auth_hint = verify_webhook_signature(
                secret=expected_secret,
                timestamp=timestamp or "",
                site_id=site_id,
                raw_body=raw_body,
                signature=signature or "",
                tolerance_seconds=settings.timestamp_tolerance_seconds,
            )
            if not ok:
                _log_authentication_failure(
                    request=request,
                    site_id=site_id,
                    reason=auth_message or "Invalid webhook credentials.",
                    hint=auth_hint,
                )
                return json_error(
                    401,
                    "Invalid webhook credentials.",
                    code="INVALID_WEBHOOK_CREDENTIALS",
                    hint=(
                        "Check the webhook signing secret, timestamp, and required "
                        "security headers."
                    ),
                    details={"site_id": site_id},
                )

        property_id = _extract_property_id(payload or {})
        raw_payload_hash = build_raw_payload_hash(raw_body)
        request_id = _get_request_id(request)
        dispatcher_accepting_jobs = bool(is_accepting_jobs())

        if not dispatcher_accepting_jobs:
            logger.warning(
                format_console_block(
                    "Webhook Accepted While Dispatcher Paused",
                    format_detail_line("Request ID", request_id or "<unknown>"),
                    format_detail_line("Client", format_client(request)),
                    format_detail_line("Site ID", site_id),
                    format_detail_line("Property ID", property_id),
                    "The webhook will still be enqueued in the durable PostgreSQL queue.",
                )
            )
            log_persistent_event(
                "webhook.dispatcher_paused",
                request_id=request_id,
                site_id=site_id,
                property_id=property_id,
                client=format_client(request),
                dispatcher_accepting_jobs=dispatcher_accepting_jobs,
            )

        try:
            with unit_of_work_factory() as uow:
                accepted_delivery = ingest_wordpress_property.execute(
                    uow=uow,
                    data=IngestWordPressPropertyInput(
                        site_id=site_id,
                        property_id=property_id,
                        raw_payload_hash=raw_payload_hash,
                        payload=payload or {},
                        default_platforms=settings.default_platforms,
                    ),
                )
        except ResourceNotFoundError as error:
            _log_acceptance_failure(
                request=request,
                request_id=request_id,
                site_id=site_id,
                property_id=property_id,
                dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                error=error,
                title="Webhook Acceptance Rejected",
                persistent_event_type="webhook.acceptance_rejected",
                tone="warning",
            )
            status_code = 404 if error.code in {
                "UNKNOWN_WORDPRESS_SITE",
                "GHL_TOKEN_NOT_FOUND",
                "GHL_CONNECTION_NOT_FOUND",
            } else 400
            return json_error(
                status_code,
                str(error),
                code=error.code,
                hint=error.hint,
                details=_acceptance_error_details(
                    request_id=request_id,
                    dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                    context=error.context,
                ),
            )
        except ValidationError as error:
            _log_acceptance_failure(
                request=request,
                request_id=request_id,
                site_id=site_id,
                property_id=property_id,
                dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                error=error,
                title="Webhook Acceptance Rejected",
                persistent_event_type="webhook.acceptance_rejected",
                tone="warning",
            )
            return json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details=_acceptance_error_details(
                    request_id=request_id,
                    dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                    context=error.context,
                ),
            )
        except ApplicationError as error:
            _log_acceptance_failure(
                request=request,
                request_id=request_id,
                site_id=site_id,
                property_id=property_id,
                dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                error=error,
                title="Webhook Acceptance Failed",
                persistent_event_type="webhook.acceptance_failed",
                tone="failure",
            )
            return json_error(
                500,
                str(error),
                code=getattr(error, "code", "WEBHOOK_ACCEPTANCE_FAILED"),
                hint=getattr(error, "hint", None),
                details=_acceptance_error_details(
                    request_id=request_id,
                    dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                    context=getattr(error, "context", None),
                ),
            )
        except Exception as error:
            _log_acceptance_failure(
                request=request,
                request_id=request_id,
                site_id=site_id,
                property_id=property_id,
                dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                error=error,
                title="Webhook Acceptance Failed",
                persistent_event_type="webhook.acceptance_failed",
                tone="failure",
            )
            return json_error(
                500,
                "Failed to accept webhook delivery.",
                code="WEBHOOK_ACCEPTANCE_FAILED",
                hint=(
                    "Check the dated log folders under logs/MM-YYYY/DD-MM-YYYY for "
                    "errors.log, warnings-errors.log, and audit.jsonl with the "
                    "request_id and underlying acceptance failure."
                ),
                details=_acceptance_error_details(
                    request_id=request_id,
                    dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                ),
            )

        _log_acceptance_success(
            request_id=request_id,
            accepted_delivery=accepted_delivery,
            site_id=site_id,
            property_id=property_id,
            raw_payload_hash=raw_payload_hash,
            dispatcher_accepting_jobs=dispatcher_accepting_jobs,
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "event_id": accepted_delivery.event_id,
                "job_id": accepted_delivery.job_id,
                "site_id": site_id,
                "property_id": property_id,
                "site_auto_provisioned": accepted_delivery.tenant_auto_provisioned,
            },
        )

    return router


__all__ = [
    "WordPressWebhookSettings",
    "create_wordpress_webhook_router",
]
