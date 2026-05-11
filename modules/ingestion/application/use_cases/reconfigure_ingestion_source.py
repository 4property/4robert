"""Reconfigure mutable fields on an ingestion source."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from modules.ingestion.application.use_cases._source_support import (
    agency_not_found_error,
    normalize_external_id,
    normalize_name,
    normalize_site_url,
    normalize_status,
    source_not_found_error,
)
from modules.ingestion.domain import IngestionSource
from shared.db import DatabaseUnitOfWork
from shared.errors import PipelineError, ValidationError


@dataclass(frozen=True, slots=True)
class ReconfigureIngestionSourceInput:
    agency_id: str
    ingestion_source_id: str
    name: str | None = None
    site_url: str | None = None
    normalized_host: str | None = None
    status: str | None = None
    secret: str | None = None
    config: Mapping[str, Any] | None = None
    update_secret: bool = False


class ReconfigureIngestionSourceUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: ReconfigureIngestionSourceInput,
    ) -> IngestionSource:
        if uow.tenancy is None or uow.ingestion is None:
            raise RuntimeError("The unit of work is not active.")

        agency_id = str(data.agency_id or "").strip()
        if uow.tenancy.agencies.get_by_id(agency_id) is None:
            raise agency_not_found_error(agency_id)

        normalized_id = str(data.ingestion_source_id or "").strip()
        existing = uow.ingestion.sources.get_by_id(normalized_id)
        if existing is None:
            raise source_not_found_error(normalized_id)
        if existing.agency_id != agency_id:
            raise ValidationError(
                "Reassigning an ingestion source to a different agency is not supported.",
                code="ADMIN_SOURCE_AGENCY_MISMATCH",
                context={
                    "ingestion_source_id": normalized_id,
                    "expected_agency_id": existing.agency_id,
                    "requested_agency_id": agency_id,
                },
            )

        next_name = (
            normalize_name(data.name) if data.name is not None else existing.name
        )
        next_status = (
            normalize_status(data.status)
            if data.status is not None
            else existing.status
        )

        config = dict(data.config) if data.config is not None else dict(existing.config)
        if data.site_url is not None:
            config["site_url"] = normalize_site_url(
                data.site_url, fallback_host=existing.external_id
            )
        if data.normalized_host is not None:
            config["normalized_host"] = normalize_external_id(
                data.normalized_host, field="normalized_host"
            )
        config.setdefault("site_url", f"https://{existing.external_id}")
        config.setdefault("normalized_host", existing.external_id)

        secret_to_persist: str | None
        if data.update_secret:
            secret_to_persist = "" if data.secret is None else str(data.secret)
        else:
            secret_to_persist = None

        try:
            uow.ingestion.sources.update(
                ingestion_source_id=normalized_id,
                name=next_name,
                config=config,
                status=next_status,
                secret=secret_to_persist,
            )
        except Exception as error:  # pragma: no cover - defensive
            raise PipelineError(
                "The ingestion source could not be updated.",
                stage="persistence",
                code="ADMIN_SOURCE_UPDATE_FAILED",
                retryable=False,
                context={"ingestion_source_id": normalized_id},
                cause=error,
            ) from error

        updated = uow.ingestion.sources.get_by_id(normalized_id)
        if updated is None:
            raise PipelineError(
                "The ingestion source could not be reloaded after update.",
                stage="persistence",
                code="ADMIN_SOURCE_RELOAD_FAILED",
                retryable=False,
                context={"ingestion_source_id": normalized_id},
            )
        return updated


__all__ = [
    "ReconfigureIngestionSourceInput",
    "ReconfigureIngestionSourceUseCase",
]
