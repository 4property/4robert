"""Update the brand slice of an agency configuration.

Writes directly to `agency_brand_settings` via
`uow.configuration.brand.upsert(...)`. Other configuration sections
(defaults, automation, social_templates, music) are not touched.

Hotfix 2026-05-15: the "Reset to default" button on the frontend
sends ``null`` for the field it wants to clear. Pydantic does not
distinguish a missing key from a key whose value is ``null`` (both
arrive as ``None``), so callers can pass a ``fields_present`` frozenset
listing the keys that the client actually included in the JSON body.
Only those keys propagate to the repository — the rest fall through to
the repository's ``UNSET`` sentinel, preserving the existing column.
When ``fields_present`` is ``None`` (legacy callers and unit tests that
build the input directly), the previous "any non-``None`` value writes,
``None`` preserves" behaviour is recovered via translation here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from modules.configuration.domain import BrandSettings
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from modules.configuration.infrastructure.brand_repository import UNSET
from shared.db import DatabaseUnitOfWork


_BRAND_FIELDS: tuple[str, ...] = (
    "primary_color",
    "secondary_color",
    "logo_position",
    "logo_object_key",
    "intro_logo_object_key",
    "font_family",
)


@dataclass(frozen=True, slots=True)
class UpdateBrandSettingsInput:
    agency_id: str
    primary_color: str | None = None
    secondary_color: str | None = None
    logo_position: str | None = None
    logo_object_key: str | None = None
    intro_logo_object_key: str | None = None
    font_family: str | None = None
    # Names of the keys the HTTP client included in the JSON body. ``None``
    # means "legacy caller did not track explicit-vs-omitted" — the use
    # case then preserves the historical contract (any ``None`` here is
    # treated as "preserve the existing column"). When the router passes
    # an explicit frozenset, the use case respects ``null`` as "clear".
    fields_present: frozenset[str] | None = field(default=None)


class UpdateBrandSettingsUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: UpdateBrandSettingsInput,
    ) -> BrandSettings:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        agency_id = str(data.agency_id or "").strip()
        ensure_agency_exists(uow, agency_id)

        kwargs: dict[str, object] = {}
        for name in _BRAND_FIELDS:
            value = getattr(data, name)
            if data.fields_present is None:
                # Legacy caller (unit tests, internal helpers). Preserve
                # the historical contract: a ``None`` here means "did not
                # supply", so translate it to ``UNSET`` and keep the
                # existing column. Non-``None`` strings still propagate
                # verbatim and overwrite the column.
                kwargs[name] = UNSET if value is None else value
            else:
                # Router caller derived from
                # ``payload.model_dump(exclude_unset=True)``: a missing
                # key is genuinely absent and must be preserved (UNSET);
                # an explicit ``null`` clears the override (passed
                # through to the repo as ``None``).
                kwargs[name] = value if name in data.fields_present else UNSET

        return uow.configuration.brand.upsert(agency_id=agency_id, **kwargs)


__all__ = ["UpdateBrandSettingsInput", "UpdateBrandSettingsUseCase"]
