"""Register a new ingestion source for an existing agency."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from modules.ingestion.application.use_cases._source_support import (
    DEFAULT_SOURCE_KIND,
    agency_not_found_error,
    normalize_external_id,
    normalize_kind,
    normalize_name,
    normalize_site_url,
    normalize_status,
)
from modules.ingestion.domain import IngestionSource
from shared.db import DatabaseUnitOfWork
from shared.errors import PipelineError, ValidationError


@dataclass(frozen=True, slots=True)
class RegisterIngestionSourceInput:
    agency_id: str
    name: str
    external_id: str
    kind: str = DEFAULT_SOURCE_KIND
    site_url: str | None = None
    normalized_host: str | None = None
    status: str | None = None
    secret: str = ""
    config: Mapping[str, Any] = field(default_factory=dict)


class RegisterIngestionSourceUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: RegisterIngestionSourceInput,
    ) -> IngestionSource:
        if uow.tenancy is None or uow.ingestion is None:
            raise RuntimeError("The unit of work is not active.")

        agency_id = str(data.agency_id or "").strip()
        if uow.tenancy.agencies.get_by_id(agency_id) is None:
            raise agency_not_found_error(agency_id)

        kind = normalize_kind(data.kind)
        external_id = normalize_external_id(data.external_id, field="site_id")
        name = normalize_name(data.name)
        status = normalize_status(data.status)

        if uow.ingestion.sources.get_by_kind_external_id(
            kind=kind, external_id=external_id
        ) is not None:
            raise ValidationError(
                "An ingestion source with that external_id already exists.",
                code="INGESTION_SOURCE_DUPLICATE",
                context={"kind": kind, "external_id": external_id},
                hint="Use a different external_id or update the existing source.",
            )

        config = dict(data.config or {})
        config.setdefault(
            "site_url",
            normalize_site_url(data.site_url, fallback_host=external_id),
        )
        config.setdefault(
            "normalized_host",
            normalize_external_id(
                data.normalized_host or external_id, field="normalized_host"
            ),
        )

        ingestion_source_id = str(uuid4())
        try:
            uow.ingestion.sources.create(
                ingestion_source_id=ingestion_source_id,
                agency_id=agency_id,
                kind=kind,
                external_id=external_id,
                name=name,
                config=config,
                secret=data.secret or "",
                status=status,
            )
        except IntegrityError as error:
            raise PipelineError(
                "The ingestion source could not be created.",
                stage="persistence",
                code="ADMIN_SOURCE_CREATE_FAILED",
                retryable=False,
                context={
                    "kind": kind,
                    "external_id": external_id,
                    "agency_id": agency_id,
                },
                cause=error,
            ) from error

        created = uow.ingestion.sources.get_by_id(ingestion_source_id)
        if created is None:
            raise PipelineError(
                "The ingestion source could not be reloaded after creation.",
                stage="persistence",
                code="ADMIN_SOURCE_RELOAD_FAILED",
                retryable=False,
                context={"ingestion_source_id": ingestion_source_id},
            )
        return created


__all__ = [
    "RegisterIngestionSourceInput",
    "RegisterIngestionSourceUseCase",
]
