"""FastAPI router for GoHighLevel embedded sessions."""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import format_client
from apps.api.agency_token import issue_agency_token
from apps.api.error_handlers import json_error
from modules.publishing.application.use_cases.decode_session_context import (
    DecodeSessionContextUseCase,
    extract_gohighlevel_user_context_fields,
)
from modules.publishing.application.use_cases.inspect_session_status import (
    InspectSessionStatusUseCase,
)
from modules.publishing.application.use_cases.list_provider_sessions import (
    ListProviderSessionsUseCase,
)
from modules.publishing.application.use_cases.probe_provider_connection import (
    ProbeProviderConnectionUseCase,
)
from modules.publishing.transport.payloads.sessions import (
    GoHighLevelContextPayload,
    GoHighLevelLocationPayload,
    GoHighLevelSessionPayload,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError
from shared.observability import log_persistent_event

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_sessions_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    shared_secret: str,
    agency_token_secret: str = "",
    agency_token_ttl_seconds: int = 3600,
    admin_disable_auth_for_testing: bool = False,
    list_provider_sessions: ListProviderSessionsUseCase | None = None,
    decode_session_context: DecodeSessionContextUseCase | None = None,
    inspect_session_status: InspectSessionStatusUseCase | None = None,
    probe_provider_connection: ProbeProviderConnectionUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/sessions/gohighlevel",
        tags=["Session - GoHighLevel"],
    )
    list_provider_sessions = list_provider_sessions or ListProviderSessionsUseCase()
    decode_session_context = decode_session_context or DecodeSessionContextUseCase(
        shared_secret=shared_secret,
    )
    inspect_session_status = inspect_session_status or InspectSessionStatusUseCase()
    probe_provider_connection = probe_provider_connection or ProbeProviderConnectionUseCase()

    @router.get(
        "/tokens",
        summary="List every saved GoHighLevel connection",
        description=(
            "Returns one row per agency that has a stored GHL connection, "
            "with access tokens redacted. Used as a quick global health check."
        ),
    )
    async def list_gohighlevel_session_connections() -> JSONResponse:
        with unit_of_work_factory() as uow:
            result = list_provider_sessions.execute(uow=uow)
        return JSONResponse(status_code=200, content=result)

    @router.post(
        "/context",
        summary="Decrypt the GoHighLevel iframe SSO payload",
        description=(
            "Decrypts the embedded HighLevel userData blob with "
            "GO_HIGH_LEVEL_APP_SHARED_SECRET and returns the resolved session context."
        ),
    )
    async def resolve_gohighlevel_session_context(
        payload: GoHighLevelContextPayload,
        request: Request,
    ) -> JSONResponse:
        try:
            user_data = decode_session_context.execute(
                encrypted_data=payload.encrypted_data,
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
            return json_error(
                503,
                str(error),
                code=getattr(error, "code", "GHL_CONTEXT_DECRYPT_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        resolved_context = extract_gohighlevel_user_context_fields(user_data)
        if not resolved_context["location_id"]:
            return json_error(
                400,
                "The decrypted GoHighLevel context does not include activeLocation.",
                code="GHL_CONTEXT_LOCATION_MISSING",
                hint=(
                    "Open the app from a sub-account/location custom page. "
                    "Agency context does not include activeLocation."
                ),
                details={
                    "context_type": resolved_context["type"],
                    "has_user_id": bool(resolved_context["user_id"]),
                },
            )

        log_persistent_event(
            "sessions.gohighlevel_context_resolved",
            request_id=_get_request_id(request),
            client=format_client(request),
            location_id=resolved_context["location_id"],
            user_id=resolved_context["user_id"],
            context_type=resolved_context["type"],
        )
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "source": "ghl-sso-decrypted",
                **resolved_context,
                "user_data": user_data,
            },
        )

    @router.post(
        "/session",
        summary="Create or refresh the agency-bound session for a GHL location",
        description=(
            "Given the active location_id and user_id, returns whether the "
            "location has a saved access token and which agency it belongs to."
        ),
    )
    async def create_gohighlevel_session(
        payload: GoHighLevelSessionPayload,
        request: Request,
    ) -> JSONResponse:
        with unit_of_work_factory() as uow:
            session_status = inspect_session_status.execute(
                uow=uow,
                location_id=payload.location_id,
                user_id=payload.user_id,
            )
        log_persistent_event(
            "sessions.gohighlevel_session_checked",
            request_id=_get_request_id(request),
            client=format_client(request),
            location_id=session_status.location_id,
            user_id=session_status.user_id,
            connected=session_status.connected,
        )

        body = session_status.to_dict()
        if session_status.connected and session_status.agency_id:
            if not agency_token_secret:
                if not admin_disable_auth_for_testing:
                    return json_error(
                        503,
                        "The agency-scoped session token is not configured.",
                        code="AGENCY_AUTH_NOT_CONFIGURED",
                        hint=(
                            "Set ADMIN_AGENCY_TOKEN_SECRET in the environment "
                            "and restart the service before issuing sessions."
                        ),
                        details={"location_id": session_status.location_id},
                    )
            else:
                token, expires_at = issue_agency_token(
                    agency_id=session_status.agency_id,
                    location_id=session_status.location_id,
                    user_id=session_status.user_id,
                    secret=agency_token_secret,
                    ttl_seconds=int(agency_token_ttl_seconds),
                )
                body["agency_token"] = token
                body["agency_token_expires_at"] = _format_iso_utc(expires_at)

        return JSONResponse(status_code=200, content=body)

    @router.post(
        "/test",
        summary="Probe a GHL location's saved token and list its social accounts",
        description=(
            "Identical to the agency-scoped GoHighLevel connection test but "
            "keyed by location_id rather than agency_id."
        ),
    )
    async def test_gohighlevel_session_connection(
        payload: GoHighLevelLocationPayload,
        request: Request,
    ) -> JSONResponse:
        try:
            with unit_of_work_factory() as uow:
                accounts = probe_provider_connection.execute(
                    uow=uow,
                    location_id=payload.location_id,
                )
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"location_id": payload.location_id},
            )
        except ApplicationError as error:
            return json_error(
                502,
                str(error),
                code=getattr(error, "code", "GHL_CONNECTION_TEST_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        account_payload = [_serialize_account(account) for account in accounts]
        log_persistent_event(
            "sessions.gohighlevel_connection_tested",
            request_id=_get_request_id(request),
            client=format_client(request),
            location_id=payload.location_id,
            account_count=len(account_payload),
        )
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "location_id": payload.location_id,
                "account_count": len(account_payload),
                "accounts": account_payload,
            },
        )

    return router


def _format_iso_utc(value) -> str:
    """Render a UTC datetime as ISO-8601 with a trailing ``Z``."""
    text = value.isoformat()
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    return text


def _serialize_account(account: object) -> dict[str, object]:
    return {
        "id": getattr(account, "id", ""),
        "name": getattr(account, "name", ""),
        "platform": getattr(account, "platform", ""),
        "account_type": getattr(account, "account_type", ""),
        "is_expired": bool(getattr(account, "is_expired", False)),
    }


def _get_request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    if value in (None, ""):
        return None
    return str(value)


__all__ = ["create_sessions_router"]
