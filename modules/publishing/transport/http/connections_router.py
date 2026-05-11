"""FastAPI router for the agency-scoped GoHighLevel connection."""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.publishing.application.use_cases.attach_provider_connection import (
    AttachProviderConnectionInput,
    AttachProviderConnectionUseCase,
)
from modules.publishing.application.use_cases.detach_provider_connection import (
    DetachProviderConnectionUseCase,
)
from modules.publishing.application.use_cases.inspect_provider_connection import (
    InspectProviderConnectionUseCase,
)
from modules.publishing.application.use_cases.list_provider_connections import (
    ListProviderConnectionsUseCase,
)
from modules.publishing.application.use_cases.probe_provider_connection import (
    ProbeProviderConnectionUseCase,
)
from modules.publishing.application.use_cases.rotate_provider_credentials import (
    RotateProviderCredentialsInput,
    RotateProviderCredentialsUseCase,
)
from modules.publishing.domain import ProviderConnection, ProviderConnectionWithSecrets
from modules.publishing.transport.payloads.connections import (
    ProviderConnectionUpsertPayload,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_connections_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    attach_provider_connection: AttachProviderConnectionUseCase | None = None,
    rotate_provider_credentials: RotateProviderCredentialsUseCase | None = None,
    inspect_provider_connection: InspectProviderConnectionUseCase | None = None,
    detach_provider_connection: DetachProviderConnectionUseCase | None = None,
    list_provider_connections: ListProviderConnectionsUseCase | None = None,
    probe_provider_connection: ProbeProviderConnectionUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · GHL connection"],
    )
    attach_provider_connection = (
        attach_provider_connection or AttachProviderConnectionUseCase()
    )
    rotate_provider_credentials = (
        rotate_provider_credentials or RotateProviderCredentialsUseCase()
    )
    inspect_provider_connection = (
        inspect_provider_connection or InspectProviderConnectionUseCase()
    )
    detach_provider_connection = (
        detach_provider_connection or DetachProviderConnectionUseCase()
    )
    list_provider_connections = (
        list_provider_connections or ListProviderConnectionsUseCase()
    )
    probe_provider_connection = (
        probe_provider_connection or ProbeProviderConnectionUseCase()
    )

    @router.post(
        "/agencies/{agency_id}/ghl-connection",
        summary="Attach (or replace) the agency's GoHighLevel connection",
        description=(
            "Stores the `location_id` and OAuth tokens for the agency's GHL "
            "sub-account. Tokens are encrypted at rest with Fernet; the "
            "response never echoes the plaintext access or refresh token."
        ),
    )
    async def attach_admin_agency_ghl_connection(
        agency_id: str,
        payload: ProviderConnectionUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                connection = attach_provider_connection.execute(
                    uow=uow,
                    data=AttachProviderConnectionInput(
                        agency_id=agency_id,
                        location_id=payload.location_id,
                        access_token=payload.access_token,
                        user_id=payload.user_id,
                        refresh_token=payload.refresh_token,
                        expires_at=payload.expires_at,
                        status=payload.status,
                    ),
                )
        except ValidationError as error:
            return json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return json_error(
                500,
                str(error),
                code=getattr(error, "code", "GHL_CONNECTION_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "saved",
                "ghl_connection": _serialize_connection(connection, payload=payload),
            },
        )

    @router.put(
        "/agencies/{agency_id}/ghl-connection",
        summary="Rotate the agency's GoHighLevel credentials",
        description=(
            "Replaces the saved tokens for an agency that already has a "
            "GoHighLevel connection. Returns 404 (`GHL_CONNECTION_NOT_FOUND`) "
            "if no connection exists yet — use POST to attach one first."
        ),
    )
    async def rotate_admin_agency_ghl_credentials(
        agency_id: str,
        payload: ProviderConnectionUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                connection = rotate_provider_credentials.execute(
                    uow=uow,
                    data=RotateProviderCredentialsInput(
                        agency_id=agency_id,
                        location_id=payload.location_id,
                        access_token=payload.access_token,
                        user_id=payload.user_id,
                        refresh_token=payload.refresh_token,
                        expires_at=payload.expires_at,
                        status=payload.status,
                    ),
                )
        except ValidationError as error:
            return json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return json_error(
                500,
                str(error),
                code=getattr(error, "code", "GHL_CONNECTION_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "rotated",
                "ghl_connection": _serialize_connection(connection, payload=payload),
            },
        )

    @router.get(
        "/agencies/{agency_id}/ghl-connection",
        summary="Inspect the agency's GoHighLevel connection",
        description=(
            "Returns the saved connection metadata (location id, status, "
            "config, presence flags for tokens). The plaintext access and "
            "refresh tokens are never returned."
        ),
    )
    async def inspect_admin_agency_ghl_connection(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                connection = inspect_provider_connection.execute(
                    uow=uow,
                    agency_id=agency_id,
                )
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={"ghl_connection": _serialize_connection(connection)},
        )

    @router.delete(
        "/agencies/{agency_id}/ghl-connection",
        summary="Detach the agency's GoHighLevel connection",
        description=(
            "Deletes the connection. Subsequent webhooks for this agency will "
            "be rejected with `GHL_CONNECTION_NOT_FOUND` until a new "
            "connection is attached."
        ),
    )
    async def detach_admin_agency_ghl_connection(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                detach_provider_connection.execute(uow=uow, agency_id=agency_id)
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={"status": "deleted", "agency_id": agency_id},
        )

    @router.post(
        "/agencies/{agency_id}/ghl-connection/test",
        summary="Probe the agency's GoHighLevel connection",
        description=(
            "Calls the GHL accounts endpoint with the stored connection and "
            "returns the social accounts the location has linked. Useful to "
            "verify that the saved access token still works."
        ),
    )
    async def probe_admin_agency_ghl_connection(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                connection = inspect_provider_connection.execute(
                    uow=uow,
                    agency_id=agency_id,
                )
                accounts = probe_provider_connection.execute(
                    uow=uow,
                    location_id=connection.external_id,
                )
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return json_error(
                502,
                str(error),
                code=getattr(error, "code", "GHL_CONNECTION_TEST_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        accounts_payload = [_serialize_account(account) for account in accounts]
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "agency_id": agency_id,
                "location_id": connection.external_id,
                "account_count": len(accounts_payload),
                "accounts": accounts_payload,
            },
        )

    # The list use case has no dedicated route in this feature: it is exposed
    # so cross-module callers (e.g. the tenancy `inspect_agency` router) can
    # reuse it without binding to the connection repo directly. Keep it bound
    # to the router scope so the dependency is explicit at composition time.
    _ = list_provider_connections

    return router


def _serialize_connection(
    connection: ProviderConnection,
    *,
    payload: ProviderConnectionUpsertPayload | None = None,
) -> dict[str, object]:
    config = dict(connection.config or {})
    secrets: dict[str, object] = {}
    if isinstance(connection, ProviderConnectionWithSecrets):
        secrets = dict(connection.secrets or {})

    has_access_token = bool(str(secrets.get("access_token") or "").strip())
    has_refresh_token = bool(str(secrets.get("refresh_token") or "").strip())
    expires_at = str(secrets.get("expires_at") or config.get("expires_at") or "")

    if payload is not None:
        if not has_access_token:
            has_access_token = bool(str(payload.access_token or "").strip())
        if not has_refresh_token:
            has_refresh_token = bool(str(payload.refresh_token or "").strip())
        if not expires_at:
            expires_at = str(payload.expires_at or "")

    return {
        "connection_id": connection.connection_id,
        "agency_id": connection.agency_id,
        "provider": connection.provider,
        "location_id": connection.external_id,
        "user_id": str(config.get("user_id") or ""),
        "expires_at": expires_at,
        "status": connection.status,
        "has_secret": connection.has_secret,
        "has_access_token": has_access_token,
        "has_refresh_token": has_refresh_token,
        "created_at": connection.created_at,
        "updated_at": connection.updated_at,
    }


def _serialize_account(account: object) -> dict[str, object]:
    return {
        "id": getattr(account, "id", ""),
        "name": getattr(account, "name", ""),
        "platform": getattr(account, "platform", ""),
        "account_type": getattr(account, "account_type", ""),
        "is_expired": bool(getattr(account, "is_expired", False)),
    }


__all__ = ["create_connections_router"]
