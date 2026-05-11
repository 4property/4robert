"""FastAPI router for the scripted video render endpoint.

`POST /v1/videos/scripted/render` accepts a manifest, persists a `webhook_events`
audit row, enqueues a `scripted_render` job, and returns `202 Accepted` with
`{job_id, event_id}`. The worker process picks up the job and runs ffmpeg
asynchronously — the legacy synchronous behaviour (`201 Created` with
`{render_id, video_path, ...}`) is gone.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any, ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import format_client
from apps.api.error_handlers import json_error
from modules.rendering.application.use_cases.enqueue_scripted_render import (
    EnqueueScriptedRenderInput,
    EnqueueScriptedRenderUseCase,
)
from modules.rendering.transport.payloads.scripted import ScriptedRenderResponse
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError
from shared.observability import (
    format_console_block,
    format_detail_line,
    log_persistent_event,
)

logger = logging.getLogger(__name__)

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]
SCRIPTED_RENDER_ROUTE = "/videos" "/scripted/render"


def create_scripted_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    job_max_attempts: int,
    max_payload_bytes: int,
    enqueue_scripted_render: EnqueueScriptedRenderUseCase | None = None,
) -> APIRouter:
    """Build the scripted render router."""
    router = APIRouter(prefix="/v1", tags=["Video Rendering"])
    enqueue_scripted_render = enqueue_scripted_render or EnqueueScriptedRenderUseCase(
        job_max_attempts=job_max_attempts,
    )

    @router.post(
        SCRIPTED_RENDER_ROUTE,
        summary="Enqueue a scripted property video render",
        description=(
            "Validates the manifest's tenant fields (`site_id`, "
            "`source_property_id`), enqueues a `scripted_render` job, and "
            "returns 202 with `event_id` and `job_id`. The worker performs "
            "the ffmpeg render asynchronously."
        ),
        response_model=ScriptedRenderResponse,
        status_code=202,
    )
    async def enqueue_scripted_render_endpoint(request: Request) -> JSONResponse:
        content_type = request.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            return json_error(
                400,
                "Content-Type must be application/json.",
                code="INVALID_CONTENT_TYPE",
                hint=(
                    "Post the scripted render manifest as raw JSON with "
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
                    "Send a numeric Content-Length header or let the HTTP "
                    "client populate it automatically."
                ),
            )
        if content_length > max_payload_bytes:
            return json_error(
                413,
                "Request body is too large.",
                code="PAYLOAD_TOO_LARGE",
                hint=(
                    "Reduce the payload size or increase WEBHOOK_MAX_PAYLOAD_BYTES "
                    "on the API host."
                ),
                details={"max_payload_bytes": max_payload_bytes},
            )

        raw_body = await request.body()
        if len(raw_body) > max_payload_bytes:
            return json_error(
                413,
                "Request body is too large.",
                code="PAYLOAD_TOO_LARGE",
                hint=(
                    "Reduce the payload size or increase WEBHOOK_MAX_PAYLOAD_BYTES "
                    "on the API host."
                ),
                details={"max_payload_bytes": max_payload_bytes},
            )

        payload, payload_error = _parse_json_object_payload(raw_body)
        if payload_error is not None:
            return json_error(
                400,
                payload_error,
                code="INVALID_SCRIPTED_RENDER_PAYLOAD",
                hint="Send a single JSON object describing the scripted render request.",
            )
        assert payload is not None

        site_id_value = payload.get("site_id")
        if not isinstance(site_id_value, str) or not site_id_value.strip():
            return json_error(
                400,
                "The scripted render manifest must include a non-empty site_id.",
                code="SITE_ID_REQUIRED",
                hint="Set site_id to the WordPress site identifier (its ingestion_sources external_id).",
                details={"field": "site_id"},
            )

        source_property_id = _coerce_source_property_id(payload.get("source_property_id"))
        if source_property_id is None:
            return json_error(
                400,
                "The scripted render manifest must include a numeric source_property_id.",
                code="SOURCE_PROPERTY_ID_REQUIRED",
                hint="Set source_property_id to the integer property identifier coming from WordPress.",
                details={"field": "source_property_id"},
            )

        raw_payload_hash = hashlib.sha256(raw_body).hexdigest()

        try:
            with unit_of_work_factory() as uow:
                enqueued = enqueue_scripted_render.execute(
                    uow=uow,
                    data=EnqueueScriptedRenderInput(
                        site_id=site_id_value,
                        source_property_id=source_property_id,
                        raw_payload_hash=raw_payload_hash,
                        payload=payload,
                    ),
                )
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ValidationError as error:
            return json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            logger.exception(
                "Scripted render enqueue failed for %s",
                format_client(request),
            )
            return json_error(
                500,
                str(error),
                code=getattr(error, "code", "SCRIPTED_RENDER_ENQUEUE_FAILED"),
                hint=getattr(error, "hint", None),
                details={"context": error.context} if getattr(error, "context", None) else None,
            )

        logger.info(
            format_console_block(
                "Scripted Render Enqueued",
                format_detail_line("Event ID", enqueued.event_id),
                format_detail_line("Job ID", enqueued.job_id),
                format_detail_line("Site ID", enqueued.site_id),
                format_detail_line("Source Property ID", enqueued.source_property_id),
            )
        )
        log_persistent_event(
            "scripted_render.enqueued",
            event_id=enqueued.event_id,
            job_id=enqueued.job_id,
            agency_id=enqueued.agency_id,
            ingestion_source_id=enqueued.ingestion_source_id,
            site_id=enqueued.site_id,
            source_property_id=enqueued.source_property_id,
            raw_payload_hash=raw_payload_hash,
        )

        body = ScriptedRenderResponse(
            status="accepted",
            job_id=enqueued.job_id,
            event_id=enqueued.event_id,
            site_id=enqueued.site_id,
            source_property_id=enqueued.source_property_id,
        )
        return JSONResponse(status_code=202, content=body.model_dump())

    return router


def _parse_content_length(raw_value: str | None) -> int | None:
    if raw_value is None:
        return 0
    try:
        content_length = int(raw_value)
    except ValueError:
        return None
    return max(content_length, 0)


def _parse_json_object_payload(
    raw_body: bytes,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except UnicodeDecodeError:
        return None, "Request body must be UTF-8 encoded JSON."
    except json.JSONDecodeError as exc:
        return (
            None,
            (
                f"Request body must be valid JSON. {exc.msg} at line "
                f"{exc.lineno}, column {exc.colno}."
            ),
        )

    if not isinstance(parsed, dict):
        return None, "Request body must be a JSON object."

    return parsed, None


def _coerce_source_property_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


__all__ = ["create_scripted_router"]
