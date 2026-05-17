"""Register a new agency in the tenancy bounded context."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from modules.configuration.application.use_cases.seed_default_music_tracks import (
    seed_default_music_tracks_for_agency,
)
from modules.configuration.domain import build_default_social_templates
from modules.tenancy.domain import Agency
from shared.db import DatabaseUnitOfWork
from shared.errors import PipelineError, ValidationError

from modules.tenancy.application.use_cases._agency_support import (
    DEFAULT_AGENCY_STATUS,
    DEFAULT_AGENCY_TIMEZONE,
    build_agency_slug,
    build_agency_write_error,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RegisterAgencyInput:
    name: str
    slug: str | None = None
    timezone: str | None = None
    status: str | None = None


class RegisterAgencyUseCase:
    def execute(self, *, uow: DatabaseUnitOfWork, data: RegisterAgencyInput) -> Agency:
        if uow.tenancy is None:
            raise RuntimeError("The unit of work is not active.")
        normalized_name = str(data.name or "").strip()
        if not normalized_name:
            raise ValidationError(
                "The agency name is required.",
                code="ADMIN_AGENCY_NAME_REQUIRED",
                context={"field": "name"},
            )

        agency_id = str(uuid4())
        slug = build_agency_slug(data.slug or normalized_name)
        timezone = str(data.timezone or DEFAULT_AGENCY_TIMEZONE).strip() or DEFAULT_AGENCY_TIMEZONE
        status = str(data.status or DEFAULT_AGENCY_STATUS).strip().lower() or DEFAULT_AGENCY_STATUS

        try:
            uow.tenancy.agencies.create(
                agency_id=agency_id,
                name=normalized_name,
                slug=slug,
                timezone=timezone,
                status=status,
            )
        except IntegrityError as error:
            raise build_agency_write_error(
                error,
                agency_id=agency_id,
                slug=slug,
                code="ADMIN_AGENCY_CREATE_FAILED",
                message="The agency could not be created.",
            ) from error

        agency = uow.tenancy.agencies.get_by_id(agency_id)
        if agency is None:
            raise PipelineError(
                "The agency could not be created.",
                stage="persistence",
                code="ADMIN_AGENCY_CREATE_FAILED",
                retryable=False,
                context={"agency_id": agency_id, "slug": slug},
            )

        # Seed default social templates so the agency publishes a sensible
        # caption from day one. The configuration namespace is available
        # whenever the real UoW is open; tests often build a minimal UoW
        # via SimpleNamespace without `configuration` at all, so we use
        # getattr with a fallback and skip silently when missing — the
        # admin can still configure templates via /social later.
        configuration = getattr(uow, "configuration", None)
        if configuration is not None:
            configuration.social_templates.replace_all_for_agency(
                agency_id=agency_id,
                templates=build_default_social_templates(),
            )
        # Feature 23: seed the default NCS background music pool. The
        # workspace_dir is read off the UoW (app_factory wires it to
        # ``resolved_workspace``); when the test harness builds a UoW
        # without ``base_dir`` we skip silently — the admin can upload
        # tracks manually via /music/upload, and the seed migration
        # re-fills existing agencies on the next ``alembic upgrade``.
        if configuration is not None:
            workspace_dir = getattr(uow, "base_dir", None)
            if workspace_dir is not None:
                try:
                    seed_default_music_tracks_for_agency(
                        uow=uow,
                        agency_id=agency_id,
                        workspace_dir=Path(workspace_dir),
                    )
                except Exception:  # pragma: no cover - defensive logging
                    logger.exception(
                        "Failed to seed default music tracks for new agency %s.",
                        agency_id,
                    )
        return agency


__all__ = ["RegisterAgencyInput", "RegisterAgencyUseCase"]
