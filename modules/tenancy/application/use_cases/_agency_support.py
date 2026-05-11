"""Private helpers shared by tenancy agency use cases."""

from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from shared.errors import PipelineError, ResourceNotFoundError, ValidationError

DEFAULT_AGENCY_STATUS = "active"
DEFAULT_AGENCY_TIMEZONE = "Europe/Dublin"

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def slugify_agency(value: str | None) -> str:
    raw_value = str(value or "").strip().lower()
    if not raw_value:
        return ""
    return _SLUG_PATTERN.sub("-", raw_value).strip("-")


def build_agency_slug(value: str | None) -> str:
    return slugify_agency(value) or slugify_agency(f"agency-{uuid4().hex[:8]}")


def agency_not_found_error(agency_id: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(
        "The agency does not exist.",
        code="ADMIN_AGENCY_NOT_FOUND",
        context={"agency_id": str(agency_id or "").strip()},
    )


def build_agency_write_error(
    error: IntegrityError,
    *,
    agency_id: str,
    slug: str,
    code: str,
    message: str,
) -> ValidationError | PipelineError:
    lowered_error = str(getattr(error, "orig", error)).lower()
    context = {
        "agency_id": str(agency_id or "").strip(),
        "slug": str(slug or "").strip().lower(),
    }
    if "slug" in lowered_error and ("duplicate" in lowered_error or "unique" in lowered_error):
        return ValidationError(
            "The agency slug is already in use.",
            code="ADMIN_AGENCY_SLUG_TAKEN",
            context=context,
            hint="Choose a different slug.",
            cause=error,
        )
    return PipelineError(
        message,
        stage="persistence",
        code=code,
        retryable=False,
        context=context,
        hint="Check the request payload and database constraints before retrying.",
        cause=error,
    )


__all__ = [
    "DEFAULT_AGENCY_STATUS",
    "DEFAULT_AGENCY_TIMEZONE",
    "agency_not_found_error",
    "build_agency_slug",
    "build_agency_write_error",
    "slugify_agency",
]
