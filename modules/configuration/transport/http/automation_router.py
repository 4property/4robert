"""FastAPI router for the agency automation-rules endpoints.

`/v1/admin/agencies/{agency_id}/automation` — read and update the
publish-automation rules. `platforms` is owned by `/defaults`, not here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.configuration.application.use_cases.read_automation_rules import (
    ReadAutomationRulesUseCase,
)
from modules.configuration.application.use_cases.update_automation_rules import (
    UpdateAutomationRulesInput,
    UpdateAutomationRulesUseCase,
)
from modules.configuration.domain import AutomationRules
from modules.configuration.transport.payloads.automation import (
    AutomationRulesUpsertPayload,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]

_DEFAULT_PUBLISH_DAYS = ("mon", "tue", "wed", "thu", "fri")
_DEFAULT_TRIGGER_ON_STATUS = ("for_sale", "to_let")


def create_automation_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    read_automation_rules: ReadAutomationRulesUseCase | None = None,
    update_automation_rules: UpdateAutomationRulesUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Automation"],
    )
    read_automation_rules = read_automation_rules or ReadAutomationRulesUseCase()
    update_automation_rules = update_automation_rules or UpdateAutomationRulesUseCase()

    @router.get(
        "/agencies/{agency_id}/automation",
        summary="Read the agency's automation rules",
        description=(
            "Returns the automation slice: approval requirement, publish "
            "window, publish days and trigger statuses. `platforms` is NOT "
            "part of this slice — read it from `/defaults`."
        ),
    )
    async def read_admin_agency_automation_rules(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                record = read_automation_rules.execute(uow=uow, agency_id=agency_id)
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
            content={
                "agency_id": agency_id,
                "automation": _serialize_automation(record, agency_id=agency_id),
            },
        )

    @router.put(
        "/agencies/{agency_id}/automation",
        summary="Update the agency's automation rules",
        description=(
            "Replaces only the automation slice. `platforms` is intentionally "
            "rejected by the payload — its canonical owner is the `/defaults` "
            "endpoint."
        ),
    )
    async def update_admin_agency_automation_rules(
        agency_id: str,
        payload: AutomationRulesUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                record = update_automation_rules.execute(
                    uow=uow,
                    data=UpdateAutomationRulesInput(
                        agency_id=agency_id,
                        approval_required=payload.approval_required,
                        publish_window_start=payload.publish_window_start,
                        publish_window_end=payload.publish_window_end,
                        publish_days=payload.publish_days,
                        trigger_on_status=payload.trigger_on_status,
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
                code=getattr(error, "code", "AUTOMATION_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "saved",
                "agency_id": agency_id,
                "automation": _serialize_automation(record, agency_id=agency_id),
            },
        )

    return router


def _serialize_automation(
    record: AutomationRules | None,
    *,
    agency_id: str,
) -> dict[str, object]:
    if record is None:
        return {
            "agency_id": agency_id,
            "approval_required": False,
            "publish_window_start": "00:00",
            "publish_window_end": "23:59",
            "publish_days": list(_DEFAULT_PUBLISH_DAYS),
            "trigger_on_status": list(_DEFAULT_TRIGGER_ON_STATUS),
            "created_at": "",
            "updated_at": "",
        }
    return {
        "agency_id": record.agency_id,
        "approval_required": record.approval_required,
        "publish_window_start": record.publish_window_start,
        "publish_window_end": record.publish_window_end,
        "publish_days": list(record.publish_days),
        "trigger_on_status": list(record.trigger_on_status),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


__all__ = ["create_automation_router"]
