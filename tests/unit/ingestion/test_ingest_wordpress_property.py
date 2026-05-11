from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from modules.delivery.domain import JobEnqueueRequest
from modules.ingestion.application.use_cases.ingest_wordpress_property import (
    IngestWordPressPropertyInput,
    IngestWordPressPropertyUseCase,
)
from modules.ingestion.domain import IngestionSource
from modules.publishing.domain import ProviderConnectionWithSecrets
from shared.errors import ResourceNotFoundError


def test_ingest_wordpress_property_enqueues_job_with_provider_secret_bundle() -> None:
    use_case = IngestWordPressPropertyUseCase(job_max_attempts=3)
    sources = _SourcesRepo({"ckp.ie": _source("agency-1", "ckp.ie")})
    connections = _ConnectionsRepo(
        {("agency-1", "gohighlevel"): _ghl_connection("loc-1", "tok-abc")}
    )
    delivery = _DeliveryNamespace()
    configuration = _ConfigurationNamespace()
    uow = _uow(
        sources=sources,
        connections=connections,
        delivery=delivery,
        configuration=configuration,
    )

    accepted = use_case.execute(
        uow=uow,
        data=IngestWordPressPropertyInput(
            site_id="ckp.ie",
            property_id=42,
            raw_payload_hash="abc123",
            payload={"id": 42, "rest_domain": "ckp.ie", "title": "Sample"},
            default_platforms=("tiktok",),
        ),
    )

    assert accepted.agency_id == "agency-1"
    assert accepted.ingestion_source_id == "src-1"
    assert accepted.site_id == "ckp.ie"
    assert accepted.property_id == 42
    assert delivery.jobs.enqueued is not None
    enqueued: JobEnqueueRequest = delivery.jobs.enqueued
    assert enqueued.kind == "reel_publish"
    bundle = json.loads(enqueued.provider_secret_bundle)
    assert bundle == {"access_token": "tok-abc", "provider": "gohighlevel"}
    assert enqueued.payload == {"id": 42, "rest_domain": "ckp.ie", "title": "Sample"}
    assert enqueued.publish_context["provider"] == "gohighlevel"
    assert enqueued.publish_context["location_id"] == "loc-1"
    assert enqueued.publish_context["platforms"] == ["tiktok"]


def test_ingest_wordpress_property_supersedes_previous_jobs() -> None:
    use_case = IngestWordPressPropertyUseCase(job_max_attempts=1)
    sources = _SourcesRepo({"ckp.ie": _source("agency-1", "ckp.ie")})
    connections = _ConnectionsRepo(
        {("agency-1", "gohighlevel"): _ghl_connection("loc-1", "tok-abc")}
    )
    delivery = _DeliveryNamespace()
    delivery.jobs.superseded_event_ids = ("event-old",)

    use_case.execute(
        uow=_uow(
            sources=sources,
            connections=connections,
            delivery=delivery,
            configuration=_ConfigurationNamespace(),
        ),
        data=IngestWordPressPropertyInput(
            site_id="ckp.ie",
            property_id=42,
            raw_payload_hash="hash",
            payload={"id": 42, "rest_domain": "ckp.ie"},
            default_platforms=(),
        ),
    )

    assert delivery.jobs.supersede_called_with["external_source_id"] == "ckp.ie"
    assert delivery.jobs.supersede_called_with["property_id"] == 42
    assert delivery.webhook_events.status_updates == [
        ("event-old", "superseded", "Superseded by a newer queued job.")
    ]


def test_ingest_wordpress_property_raises_when_site_unknown() -> None:
    use_case = IngestWordPressPropertyUseCase(job_max_attempts=1)

    with pytest.raises(ResourceNotFoundError) as exc_info:
        use_case.execute(
            uow=_uow(
                sources=_SourcesRepo({}),
                connections=_ConnectionsRepo({}),
                delivery=_DeliveryNamespace(),
                configuration=_ConfigurationNamespace(),
            ),
            data=IngestWordPressPropertyInput(
                site_id="ghost.ie",
                property_id=None,
                raw_payload_hash="hash",
                payload={"id": 1},
                default_platforms=(),
            ),
        )
    assert exc_info.value.code == "UNKNOWN_WORDPRESS_SITE"


def test_ingest_wordpress_property_raises_when_ghl_connection_missing() -> None:
    use_case = IngestWordPressPropertyUseCase(job_max_attempts=1)
    sources = _SourcesRepo({"ckp.ie": _source("agency-1", "ckp.ie")})

    with pytest.raises(ResourceNotFoundError) as exc_info:
        use_case.execute(
            uow=_uow(
                sources=sources,
                connections=_ConnectionsRepo({}),
                delivery=_DeliveryNamespace(),
                configuration=_ConfigurationNamespace(),
            ),
            data=IngestWordPressPropertyInput(
                site_id="ckp.ie",
                property_id=1,
                raw_payload_hash="hash",
                payload={"id": 1},
                default_platforms=(),
            ),
        )
    assert exc_info.value.code == "GHL_CONNECTION_NOT_FOUND"


def _uow(*, sources, connections, delivery, configuration) -> SimpleNamespace:
    return SimpleNamespace(
        tenancy=SimpleNamespace(),
        ingestion=SimpleNamespace(sources=sources),
        publishing=SimpleNamespace(connections=connections),
        configuration=configuration,
        delivery=delivery,
    )


def _source(agency_id: str, external_id: str) -> IngestionSource:
    return IngestionSource(
        ingestion_source_id="src-1",
        agency_id=agency_id,
        kind="wordpress",
        external_id=external_id,
        name="CKP",
        status="active",
    )


def _ghl_connection(external_id: str, access_token: str) -> ProviderConnectionWithSecrets:
    return ProviderConnectionWithSecrets(
        connection_id="conn-1",
        agency_id="agency-1",
        provider="gohighlevel",
        external_id=external_id,
        config={"user_id": "u1"},
        status="active",
        has_secret=True,
        secrets={"access_token": access_token},
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

    def touch_last_event(self, ingestion_source_id: str) -> None:
        self.touched = ingestion_source_id


class _ConnectionsRepo:
    def __init__(self, records: dict[tuple[str, str], ProviderConnectionWithSecrets]) -> None:
        self.records = records

    def get_with_secrets(
        self, *, agency_id: str, provider: str
    ) -> ProviderConnectionWithSecrets | None:
        return self.records.get((agency_id, provider))


class _DeliveryNamespace:
    def __init__(self) -> None:
        self.jobs = _JobsRepo()
        self.webhook_events = _WebhookEventsRepo()


class _JobsRepo:
    def __init__(self) -> None:
        self.enqueued: JobEnqueueRequest | None = None
        self.supersede_called_with: dict = {}
        self.superseded_event_ids: tuple[str, ...] = ()

    def supersede_queued_jobs(
        self,
        *,
        external_source_id,
        property_id,
        superseded_by_job_id,
        finished_at=None,
    ) -> tuple[str, ...]:
        self.supersede_called_with = {
            "external_source_id": external_source_id,
            "property_id": property_id,
            "superseded_by_job_id": superseded_by_job_id,
            "finished_at": finished_at,
        }
        return self.superseded_event_ids

    def enqueue_job(self, request: JobEnqueueRequest) -> None:
        self.enqueued = request


class _WebhookEventsRepo:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.status_updates: list[tuple[str, str, str | None]] = []

    def create_event(self, **kwargs) -> None:
        self.created.append(kwargs)

    def update_event_status(self, event_id, *, status, error_message=None) -> None:
        self.status_updates.append((event_id, status, error_message))


class _ConfigurationNamespace:
    def __init__(self) -> None:
        self.defaults = SimpleNamespace(get=lambda agency_id: None)
        self.automation = SimpleNamespace(get=lambda agency_id: None)
        self.social_templates = SimpleNamespace(list_for_agency=lambda agency_id: ())
