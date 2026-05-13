"""FastAPI router for the agency social-templates endpoints.

`/v1/admin/agencies/{agency_id}/social-templates` — read and replace the
per-platform description templates used at publish time.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.configuration.application.use_cases.read_social_templates import (
    ReadSocialTemplatesUseCase,
)
from modules.configuration.application.use_cases.replace_social_templates import (
    ReplaceSocialTemplatesInput,
    ReplaceSocialTemplatesUseCase,
)
from modules.configuration.domain import SocialTemplate
from modules.configuration.domain.social_templates_variables import (
    ALLOWED_TEMPLATE_VARIABLES,
    find_unknown_template_variables,
)
from modules.configuration.transport.payloads.social_templates import (
    SocialTemplatesReplacePayload,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_social_templates_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    read_social_templates: ReadSocialTemplatesUseCase | None = None,
    replace_social_templates: ReplaceSocialTemplatesUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Social templates"],
    )
    read_social_templates = read_social_templates or ReadSocialTemplatesUseCase()
    replace_social_templates = (
        replace_social_templates or ReplaceSocialTemplatesUseCase()
    )

    @router.get(
        "/agencies/{agency_id}/social-templates",
        summary="Read the agency's per-platform description templates",
        description=(
            "Returns the templates map keyed by platform identifier "
            "(`instagram`, `tiktok`, `facebook`, `linkedin`, `youtube`, "
            "`gbp`, `pinterest`). Used by the **Social** tab to render the "
            "publish caption."
        ),
    )
    async def read_admin_agency_social_templates(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                records = read_social_templates.execute(uow=uow, agency_id=agency_id)
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
                "templates": _serialize_templates(records),
                "items": [_serialize_record(record) for record in records],
                "count": len(records),
            },
        )

    @router.put(
        "/agencies/{agency_id}/social-templates",
        summary="Replace the agency's per-platform description templates",
        description=(
            "Replaces the entire templates block: every existing per-platform "
            "row is dropped and re-inserted from the supplied map. Send an "
            "empty map to remove all templates."
        ),
    )
    async def replace_admin_agency_social_templates(
        agency_id: str,
        payload: SocialTemplatesReplacePayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        unknown_by_platform = _collect_unknown_template_variables(payload.templates or {})
        if unknown_by_platform:
            return _unknown_variable_response(unknown_by_platform)
        try:
            with unit_of_work_factory() as uow:
                records = replace_social_templates.execute(
                    uow=uow,
                    data=ReplaceSocialTemplatesInput(
                        agency_id=agency_id,
                        templates=dict(payload.templates or {}),
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
                code=getattr(error, "code", "SOCIAL_TEMPLATES_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "saved",
                "agency_id": agency_id,
                "templates": _serialize_templates(records),
                "items": [_serialize_record(record) for record in records],
                "count": len(records),
            },
        )

    return router


def _serialize_templates(records: tuple[SocialTemplate, ...]) -> dict[str, str]:
    return {record.platform: record.description_template for record in records}


def _serialize_record(record: SocialTemplate) -> dict[str, object]:
    return {
        "agency_id": record.agency_id,
        "platform": record.platform,
        "description_template": record.description_template,
        "title_template": record.title_template,
        "hashtags": list(record.hashtags),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _collect_unknown_template_variables(
    templates: dict[str, str],
) -> dict[str, list[str]]:
    """Return `{platform: [unknown_variable, ...]}` for every offending template.

    Platforms whose template references only allowed variables (or none at
    all) are omitted. Keys are normalized to the lowercase form the use case
    will persist, so the error message matches what the admin will see in
    the response of the next successful GET.
    """
    offences: dict[str, list[str]] = {}
    for raw_platform, template in (templates or {}).items():
        platform = str(raw_platform or "").strip().lower()
        if not platform:
            continue
        unknown = find_unknown_template_variables(str(template or ""))
        if unknown:
            offences[platform] = unknown
    return offences


def _unknown_variable_response(
    unknown_by_platform: dict[str, list[str]],
) -> JSONResponse:
    summary = ", ".join(
        f"{platform}: {{{{{', '.join(names)}}}}}"
        for platform, names in unknown_by_platform.items()
    )
    allowed_sorted = sorted(ALLOWED_TEMPLATE_VARIABLES)
    return json_error(
        422,
        (
            "One or more description templates reference unknown variables: "
            f"{summary}."
        ),
        code="SOCIAL_TEMPLATE_UNKNOWN_VARIABLE",
        hint=(
            "Use only the supported variables: "
            f"{', '.join(allowed_sorted)}."
        ),
        details={
            "unknown_variables_by_platform": unknown_by_platform,
            "allowed_variables": allowed_sorted,
        },
    )


__all__ = ["create_social_templates_router"]
