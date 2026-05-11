"""Admin router for the agency social accounts endpoint.

Powers ``GET /v1/admin/agencies/{agency_id}/social-accounts``. Replaces
the legacy handler that lived in ``services/transport/http/server.py``.

The endpoint always returns 200; an unconfigured connection or an
upstream GoHighLevel failure yields ``connected=false`` (or
``connected=true`` with empty items + a ``reason`` code) so the admin
drawer can render an empty state without crashing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from modules.publishing.application.use_cases.inspect_agency_social_accounts import (
    AgencySocialAccountsResult,
    InspectAgencySocialAccountsUseCase,
)
from shared.db import DatabaseUnitOfWork

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_social_accounts_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    inspect_agency_social_accounts: InspectAgencySocialAccountsUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Content"],
    )
    inspect_use_case = (
        inspect_agency_social_accounts or InspectAgencySocialAccountsUseCase()
    )

    @router.get(
        "/agencies/{agency_id}/social-accounts",
        summary="List social accounts linked to the agency's GHL location",
        description=(
            "Wraps the GoHighLevel accounts API using the agency's stored "
            "connection. Always returns 200; if the agency has no GHL "
            "connection (or the call fails) the body has `connected: false` "
            "or `items: []` plus a `reason` code so the frontend can render "
            "an empty state without crashing."
        ),
    )
    async def list_admin_agency_social_accounts(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        result = inspect_use_case.execute(
            unit_of_work_factory=unit_of_work_factory,
            agency_id=agency_id,
        )
        return JSONResponse(
            status_code=200,
            content=_serialize(result),
        )

    return router


def _serialize(result: AgencySocialAccountsResult) -> dict[str, object]:
    if not result.connected:
        return {
            "ok": False,
            "agency_id": result.agency_id,
            "connected": False,
            "items": [],
            "count": 0,
            "reason": result.reason or "GHL_CONNECTION_NOT_FOUND",
        }
    if result.reason is not None:
        body: dict[str, object] = {
            "ok": False,
            "agency_id": result.agency_id,
            "connected": True,
            "location_id": result.location_id or "",
            "items": [],
            "count": 0,
            "reason": result.reason,
        }
        if result.error:
            body["error"] = result.error
        return body
    items = [
        {
            "id": account.id,
            "name": account.name,
            "platform": account.platform,
            "account_type": account.account_type,
            "is_expired": account.is_expired,
        }
        for account in result.items
    ]
    return {
        "ok": True,
        "agency_id": result.agency_id,
        "connected": True,
        "location_id": result.location_id or "",
        "count": len(items),
        "items": items,
    }


__all__ = ["create_social_accounts_router"]
