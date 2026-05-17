"""FastAPI router for the agency reel-defaults endpoints.

`/v1/admin/agencies/{agency_id}/defaults` — read and update the global
reel rendering defaults. Defaults is the canonical owner of `platforms`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.configuration.application.use_cases.read_aggregated_reel_profile import (
    resolve_music_selection_rules,
)
from modules.configuration.application.use_cases.read_intro_asset import (
    ReadIntroAssetUseCase,
)
from modules.configuration.application.use_cases.read_outro_asset import (
    ReadOutroAssetUseCase,
)
from modules.configuration.application.use_cases.read_reel_defaults import (
    ReadReelDefaultsUseCase,
)
from modules.configuration.application.use_cases.update_reel_defaults import (
    UpdateReelDefaultsInput,
    UpdateReelDefaultsUseCase,
)
from modules.configuration.domain import IntroOutroAsset, ReelDefaults
from modules.configuration.transport.payloads.defaults import ReelDefaultsUpsertPayload
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


_DEFAULT_PLATFORMS = (
    "tiktok",
    "instagram",
    "linkedin",
    "youtube",
    "facebook",
    "gbp",
    "pinterest",
)


def create_defaults_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    read_reel_defaults: ReadReelDefaultsUseCase | None = None,
    update_reel_defaults: UpdateReelDefaultsUseCase | None = None,
    read_outro_asset: ReadOutroAssetUseCase | None = None,
    read_intro_asset: ReadIntroAssetUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Defaults"],
    )
    read_reel_defaults = read_reel_defaults or ReadReelDefaultsUseCase()
    update_reel_defaults = update_reel_defaults or UpdateReelDefaultsUseCase()
    read_outro_asset = read_outro_asset or ReadOutroAssetUseCase()
    read_intro_asset = read_intro_asset or ReadIntroAssetUseCase()

    @router.get(
        "/agencies/{agency_id}/defaults",
        summary="Read the agency's reel rendering defaults",
        description=(
            "Returns the defaults slice — platforms, target duration, "
            "intro toggle, default music, caption template and the "
            "free-form `settings` document used by the **Defaults** tab."
        ),
    )
    async def read_admin_agency_reel_defaults(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                record = read_reel_defaults.execute(uow=uow, agency_id=agency_id)
                outro_asset = read_outro_asset.execute(uow=uow, agency_id=agency_id)
                intro_asset = read_intro_asset.execute(uow=uow, agency_id=agency_id)
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
                "defaults": _serialize_defaults(
                    record,
                    agency_id=agency_id,
                    outro_asset=outro_asset,
                    intro_asset=intro_asset,
                ),
            },
        )

    @router.put(
        "/agencies/{agency_id}/defaults",
        summary="Update the agency's reel rendering defaults",
        description=(
            "Replaces only the defaults slice. `platforms` is mirrored "
            "verbatim to the canonical column (defaults owns this field). "
            "`settings` is shallow-merged with the previously stored "
            "object so partial updates from one tab do not drop fields "
            "written by another."
        ),
    )
    async def update_admin_agency_reel_defaults(
        agency_id: str,
        payload: ReelDefaultsUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                record = update_reel_defaults.execute(
                    uow=uow,
                    data=UpdateReelDefaultsInput(
                        agency_id=agency_id,
                        platforms=payload.platforms,
                        duration_seconds=payload.duration_seconds,
                        music_id=payload.music_id,
                        intro_enabled=payload.intro_enabled,
                        caption_template=payload.caption_template,
                        render_template_id=payload.render_template_id,
                        settings=payload.settings,
                        outro_enabled=payload.outro_enabled,
                    ),
                )
                outro_asset = read_outro_asset.execute(uow=uow, agency_id=agency_id)
                intro_asset = read_intro_asset.execute(uow=uow, agency_id=agency_id)
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
                code=getattr(error, "code", "REEL_DEFAULTS_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "saved",
                "agency_id": agency_id,
                "defaults": _serialize_defaults(
                    record,
                    agency_id=agency_id,
                    outro_asset=outro_asset,
                    intro_asset=intro_asset,
                ),
            },
        )

    return router


def _serialize_defaults(
    record: ReelDefaults | None,
    *,
    agency_id: str,
    outro_asset: IntroOutroAsset | None,
    intro_asset: IntroOutroAsset | None,
) -> dict[str, object]:
    outro_fields = _serialize_outro_asset(outro_asset)
    intro_fields = _serialize_intro_asset(intro_asset)
    if record is None:
        # Feature 24: surface the documented music selection-rule
        # default even for agencies that have never persisted a row,
        # so the frontend Toggle starts with a non-undefined value.
        return {
            "agency_id": agency_id,
            "platforms": list(_DEFAULT_PLATFORMS),
            "duration_seconds": 30,
            "music_id": "",
            "intro_enabled": True,
            "caption_template": "",
            "render_template_id": "classic",
            "settings": _settings_with_music_defaults({}),
            "outro_enabled": False,
            **outro_fields,
            **intro_fields,
            "created_at": "",
            "updated_at": "",
        }
    return {
        "agency_id": record.agency_id,
        "platforms": list(record.platforms),
        "duration_seconds": record.duration_seconds,
        "music_id": record.music_id,
        "intro_enabled": record.intro_enabled,
        "caption_template": record.caption_template,
        "render_template_id": record.render_template_id,
        "settings": _settings_with_music_defaults(dict(record.settings or {})),
        "outro_enabled": record.outro_enabled,
        **outro_fields,
        **intro_fields,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _serialize_outro_asset(
    asset: IntroOutroAsset | None,
) -> dict[str, object]:
    """Project the outro asset onto the canonical GET /defaults shape.

    The fields are emitted even when no asset row exists yet so the
    frontend can hydrate without a second roundtrip (mandatory contract
    from the feature 33 leader brief). ``outro_object_key`` is ``None``
    when nothing is uploaded; ``outro_duration_seconds`` is ``None``
    while the row is in ``'none'`` state.
    """
    if asset is None or asset.source != "uploaded" or not asset.object_key:
        source = asset.source if asset is not None else "none"
        return {
            "outro_object_key": None,
            "outro_duration_seconds": None,
            "outro_source": source,
        }
    return {
        "outro_object_key": asset.object_key,
        "outro_duration_seconds": int(asset.duration_seconds)
        if asset.duration_seconds > 0
        else None,
        "outro_source": asset.source,
    }


def _serialize_intro_asset(
    asset: IntroOutroAsset | None,
) -> dict[str, object]:
    """Project the intro asset onto the canonical GET /defaults shape.

    Feature 34: symmetric to :func:`_serialize_outro_asset`. The fields
    are emitted even when no asset row exists yet so the frontend can
    hydrate without a second roundtrip (mandatory contract from the
    leader brief).
    """
    if asset is None or asset.source != "uploaded" or not asset.object_key:
        source = asset.source if asset is not None else "none"
        return {
            "intro_object_key": None,
            "intro_duration_seconds": None,
            "intro_source": source,
        }
    return {
        "intro_object_key": asset.object_key,
        "intro_duration_seconds": int(asset.duration_seconds)
        if asset.duration_seconds > 0
        else None,
        "intro_source": asset.source,
    }


def _settings_with_music_defaults(settings: dict[str, object]) -> dict[str, object]:
    """Apply the music selection-rule defaults non-destructively.

    Feature 24: when ``music.selection_rules`` is absent the renderer
    behaves as if ``fallback_to_full_library=true``. The GET response
    surfaces that default so the frontend Toggle has a defined value
    even on a brand-new agency. The default is **not** persisted on
    write; it is only filled in on read.
    """
    rules = resolve_music_selection_rules(settings)
    raw_music = settings.get("music")
    music_dict: dict[str, object]
    if isinstance(raw_music, dict):
        music_dict = dict(raw_music)
    else:
        music_dict = {}
    music_dict["selection_rules"] = rules
    return {**settings, "music": music_dict}


__all__ = ["create_defaults_router"]
