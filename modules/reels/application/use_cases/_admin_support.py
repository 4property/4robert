"""Private helpers shared by admin reel use cases."""

from __future__ import annotations

from shared.errors import ResourceNotFoundError


def agency_not_found_error(agency_id: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(
        "The agency does not exist.",
        code="ADMIN_AGENCY_NOT_FOUND",
        context={"agency_id": str(agency_id or "").strip()},
    )


def reel_not_found_error(
    *,
    agency_id: str,
    site_id: str,
    source_property_id: int,
) -> ResourceNotFoundError:
    return ResourceNotFoundError(
        "The reel does not exist for this agency.",
        code="ADMIN_REEL_NOT_FOUND",
        context={
            "agency_id": str(agency_id or "").strip(),
            "site_id": str(site_id or "").strip().lower(),
            "source_property_id": int(source_property_id),
        },
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
    "reel_not_found_error",
]
