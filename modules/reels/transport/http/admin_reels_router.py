"""FastAPI router for the admin "Reels" surface.

Endpoints under `/v1/admin/agencies/{agency_id}/reels/*`:

- `GET    /`                               → list recent reels (use case `list_reels`)
- `GET    /{site_id}/{property_id}`        → reel detail (use case `inspect_reel`)
- `GET    /{site_id}/{property_id}/video`  → stream MP4 (range, transport helper)
- `GET    /{site_id}/{property_id}/images` → list source photos (transport helper)
- `GET    /{site_id}/{property_id}/images/{position}/file`
                                            → stream one source image (transport helper)
- `GET    /{site_id}/{property_id}/manifest`
                                            → JSON manifest (transport helper)
- `POST   /{site_id}/{property_id}/approve`
                                            → enqueue publish job (use case `regenerate_reel`).
                                              Path stays `/approve` for frontend compat.
- `POST   /{site_id}/{property_id}/reject` → mark workflow rejected (use case `reject_reel`)

The four asset GETs (video / images / image file / manifest) are pure
transport helpers (read a file, stream bytes); they do not warrant a
use case. They live in `admin_reels_assets.py` and are attached here
via :func:`register_admin_reel_asset_routes`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.reels.application.use_cases.inspect_reel import InspectReelUseCase
from modules.reels.application.use_cases.list_reels import (
    ListReelsUseCase,
    clamp_page,
    clamp_page_size,
    normalize_q,
)
from modules.reels.application.use_cases.regenerate_reel import (
    RegenerateAlreadyInFlight,
    RegeneratePublishedForbidden,
    RegenerateReelUseCase,
)
from modules.reels.application.use_cases.reject_reel import RejectReelUseCase
from modules.reels.application.use_cases.update_reel_descriptions_override import (
    ReelNotEditableError,
    UpdateReelDescriptionsOverrideUseCase,
)
from modules.reels.application.use_cases.update_reel_music_override import (
    UpdateReelMusicOverrideUseCase,
)
from modules.reels.application.use_cases.update_reel_photos_override import (
    ReelPhotosOverrideLockedError,
    UpdateReelPhotosOverrideUseCase,
)
from modules.reels.application.use_cases.update_reel_slides_override import (
    ReelSlidesOverrideLockedError,
    UpdateReelSlidesOverrideUseCase,
)
from modules.reels.application.use_cases.update_reel_subtitles_override import (
    ReelSubtitlesOverrideLockedError,
    UpdateReelSubtitlesOverrideUseCase,
)
from modules.reels.transport.http.admin_reels_assets import (
    _application_error_response,
    _resolve_workspace_path,
    _resource_not_found_response,
    _serialize_agency_reel,
    register_admin_reel_asset_routes,
)
from modules.reels.transport.payloads.reel_descriptions_override import (
    ReelDescriptionsOverridePayload,
)
from modules.reels.transport.payloads.reel_music_override import (
    ReelMusicOverridePayload,
)
from modules.reels.transport.payloads.reel_photos_override import (
    ReelPhotosOverridePayload,
)
from modules.reels.transport.payloads.admin_reels import (
    ReelManualRegeneratePayload,
    ReelSlidesOverridePayload,
)
from modules.reels.transport.payloads.reel_subtitles_override import (
    ReelSubtitlesOverridePayload,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


# Recognised pipeline states for the /reels listing filters (feature 32).
# The values mirror the strings the worker writes to ``reels.workflow_state``
# and ``reels.publish_status`` across the codebase. Unknown values produce
# a 422 INVALID_FILTER_VALUE so the frontend gets a deterministic error
# rather than silently empty results.
_VALID_WORKFLOW_STATES: frozenset[str] = frozenset(
    {
        "approved",
        "assets_prepared",
        "awaiting_review",
        "failed",
        "ingested",
        "needs_approval",
        "partial",
        "pending",
        "published",
        "rejected",
        "rendered",
        "skipped",
    }
)
_VALID_PUBLISH_STATUSES: frozenset[str] = frozenset(
    {
        "failed",
        "needs-approval",
        "needs_approval",
        "partial",
        "pending",
        "pending_publish",
        "pending_review",
        "published",
        "ready_to_publish",
        "rejected",
        "skipped",
    }
)


def _parse_csv_filter(
    raw: str | None,
    *,
    allowed: frozenset[str],
    param_name: str,
) -> tuple[str, ...] | None:
    """Parse a CSV query param into a normalised tuple.

    Empty / whitespace-only input collapses to ``None`` (no filter).
    Unknown values raise ``ValueError`` so the router can map them to a
    422 ``INVALID_FILTER_VALUE`` response instead of silently dropping
    them.
    """
    if raw is None:
        return None
    text_value = str(raw).strip()
    if not text_value:
        return None
    parts = [piece.strip() for piece in text_value.split(",")]
    cleaned = tuple(p for p in parts if p)
    if not cleaned:
        return None
    unknown = [value for value in cleaned if value not in allowed]
    if unknown:
        raise ValueError(
            f"Unknown {param_name} value(s): {', '.join(sorted(set(unknown)))}"
        )
    # De-duplicate while keeping the original order so the SQL bound
    # parameters stay deterministic for the tests.
    seen: set[str] = set()
    result: list[str] = []
    for value in cleaned:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def create_admin_reels_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    workspace_dir: str | Path,
    job_max_attempts: int,
    default_platforms: tuple[str, ...] = (),
    list_reels: ListReelsUseCase | None = None,
    inspect_reel: InspectReelUseCase | None = None,
    regenerate_reel: RegenerateReelUseCase | None = None,
    reject_reel: RejectReelUseCase | None = None,
    update_descriptions_override: UpdateReelDescriptionsOverrideUseCase | None = None,
    update_music_override: UpdateReelMusicOverrideUseCase | None = None,
    update_photos_override: UpdateReelPhotosOverrideUseCase | None = None,
    update_subtitles_override: UpdateReelSubtitlesOverrideUseCase | None = None,
    update_slides_override: UpdateReelSlidesOverrideUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Content"],
    )
    list_reels_use_case = list_reels or ListReelsUseCase()
    inspect_reel_use_case = inspect_reel or InspectReelUseCase()
    regenerate_reel_use_case = regenerate_reel or RegenerateReelUseCase(
        job_max_attempts=job_max_attempts,
        default_platforms=default_platforms,
    )
    reject_reel_use_case = reject_reel or RejectReelUseCase()
    update_descriptions_override_use_case = (
        update_descriptions_override or UpdateReelDescriptionsOverrideUseCase()
    )
    update_music_override_use_case = update_music_override or UpdateReelMusicOverrideUseCase(
        job_max_attempts=job_max_attempts,
        default_platforms=default_platforms,
    )
    update_photos_override_use_case = (
        update_photos_override
        or UpdateReelPhotosOverrideUseCase(
            job_max_attempts=job_max_attempts,
            default_platforms=default_platforms,
        )
    )
    update_subtitles_override_use_case = (
        update_subtitles_override
        or UpdateReelSubtitlesOverrideUseCase(
            job_max_attempts=job_max_attempts,
            default_platforms=default_platforms,
        )
    )
    update_slides_override_use_case = (
        update_slides_override
        or UpdateReelSlidesOverrideUseCase(
            job_max_attempts=job_max_attempts,
            default_platforms=default_platforms,
        )
    )
    resolved_workspace_dir = Path(workspace_dir).expanduser().resolve()

    @router.get(
        "/agencies/{agency_id}/reels",
        summary="List the agency's recent reels (paginated, filterable)",
        description=(
            "Returns a paginated slice of the agency's reels (feature 32).\n\n"
            "Query params:\n"
            "- ``page`` (int, default 1, clamped to >=1).\n"
            "- ``page_size`` (int, default 25, clamped to ``[1, 100]``).\n"
            "- ``workflow_state`` (CSV, optional). Filters by "
            "``reels.workflow_state``.\n"
            "- ``publish_status`` (CSV, optional). Filters by "
            "``reels.publish_status``.\n"
            "- ``q`` (string, optional). Case-insensitive ILIKE over "
            "``reels.title``, ``reels.slug`` and the related "
            "``properties.list_reference`` (property reference).\n"
            "- ``limit`` (int, legacy). If ``page`` is absent, "
            "``limit`` is interpreted as ``page_size`` with ``page=1``. "
            "If both are present, ``page_size`` wins and ``limit`` is "
            "ignored.\n\n"
            "Response shape: ``{items, count, count_total, page, "
            "page_size, has_more}`` where ``count == len(items)`` is "
            "preserved for backwards compatibility and ``count_total`` "
            "respects the active filters."
        ),
    )
    async def list_admin_agency_reels(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        query_params = request.query_params
        try:
            workflow_state_filter = _parse_csv_filter(
                query_params.get("workflow_state"),
                allowed=_VALID_WORKFLOW_STATES,
                param_name="workflow_state",
            )
            publish_status_filter = _parse_csv_filter(
                query_params.get("publish_status"),
                allowed=_VALID_PUBLISH_STATUSES,
                param_name="publish_status",
            )
        except ValueError as error:
            return json_error(
                422,
                str(error),
                code="INVALID_FILTER_VALUE",
                hint=(
                    "Use comma-separated values matching the canonical "
                    "workflow_state / publish_status set."
                ),
            )

        raw_page = query_params.get("page")
        raw_page_size = query_params.get("page_size")
        raw_limit = query_params.get("limit")
        # Backwards-compat: ``?limit=N`` keeps working when ``page`` is
        # absent. If both ``page_size`` and ``limit`` are present the
        # explicit ``page_size`` wins (documented in docs/API.md).
        if raw_page_size is None and raw_page is None and raw_limit is not None:
            page = 1
            page_size_input: str | int | None = raw_limit
        else:
            page = clamp_page(raw_page)
            page_size_input = raw_page_size
        page_size = clamp_page_size(page_size_input)
        q = normalize_q(query_params.get("q"))

        try:
            with unit_of_work_factory() as uow:
                result = list_reels_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    page=page,
                    page_size=page_size,
                    workflow_state=workflow_state_filter,
                    publish_status=publish_status_filter,
                    q=q,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)

        serialized = [_serialize_agency_reel(item) for item in result.items]
        has_more = result.page * result.page_size < result.count_total
        return JSONResponse(
            status_code=200,
            content={
                "items": serialized,
                "count": len(serialized),
                "count_total": int(result.count_total),
                "page": int(result.page),
                "page_size": int(result.page_size),
                "has_more": bool(has_more),
            },
        )

    @router.get(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}",
        summary="Get one reel for the agency",
        description=(
            "Same shape as one item from the listing endpoint, plus a "
            "`has_video` flag and a relative `video_url` to stream the "
            "rendered MP4."
        ),
    )
    async def get_admin_agency_reel(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                item = inspect_reel_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        body = _serialize_agency_reel(item)
        video_path = _resolve_workspace_path(
            resolved_workspace_dir, item.revision_media_path
        )
        body["has_video"] = video_path is not None
        body["video_url"] = (
            f"{admin_access_policy.base_path}/agencies/"
            f"{agency_id}/reels/{site_id}/{source_property_id}/video"
            if video_path is not None
            else None
        )
        return JSONResponse(status_code=200, content={"reel": body})

    register_admin_reel_asset_routes(
        router,
        unit_of_work_factory=unit_of_work_factory,
        admin_access_policy=admin_access_policy,
        inspect_reel_use_case=inspect_reel_use_case,
        resolved_workspace_dir=resolved_workspace_dir,
    )

    @router.post(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/approve",
        summary="Approve a reel and regenerate (re-publish) it",
        description=(
            "Two-step action.\n\n"
            "1. The reel is moved to `workflow_state='approved'` / "
            "`publish_status='pending_publish'` so the editor reflects the "
            "new gate immediately.\n"
            "2. A fresh `reel_publish` job is enqueued from the stored "
            "WordPress payload, with `approval_required=False` forced on "
            "the `publish_context`. If the original payload or the agency's "
            "GHL connection is missing, the response stays 200 with "
            "`publish_enqueued=false` so the frontend can render a "
            "consistent state."
        ),
    )
    async def approve_admin_agency_reel(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                result = regenerate_reel_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        except ValidationError as error:
            return json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return _application_error_response(error)
        body: dict[str, object] = {
            "status": "approved",
            "publish_enqueued": result.publish_enqueued,
            "reel": _serialize_agency_reel(result.reel),
        }
        if result.publish_enqueued:
            body["event_id"] = result.event_id
            body["job_id"] = result.job_id
            if result.idempotent_replay:
                body["idempotent_replay"] = True
            # Feature 11: surface the next scheduled publish slot
            # (ISO8601 UTC) when one was computed from the agency's
            # automation rules. Emit ``null`` rather than omitting the
            # key so the frontend can branch on ``payload.scheduled_at``
            # without worrying about presence vs absence. The shape
            # matches the cross-repo contract documented in
            # ``docs/API.md``.
            body["scheduled_at"] = result.scheduled_at
        else:
            body["reason"] = result.reason
            body["hint"] = result.hint
        return JSONResponse(status_code=200, content=body)

    @router.post(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/regenerate",
        summary="Manually re-render a reel without touching workflow/publish state",
        description=(
            "Feature 40 — editor's 'Render again' button.\n\n"
            "Re-enqueues a fresh ``reel_publish`` job for the reel with "
            "its current configuration and overrides "
            "(``photos_override`` / ``subtitles_override`` / "
            "``manifest_override``) without mutating "
            "``workflow_state`` or ``publish_status``. This is the "
            "sibling of ``POST .../approve`` — they share the same use "
            "case (``RegenerateReelUseCase``) but use a different "
            "``mode``.\n\n"
            "Body is optional: ``{}`` or no body is accepted. An "
            "optional ``reason`` (max 500 chars) is persisted on the "
            "new job's ``publish_context_json.manual_reason`` for "
            "traceability.\n\n"
            "Returns **409 REGENERATE_PUBLISHED_FORBIDDEN** when the "
            "reel is already ``publish_status='published'``, and **409 "
            "REGENERATE_ALREADY_IN_FLIGHT** when a ``reel_publish`` "
            "job is still ``queued`` / ``processing`` for the same "
            "property (the editor must wait for the running render to "
            "drain instead of stacking another one)."
        ),
    )
    async def regenerate_admin_agency_reel(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error

        # Body is optional. ``{}`` or no body are both accepted, but
        # any non-empty JSON must satisfy ``ReelManualRegeneratePayload``
        # (notably ``extra='forbid'``). FastAPI's body-as-argument path
        # would mark the body as required, so we parse manually.
        try:
            raw_body = await request.body()
        except Exception:  # pragma: no cover - defensive
            raw_body = b""
        payload: ReelManualRegeneratePayload
        if not raw_body or not raw_body.strip():
            payload = ReelManualRegeneratePayload()
        else:
            try:
                payload = ReelManualRegeneratePayload.model_validate_json(raw_body)
            except Exception as error:
                return json_error(
                    422,
                    "Invalid request body for the manual regenerate endpoint.",
                    code="INVALID_REGENERATE_PAYLOAD",
                    details={"errors": str(error)},
                )

        try:
            with unit_of_work_factory() as uow:
                result = regenerate_reel_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                    mode="manual_only",
                    manual_reason=payload.reason,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        except RegeneratePublishedForbidden as error:
            return JSONResponse(
                status_code=409,
                content={
                    "error": error.code,
                    "detail": (
                        "Cannot re-render a reel that has already been "
                        "published."
                    ),
                },
            )
        except RegenerateAlreadyInFlight as error:
            return JSONResponse(
                status_code=409,
                content={
                    "error": error.code,
                    "detail": (
                        "A render is already in progress for this reel. "
                        "Wait for it to finish."
                    ),
                },
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
            return _application_error_response(error)

        if not result.publish_enqueued:
            # Same prerequisite-missing semantics as the approve handler
            # (no GHL connection / no raw payload). The 200 status keeps
            # the contract symmetric so the frontend can render a
            # consistent "saved but not queued" state.
            return JSONResponse(
                status_code=200,
                content={
                    "render_status": "pending",
                    "job_id": None,
                    "queued_at": None,
                    "publish_enqueued": False,
                    "reason": result.reason,
                    "hint": result.hint,
                },
            )
        return JSONResponse(
            status_code=200,
            content={
                "render_status": "pending",
                "job_id": result.job_id,
                "queued_at": result.queued_at,
            },
        )

    @router.patch(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/descriptions",
        summary="Override the rendered captions for one reel",
        description=(
            "Persists a per-reel ``descriptions_override`` JSONB (feature 21) "
            "that wins over the auto-generated captions at publish time. "
            "Only reels still pending review accept overrides (publish_status "
            "in {pending, pending_review, needs-approval, ''}) — otherwise the "
            "endpoint returns **409 REEL_NOT_EDITABLE**. Platforms not listed "
            "in the agency's ``agency_reel_defaults.platforms`` produce a "
            "**422 PLATFORM_NOT_ENABLED**. The client always submits the full "
            "shape; the override is replaced wholesale and ``descriptions_by_platform={}`` "
            "clears it back to the templated captions."
        ),
    )
    async def patch_admin_agency_reel_descriptions(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        payload: ReelDescriptionsOverridePayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                result = update_descriptions_override_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                    descriptions_by_platform=payload.descriptions_by_platform,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        except ReelNotEditableError as error:
            return json_error(
                409,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": dict(error.context)} if error.context else None,
            )
        except ValidationError as error:
            return json_error(
                422,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": dict(error.context)} if error.context else None,
            )
        except ApplicationError as error:
            return _application_error_response(error)
        return JSONResponse(
            status_code=200,
            content={
                "status": "updated",
                "descriptions_by_platform": dict(
                    result.state.descriptions_override or {}
                ),
            },
        )

    @router.patch(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/music",
        summary="Override the background music for one reel",
        description=(
            "Persists ``reels.music_id`` (feature 25). ``music_id=null`` "
            "clears the override and the next render falls back to the "
            "agency pool (features 23/24). A non-null ``music_id`` must "
            "reference an ``agency_music_tracks`` row owned by the same "
            "agency — cross-agency / unknown ids surface **404 "
            "ADMIN_MUSIC_TRACK_NOT_FOUND**. Only reels still pending "
            "review accept overrides (``publish_status`` in "
            "``{pending, pending_review, needs-approval, ''}``); otherwise "
            "the endpoint returns **409 REEL_NOT_EDITABLE**. On success "
            "the use case re-enqueues a fresh ``reel_publish`` job "
            "(same machinery as ``POST /approve``) so the worker picks "
            "up the override and re-renders."
        ),
    )
    async def patch_admin_agency_reel_music(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        payload: ReelMusicOverridePayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                result = update_music_override_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                    music_id=payload.music_id,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        except ReelNotEditableError as error:
            return json_error(
                409,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": dict(error.context)} if error.context else None,
            )
        except ValidationError as error:
            return json_error(
                422,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": dict(error.context)} if error.context else None,
            )
        except ApplicationError as error:
            return _application_error_response(error)
        body: dict[str, object] = {
            "status": "saved",
            "reel_id": (
                f"{result.state.external_source_id}:{result.state.source_property_id}"
            ),
            "music_id": result.music_id,
            "publish_enqueued": result.publish_enqueued,
        }
        if result.publish_enqueued:
            body["event_id"] = result.event_id
            body["job_id"] = result.job_id
        else:
            body["reason"] = result.reason
            body["hint"] = result.hint
        return JSONResponse(status_code=200, content=body)

    @router.patch(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/photos",
        summary="Override the photo order / selection for one reel",
        description=(
            "Persists a per-reel ``photos_override`` JSONB array "
            "(feature 35). Each entry is a ``{position, selected}`` "
            "pair where ``position`` is the 0-indexed original photo "
            "slot and ``selected`` toggles whether the photo lands in "
            "the final reel. The submitted positions MUST cover the "
            "range ``[0, N)`` exactly once, where ``N`` is the number "
            "of photos in the property's catalog — anything else "
            "(gap, duplicate, out-of-range, wrong shape) is rejected "
            "with **422**. ``photos=null`` and ``photos=[]`` both "
            "clear the override and the next render falls back to the "
            "default order. The endpoint returns **409 "
            "PHOTOS_OVERRIDE_LOCKED** for reels that have already "
            "cleared the editorial gate (``workflow_state='approved'``"
            " or ``publish_status='published'``). A successful PATCH "
            "re-enqueues a fresh ``reel_publish`` job (same machinery "
            "as ``POST /approve`` and the music override endpoint) so "
            "the worker picks up the override and re-renders."
        ),
    )
    async def patch_admin_agency_reel_photos(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        payload: ReelPhotosOverridePayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        normalized_photos = (
            [entry.model_dump() for entry in payload.photos]
            if payload.photos is not None
            else None
        )
        try:
            with unit_of_work_factory() as uow:
                result = update_photos_override_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                    photos=normalized_photos,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        except ReelPhotosOverrideLockedError as error:
            return json_error(
                409,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": dict(error.context)} if error.context else None,
            )
        except ValidationError as error:
            return json_error(
                422,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": dict(error.context)} if error.context else None,
            )
        except ApplicationError as error:
            return _application_error_response(error)
        body: dict[str, object] = {
            "photos_override": result.photos_override,
            "render_status": result.state.render_status,
            "publish_enqueued": result.publish_enqueued,
        }
        if result.publish_enqueued:
            body["event_id"] = result.event_id
            body["job_id"] = result.job_id
        else:
            body["reason"] = result.reason
            body["hint"] = result.hint
        return JSONResponse(status_code=200, content=body)

    @router.patch(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/subtitles",
        summary="Override the rendered subtitles / captions for one reel",
        description=(
            "Persists a per-reel ``subtitles_override`` JSONB array "
            "(feature 36). Each cue is "
            "``{index:int, text:str, in_seconds:float, out_seconds:float}`` "
            "with ``index`` keys unique and monotonically increasing, "
            "``text`` 1-200 characters, ``in_seconds >= 0``, "
            "``out_seconds > in_seconds`` and non-overlapping windows "
            "across consecutive cues. Anything else (wrong type, empty "
            "/ over-long text, overlap, duplicate / non-monotonic index, "
            "extra field) is rejected with **422**. ``cues=null`` and "
            "``cues=[]`` both clear the override and the next render "
            "falls back to the historical autoCaptions flow (rendered "
            "when ``automation.autoCaptions`` is enabled, nothing "
            "otherwise). The endpoint returns **409 "
            "SUBTITLES_OVERRIDE_LOCKED** for reels that have already "
            "cleared the editorial gate (``workflow_state='approved'`` "
            "or ``publish_status='published'``). A successful PATCH "
            "re-enqueues a fresh ``reel_publish`` job (same machinery "
            "as ``POST /approve`` and the photos / music override "
            "endpoints) so the worker picks up the override and "
            "re-renders."
        ),
    )
    async def patch_admin_agency_reel_subtitles(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        payload: ReelSubtitlesOverridePayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        normalized_cues = (
            [entry.model_dump() for entry in payload.cues]
            if payload.cues is not None
            else None
        )
        try:
            with unit_of_work_factory() as uow:
                result = update_subtitles_override_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                    cues=normalized_cues,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        except ReelSubtitlesOverrideLockedError as error:
            return json_error(
                409,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": dict(error.context)} if error.context else None,
            )
        except ValidationError as error:
            return json_error(
                422,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": dict(error.context)} if error.context else None,
            )
        except ApplicationError as error:
            return _application_error_response(error)
        body: dict[str, object] = {
            "subtitles_override": result.subtitles_override,
            "render_status": result.state.render_status,
            "publish_enqueued": result.publish_enqueued,
        }
        if result.publish_enqueued:
            body["event_id"] = result.event_id
            body["job_id"] = result.job_id
        else:
            body["reason"] = result.reason
            body["hint"] = result.hint
        return JSONResponse(status_code=200, content=body)

    @router.patch(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/slides",
        summary="Override the slide manifest for one reel",
        description=(
            "Persists a per-reel ``manifest_override`` JSONB array "
            "(feature 37). Each slide carries ``slide_id`` (non-empty "
            "unique string), ``position`` (covering ``[0, N)`` exactly "
            "once), ``duration_seconds`` (positive float; the sum "
            "across slides must not exceed ``target_duration_seconds "
            "* 1.5``) and a ``kind`` discriminator selecting one of "
            "``photo`` / ``voiceover`` / ``text`` / ``intro_card`` / "
            "``outro_card`` plus the kind-specific required fields. "
            "Anything else (unknown ``kind``, missing per-kind field, "
            "position gap, duplicate ``slide_id``, duration cap "
            "exceeded, extra field) is rejected with **422**. "
            "``slides=null`` and ``slides=[]`` both clear the override "
            "and the next render falls back to the auto-generated "
            "manifest pipeline. The endpoint returns **409 "
            "SLIDES_OVERRIDE_LOCKED** for reels that have already "
            "cleared the editorial gate (``workflow_state='approved'`` "
            "or ``publish_status='published'``). A successful PATCH "
            "re-enqueues a fresh ``reel_publish`` job (same machinery "
            "as ``POST /approve`` and the photos / music / subtitles "
            "override endpoints) so the worker picks up the override "
            "and re-renders."
        ),
    )
    async def patch_admin_agency_reel_slides(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        payload: ReelSlidesOverridePayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        normalized_slides = (
            [entry.model_dump(exclude_none=True) for entry in payload.slides]
            if payload.slides is not None
            else None
        )
        try:
            with unit_of_work_factory() as uow:
                result = update_slides_override_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                    slides=normalized_slides,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        except ReelSlidesOverrideLockedError as error:
            return json_error(
                409,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": dict(error.context)} if error.context else None,
            )
        except ValidationError as error:
            return json_error(
                422,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": dict(error.context)} if error.context else None,
            )
        except ApplicationError as error:
            return _application_error_response(error)
        body: dict[str, object] = {
            "manifest_override": result.manifest_override,
            "render_status": result.state.render_status,
            "publish_enqueued": result.publish_enqueued,
        }
        if result.publish_enqueued:
            body["event_id"] = result.event_id
            body["job_id"] = result.job_id
        else:
            body["reason"] = result.reason
            body["hint"] = result.hint
        return JSONResponse(status_code=200, content=body)

    @router.post(
        "/agencies/{agency_id}/reels/{site_id}/{source_property_id}/reject",
        summary="Reject a reel",
        description=(
            "Sets the reel's pipeline state to `rejected` and the publish "
            "status to `rejected` so it stays out of the publish queue."
        ),
    )
    async def reject_admin_agency_reel(
        agency_id: str,
        site_id: str,
        source_property_id: int,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                item = reject_reel_use_case.execute(
                    uow=uow,
                    agency_id=agency_id,
                    site_id=site_id,
                    source_property_id=source_property_id,
                )
        except ResourceNotFoundError as error:
            return _resource_not_found_response(error)
        except ApplicationError as error:
            return _application_error_response(error)
        return JSONResponse(
            status_code=200,
            content={"status": "rejected", "reel": _serialize_agency_reel(item)},
        )

    return router


__all__ = ["create_admin_reels_router"]
