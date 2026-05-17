"""FastAPI router for the agency social-templates endpoints.

`/v1/admin/agencies/{agency_id}/social-templates` — read and replace the
per-platform description templates used at publish time.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ContextManager

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
from modules.configuration.domain import SocialTemplate, SocialTemplateUpsert
from modules.configuration.domain.social_templates_variables import (
    ALLOWED_TEMPLATE_VARIABLES,
    HASHTAG_PATTERN,
    MAX_HASHTAGS_PER_PLATFORM,
    find_invalid_hashtags,
    find_unknown_template_variables,
)
from modules.configuration.transport.payloads.social_templates import (
    SocialTemplateRichPayload,
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

        normalized_templates = _normalize_templates(payload.templates or {})

        unknown_by_platform = _collect_unknown_template_variables(normalized_templates)
        if unknown_by_platform:
            return _unknown_variable_response(unknown_by_platform)

        hashtag_errors = _collect_hashtag_errors(normalized_templates)
        if hashtag_errors:
            return _invalid_hashtag_response(hashtag_errors)

        try:
            with unit_of_work_factory() as uow:
                records = replace_social_templates.execute(
                    uow=uow,
                    data=ReplaceSocialTemplatesInput(
                        agency_id=agency_id,
                        templates=dict(normalized_templates),
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
    """Legacy flat shape kept for backward-compat.

    Earlier admin clients (and the 9 existing integration tests pinning the
    feature 11 contract) consume ``templates[platform]`` as a plain string —
    the description template. The frontend feature 20 reads the full rich
    fields from ``items[]`` instead. Keeping ``templates`` flat avoids a
    breaking change in the contract documented in `docs/API.md`.
    """
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


def _normalize_templates(
    raw_templates: dict[str, Any],
) -> dict[str, SocialTemplateUpsert]:
    """Collapse the payload union into the rich shape used downstream.

    A plain string value is interpreted as
    ``SocialTemplateRichPayload(description_template=string)`` so the legacy
    admin clients keep working without behavioural changes. Whitespace-only
    platform keys are dropped (matches the historical behaviour of the use
    case normaliser).
    """
    normalized: dict[str, SocialTemplateUpsert] = {}
    for raw_platform, value in (raw_templates or {}).items():
        platform = str(raw_platform or "").strip().lower()
        if not platform:
            continue
        if isinstance(value, SocialTemplateRichPayload):
            normalized[platform] = SocialTemplateUpsert(
                description_template=str(value.description_template or ""),
                title_template=str(value.title_template or ""),
                hashtags=tuple(str(tag) for tag in value.hashtags or ()),
            )
        else:
            normalized[platform] = SocialTemplateUpsert(
                description_template=str(value or ""),
                title_template="",
                hashtags=(),
            )
    return normalized


def _collect_unknown_template_variables(
    templates: dict[str, SocialTemplateUpsert],
) -> dict[str, dict[str, list[str]] | list[str]]:
    """Return offending platforms keyed by platform.

    The error payload shape is overloaded for backward-compat:

    - If only ``description_template`` contains unknown variables (the
      historical scenario), the value stays a flat ``list[str]`` so the
      9 existing integration tests pinned on
      ``{"instagram": ["cosa_inventada"]}`` keep working.
    - If ``title_template`` is involved (alone or together with the
      description), the value becomes a nested ``{field: [vars]}`` mapping
      that distinguishes both fields. This is the new shape the frontend
      feature 20 surfaces in its inline error UI.

    The mixed shape is intentional and documented in `docs/API.md`.
    """
    offences: dict[str, dict[str, list[str]] | list[str]] = {}
    for platform, upsert in templates.items():
        desc_unknown = find_unknown_template_variables(upsert.description_template)
        title_unknown = find_unknown_template_variables(upsert.title_template)
        if not desc_unknown and not title_unknown:
            continue
        if title_unknown:
            entry: dict[str, list[str]] = {}
            if desc_unknown:
                entry["description_template"] = desc_unknown
            entry["title_template"] = title_unknown
            offences[platform] = entry
        else:
            # Description-only error: keep the legacy flat shape.
            offences[platform] = desc_unknown
    return offences


def _unknown_variable_response(
    unknown_by_platform: dict[str, dict[str, list[str]] | list[str]],
) -> JSONResponse:
    summary_parts: list[str] = []
    for platform, entry in unknown_by_platform.items():
        if isinstance(entry, dict):
            for field, names in entry.items():
                summary_parts.append(
                    f"{platform}.{field}: {{{{{', '.join(names)}}}}}"
                )
        else:
            summary_parts.append(
                f"{platform}: {{{{{', '.join(entry)}}}}}"
            )
    summary = ", ".join(summary_parts)
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


def _collect_hashtag_errors(
    templates: dict[str, SocialTemplateUpsert],
) -> dict[str, dict[str, Any]]:
    """Return ``{platform: {invalid: [...], too_many: int|None}}`` entries.

    - ``invalid`` lists hashtag values that fail the
      ``^#[\\w-]{1,50}$`` regex (empty entries are reported as well, see
      ``find_invalid_hashtags``).
    - ``too_many`` carries the count when the list exceeds
      ``MAX_HASHTAGS_PER_PLATFORM`` so the admin sees both signals in one
      round-trip.

    Platforms with neither error are omitted.
    """
    errors: dict[str, dict[str, Any]] = {}
    for platform, upsert in templates.items():
        invalid = find_invalid_hashtags(list(upsert.hashtags))
        too_many = len(upsert.hashtags) > MAX_HASHTAGS_PER_PLATFORM
        if not invalid and not too_many:
            continue
        entry: dict[str, Any] = {}
        if invalid:
            entry["invalid"] = invalid
        if too_many:
            entry["count"] = len(upsert.hashtags)
            entry["max"] = MAX_HASHTAGS_PER_PLATFORM
        errors[platform] = entry
    return errors


def _invalid_hashtag_response(
    hashtag_errors: dict[str, dict[str, Any]],
) -> JSONResponse:
    parts: list[str] = []
    for platform, entry in hashtag_errors.items():
        if "invalid" in entry:
            parts.append(
                f"{platform} has invalid hashtags: "
                f"{', '.join(entry['invalid'])}"
            )
        if "count" in entry:
            parts.append(
                f"{platform} declares {entry['count']} hashtags but the "
                f"maximum is {entry['max']}"
            )
    summary = "; ".join(parts)
    return json_error(
        422,
        f"One or more platforms declared invalid hashtags: {summary}.",
        code="SOCIAL_TEMPLATE_INVALID_HASHTAG",
        hint=(
            "Each hashtag must match the regex "
            f"`{HASHTAG_PATTERN.pattern}` and the list cannot exceed "
            f"{MAX_HASHTAGS_PER_PLATFORM} entries."
        ),
        details={
            "hashtag_errors_by_platform": hashtag_errors,
            "pattern": HASHTAG_PATTERN.pattern,
            "max_hashtags_per_platform": MAX_HASHTAGS_PER_PLATFORM,
        },
    )


__all__ = ["create_social_templates_router"]
