"""Unit tests for the EnqueueScriptedRenderUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.delivery.domain import JobEnqueueRequest
from modules.ingestion.domain import IngestionSource
from modules.rendering.application.use_cases.enqueue_scripted_render import (
    EnqueueScriptedRenderInput,
    EnqueueScriptedRenderUseCase,
)
from modules.tenancy.domain import Agency
from shared.errors import ResourceNotFoundError, ValidationError


def test_enqueue_scripted_render_writes_event_and_job_with_scripted_kind() -> None:
    use_case = EnqueueScriptedRenderUseCase(job_max_attempts=3)
    sources = _SourcesRepo({"ckp.ie": _source("agency-1", "ckp.ie")})
    agencies = _AgenciesRepo({"agency-1": _agency("agency-1")})
    delivery = _DeliveryNamespace()

    enqueued = use_case.execute(
        uow=_uow(sources=sources, agencies=agencies, delivery=delivery),
        data=EnqueueScriptedRenderInput(
            site_id="CKP.ie",
            source_property_id=170800,
            raw_payload_hash="hash-1",
            payload={
                "site_id": "ckp.ie",
                "source_property_id": 170800,
                "title": "Sample",
                "slides": [{"image_path": "uploads/slide-01.jpg"}],
            },
        ),
    )

    assert enqueued.agency_id == "agency-1"
    assert enqueued.ingestion_source_id == "src-1"
    assert enqueued.site_id == "ckp.ie"
    assert enqueued.source_property_id == 170800
    assert delivery.jobs.enqueued is not None
    job_request: JobEnqueueRequest = delivery.jobs.enqueued
    assert job_request.kind == "scripted_render"
    assert job_request.external_source_id == "ckp.ie"
    assert job_request.property_id == 170800
    assert job_request.publish_context == {}
    assert job_request.provider_secret_bundle == ""
    assert job_request.payload["title"] == "Sample"
    assert job_request.max_attempts == 3
    assert delivery.webhook_events.created
    created_event = delivery.webhook_events.created[0]
    assert created_event["source_kind"] == "scripted_api"
    assert created_event["status"] == "queued"
    assert created_event["agency_id"] == "agency-1"
    assert created_event["ingestion_source_id"] == "src-1"


def test_enqueue_scripted_render_raises_when_site_unknown() -> None:
    use_case = EnqueueScriptedRenderUseCase(job_max_attempts=1)

    with pytest.raises(ResourceNotFoundError) as exc_info:
        use_case.execute(
            uow=_uow(
                sources=_SourcesRepo({}),
                agencies=_AgenciesRepo({}),
                delivery=_DeliveryNamespace(),
            ),
            data=EnqueueScriptedRenderInput(
                site_id="ghost.ie",
                source_property_id=1,
                raw_payload_hash="hash",
                payload={"site_id": "ghost.ie", "source_property_id": 1},
            ),
        )
    assert exc_info.value.code == "UNKNOWN_WORDPRESS_SITE"


def test_enqueue_scripted_render_raises_when_source_inactive() -> None:
    use_case = EnqueueScriptedRenderUseCase(job_max_attempts=1)
    sources = _SourcesRepo(
        {"ckp.ie": _source("agency-1", "ckp.ie", status="paused")}
    )

    with pytest.raises(ResourceNotFoundError) as exc_info:
        use_case.execute(
            uow=_uow(
                sources=sources,
                agencies=_AgenciesRepo({"agency-1": _agency("agency-1")}),
                delivery=_DeliveryNamespace(),
            ),
            data=EnqueueScriptedRenderInput(
                site_id="ckp.ie",
                source_property_id=1,
                raw_payload_hash="hash",
                payload={"site_id": "ckp.ie", "source_property_id": 1},
            ),
        )
    assert exc_info.value.code == "UNKNOWN_WORDPRESS_SITE"


def test_enqueue_scripted_render_raises_when_site_id_blank() -> None:
    use_case = EnqueueScriptedRenderUseCase(job_max_attempts=1)

    with pytest.raises(ValidationError) as exc_info:
        use_case.execute(
            uow=_uow(
                sources=_SourcesRepo({}),
                agencies=_AgenciesRepo({}),
                delivery=_DeliveryNamespace(),
            ),
            data=EnqueueScriptedRenderInput(
                site_id="   ",
                source_property_id=1,
                raw_payload_hash="hash",
                payload={"source_property_id": 1},
            ),
        )
    assert exc_info.value.code == "SITE_ID_REQUIRED"


def test_enqueue_scripted_render_raises_when_agency_missing() -> None:
    use_case = EnqueueScriptedRenderUseCase(job_max_attempts=1)
    sources = _SourcesRepo({"ckp.ie": _source("agency-1", "ckp.ie")})

    with pytest.raises(ResourceNotFoundError) as exc_info:
        use_case.execute(
            uow=_uow(
                sources=sources,
                agencies=_AgenciesRepo({}),
                delivery=_DeliveryNamespace(),
            ),
            data=EnqueueScriptedRenderInput(
                site_id="ckp.ie",
                source_property_id=42,
                raw_payload_hash="hash",
                payload={"site_id": "ckp.ie", "source_property_id": 42},
            ),
        )
    assert exc_info.value.code == "UNKNOWN_WORDPRESS_SITE"


def _uow(*, sources, agencies, delivery) -> SimpleNamespace:
    return SimpleNamespace(
        tenancy=SimpleNamespace(agencies=agencies),
        ingestion=SimpleNamespace(sources=sources),
        delivery=delivery,
    )


def _source(agency_id: str, external_id: str, *, status: str = "active") -> IngestionSource:
    return IngestionSource(
        ingestion_source_id="src-1",
        agency_id=agency_id,
        kind="wordpress",
        external_id=external_id,
        name="CKP",
        status=status,
    )


def _agency(agency_id: str) -> Agency:
    return Agency(
        agency_id=agency_id,
        name="Test Agency",
        slug="test-agency",
        timezone="UTC",
        status="active",
        created_at=None,
        updated_at=None,
    )


class _SourcesRepo:
    def __init__(self, records: dict[str, IngestionSource]) -> None:
        self.records = records

    def get_by_kind_external_id(
        self, *, kind: str, external_id: str
    ) -> IngestionSource | None:
        if kind != "wordpress":
            return None
        return self.records.get(external_id)


class _AgenciesRepo:
    def __init__(self, records: dict[str, Agency]) -> None:
        self.records = records

    def get_by_id(self, agency_id: str) -> Agency | None:
        return self.records.get(agency_id)


class _DeliveryNamespace:
    def __init__(self) -> None:
        self.jobs = _JobsRepo()
        self.webhook_events = _WebhookEventsRepo()


class _JobsRepo:
    def __init__(self) -> None:
        self.enqueued: JobEnqueueRequest | None = None

    def enqueue_job(self, request: JobEnqueueRequest) -> None:
        self.enqueued = request


class _WebhookEventsRepo:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create_event(self, **kwargs) -> None:
        self.created.append(kwargs)
