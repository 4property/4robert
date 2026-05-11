"""JSON error responses and FastAPI exception handlers for the API process."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from shared.errors import (
    ApplicationError,
    PipelineError,
    ResourceNotFoundError,
    ValidationError,
    extract_error_details,
)

logger = logging.getLogger(__name__)


def json_error(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    hint: str | None = None,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    """Build a structured JSON error response with the project's canonical shape."""
    payload: dict[str, object] = {"error": message}
    if code:
        payload["code"] = code
    if hint:
        payload["hint"] = hint
    if details:
        payload["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


def _status_code_for(error: ApplicationError) -> int:
    if isinstance(error, ValidationError):
        return 400
    if isinstance(error, ResourceNotFoundError):
        return 404
    return 500


def _build_application_error_payload(error: ApplicationError) -> dict[str, object]:
    details = extract_error_details(error)
    payload: dict[str, object] = {"error": str(error) or details.get("message", "")}
    code = details.get("code")
    if code:
        payload["code"] = code
    hint = details.get("hint") or getattr(error, "hint", None)
    if hint:
        payload["hint"] = hint
    context = details.get("context")
    extra: dict[str, object] = {}
    if isinstance(context, dict) and context:
        extra["context"] = context
    if isinstance(error, PipelineError):
        extra["stage"] = error.stage
        extra["retryable"] = error.retryable
        if error.external_trace_id:
            extra["external_trace_id"] = error.external_trace_id
    if extra:
        payload["details"] = extra
    return payload


def register_error_handlers(app: FastAPI) -> None:
    """Register the structured `ApplicationError` handler on `app`.

    The handler maps `ValidationError` to 400, `ResourceNotFoundError` to 404,
    and any other `ApplicationError` to 500. The body always carries the
    canonical `{error, code?, hint?, details?}` shape so the frontend can
    render the failure consistently.
    """

    async def handle_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        del request
        status_code = _status_code_for(exc)
        payload = _build_application_error_payload(exc)
        if status_code >= 500:
            logger.exception("Unhandled ApplicationError reached the transport layer.", exc_info=exc)
        return JSONResponse(status_code=status_code, content=payload)

    app.add_exception_handler(ApplicationError, handle_application_error)


__all__ = [
    "json_error",
    "register_error_handlers",
]
