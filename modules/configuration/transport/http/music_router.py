"""FastAPI router for the agency music-library endpoints.

`/v1/admin/agencies/{agency_id}/music` — full CRUD over agency music
tracks. Replaces the legacy `/music-tracks` stub.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from apps.api.error_handlers import json_error
from modules.configuration.application.use_cases.decommission_music_track import (
    DecommissionMusicTrackUseCase,
)
from modules.configuration.application.use_cases.inspect_music_track import (
    InspectMusicTrackUseCase,
)
from modules.configuration.application.use_cases.list_music_tracks import (
    ListMusicTracksUseCase,
)
from modules.configuration.application.use_cases.reconfigure_music_track import (
    ReconfigureMusicTrackInput,
    ReconfigureMusicTrackUseCase,
)
from modules.configuration.application.use_cases.register_music_track import (
    RegisterMusicTrackInput,
    RegisterMusicTrackUseCase,
)
from modules.configuration.domain import MusicTrack
from modules.configuration.transport.payloads.music import (
    MusicTrackPatchPayload,
    MusicTrackPayload,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError

UnitOfWorkFactory = Callable[[], ContextManager[DatabaseUnitOfWork]]


def create_music_router(
    *,
    unit_of_work_factory: UnitOfWorkFactory,
    admin_access_policy: AdminAccessPolicy,
    register_music_track: RegisterMusicTrackUseCase | None = None,
    list_music_tracks: ListMusicTracksUseCase | None = None,
    inspect_music_track: InspectMusicTrackUseCase | None = None,
    reconfigure_music_track: ReconfigureMusicTrackUseCase | None = None,
    decommission_music_track: DecommissionMusicTrackUseCase | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Music"],
    )
    register_music_track = register_music_track or RegisterMusicTrackUseCase()
    list_music_tracks = list_music_tracks or ListMusicTracksUseCase()
    inspect_music_track = inspect_music_track or InspectMusicTrackUseCase()
    reconfigure_music_track = reconfigure_music_track or ReconfigureMusicTrackUseCase()
    decommission_music_track = (
        decommission_music_track or DecommissionMusicTrackUseCase()
    )

    @router.post(
        "/agencies/{agency_id}/music",
        summary="Register a new music track for the agency",
        description=(
            "Adds a track to the agency music library. The `id` is "
            "generated server side; the response echoes the saved record."
        ),
    )
    async def register_admin_agency_music_track(
        agency_id: str,
        payload: MusicTrackPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                track = register_music_track.execute(
                    uow=uow,
                    data=RegisterMusicTrackInput(
                        agency_id=agency_id,
                        display_name=payload.display_name,
                        object_key=payload.object_key,
                        duration_seconds=payload.duration_seconds,
                        is_default=payload.is_default,
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
                code=getattr(error, "code", "MUSIC_TRACK_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=201,
            content={
                "status": "created",
                "agency_id": agency_id,
                "music_track": _serialize_track(track),
            },
        )

    @router.get(
        "/agencies/{agency_id}/music",
        summary="List the agency's music library",
        description=(
            "Returns every music track attached to the agency, ordered by "
            "display name. Replaces the legacy `/music-tracks` stub."
        ),
    )
    async def list_admin_agency_music_tracks(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                tracks = list_music_tracks.execute(uow=uow, agency_id=agency_id)
        except ResourceNotFoundError as error:
            return json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        items = [_serialize_track(track) for track in tracks]
        return JSONResponse(
            status_code=200,
            content={
                "agency_id": agency_id,
                "items": items,
                "count": len(items),
            },
        )

    @router.get(
        "/agencies/{agency_id}/music/{music_id}",
        summary="Inspect a single music track",
    )
    async def inspect_admin_agency_music_track(
        agency_id: str,
        music_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                track = inspect_music_track.execute(
                    uow=uow,
                    agency_id=agency_id,
                    music_id=music_id,
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
            content={
                "agency_id": agency_id,
                "music_track": _serialize_track(track),
            },
        )

    @router.put(
        "/agencies/{agency_id}/music/{music_id}",
        summary="Reconfigure an existing music track",
        description=(
            "Updates the descriptive fields of a music track. Omitted "
            "fields preserve the previously stored value."
        ),
    )
    async def reconfigure_admin_agency_music_track(
        agency_id: str,
        music_id: str,
        payload: MusicTrackPatchPayload,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                track = reconfigure_music_track.execute(
                    uow=uow,
                    data=ReconfigureMusicTrackInput(
                        agency_id=agency_id,
                        music_id=music_id,
                        display_name=payload.display_name,
                        object_key=payload.object_key,
                        duration_seconds=payload.duration_seconds,
                        is_default=payload.is_default,
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
                code=getattr(error, "code", "MUSIC_TRACK_SAVE_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "saved",
                "agency_id": agency_id,
                "music_track": _serialize_track(track),
            },
        )

    @router.delete(
        "/agencies/{agency_id}/music/{music_id}",
        summary="Decommission a music track from the agency library",
    )
    async def decommission_admin_agency_music_track(
        agency_id: str,
        music_id: str,
        request: Request,
    ) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        try:
            with unit_of_work_factory() as uow:
                decommission_music_track.execute(
                    uow=uow,
                    agency_id=agency_id,
                    music_id=music_id,
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
            content={
                "status": "deleted",
                "agency_id": agency_id,
                "music_id": music_id,
            },
        )

    return router


def _serialize_track(track: MusicTrack) -> dict[str, object]:
    return {
        "music_id": track.music_id,
        "agency_id": track.agency_id,
        "display_name": track.display_name,
        "object_key": track.object_key,
        "duration_seconds": track.duration_seconds,
        "is_default": track.is_default,
        "created_at": track.created_at,
    }


__all__ = ["create_music_router"]
