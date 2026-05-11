"""Private helpers shared by configuration use cases."""

from __future__ import annotations

from shared.errors import ResourceNotFoundError


def agency_not_found_error(agency_id: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(
        "The agency does not exist.",
        code="ADMIN_AGENCY_NOT_FOUND",
        context={"agency_id": str(agency_id or "").strip()},
    )


def music_track_not_found_error(music_id: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(
        "The music track does not exist.",
        code="MUSIC_TRACK_NOT_FOUND",
        context={"music_id": str(music_id or "").strip()},
    )


def ensure_agency_exists(uow, agency_id: str) -> None:
    if uow.tenancy is None:
        raise RuntimeError("The unit of work is not active.")
    agency = uow.tenancy.agencies.get_by_id(str(agency_id or "").strip())
    if agency is None:
        raise agency_not_found_error(agency_id)


__all__ = [
    "agency_not_found_error",
    "ensure_agency_exists",
    "music_track_not_found_error",
]
