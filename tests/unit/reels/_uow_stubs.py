"""Lightweight UoW stubs used across reels admin use-case unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class StubAgencies:
    def __init__(self, *, present: bool = True) -> None:
        self.present = present

    def get_by_id(self, agency_id: str) -> Any:
        if not self.present:
            return None
        return SimpleNamespace(agency_id=agency_id)


class StubReelQuery:
    def __init__(self, *, items: tuple = ()) -> None:
        self.items = tuple(items)
        self.calls: list[dict[str, Any]] = []

    def list_recent_for_agency(
        self, *, agency_id: str, limit: int
    ) -> tuple:
        self.calls.append({"agency_id": agency_id, "limit": limit})
        return self.items


class StubReelStates:
    def __init__(self, *, existing: Any = None) -> None:
        self.existing = existing
        self.workflow_calls: list[dict[str, Any]] = []
        self.publish_calls: list[dict[str, Any]] = []

    def get(self, *, external_source_id: str, source_property_id: int) -> Any:
        return self.existing

    def update_workflow_state(self, **kwargs: Any) -> None:
        self.workflow_calls.append(kwargs)

    def update_publish_status(self, **kwargs: Any) -> None:
        self.publish_calls.append(kwargs)


class StubProperties:
    def __init__(self, *, raw_payload: str | None = None) -> None:
        self.raw_payload = raw_payload

    def get_raw_payload(
        self, *, external_source_id: str, source_property_id: int
    ) -> str | None:
        del external_source_id, source_property_id
        return self.raw_payload


class StubImages:
    def __init__(self, *, items: tuple = ()) -> None:
        self.items = tuple(items)

    def list_for_property(
        self, *, external_source_id: str, source_property_id: int
    ) -> tuple:
        del external_source_id, source_property_id
        return self.items


class StubProviderConnections:
    def __init__(self, *, connection: Any = None) -> None:
        self.connection = connection

    def get_with_secrets(self, *, agency_id: str, provider: str) -> Any:
        del agency_id, provider
        return self.connection


class StubDefaults:
    def __init__(self, *, existing: Any = None) -> None:
        self.existing = existing

    def get(self, agency_id: str) -> Any:
        del agency_id
        return self.existing


class StubAutomation:
    def __init__(self, *, existing: Any = None) -> None:
        self.existing = existing

    def get(self, agency_id: str) -> Any:
        del agency_id
        return self.existing


class StubSocialTemplates:
    def __init__(self, *, items: tuple = ()) -> None:
        self.items = tuple(items)

    def list_for_agency(self, agency_id: str) -> tuple:
        del agency_id
        return self.items


class StubJobs:
    def __init__(self) -> None:
        self.supersede_calls: list[dict[str, Any]] = []
        self.enqueue_calls: list[Any] = []

    def supersede_queued_jobs(
        self,
        *,
        external_source_id: str,
        property_id: int | None,
        superseded_by_job_id: str,
        finished_at: str | None = None,
    ) -> tuple[str, ...]:
        self.supersede_calls.append(
            {
                "external_source_id": external_source_id,
                "property_id": property_id,
                "superseded_by_job_id": superseded_by_job_id,
                "finished_at": finished_at,
            }
        )
        return ()

    def enqueue_job(self, request: Any) -> None:
        self.enqueue_calls.append(request)


class StubWebhookEvents:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.status_calls: list[tuple[str, dict[str, Any]]] = []

    def create_event(self, **kwargs: Any) -> None:
        self.create_calls.append(kwargs)

    def update_event_status(
        self, event_id: str, **kwargs: Any
    ) -> None:
        self.status_calls.append((event_id, kwargs))


def build_uow(
    *,
    agency_present: bool = True,
    queries: StubReelQuery | None = None,
    states: StubReelStates | None = None,
    properties: StubProperties | None = None,
    images: StubImages | None = None,
    connections: StubProviderConnections | None = None,
    defaults: StubDefaults | None = None,
    automation: StubAutomation | None = None,
    social_templates: StubSocialTemplates | None = None,
    jobs: StubJobs | None = None,
    webhook_events: StubWebhookEvents | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        tenancy=SimpleNamespace(agencies=StubAgencies(present=agency_present)),
        reels=SimpleNamespace(
            states=states or StubReelStates(),
            queries=queries or StubReelQuery(),
        ),
        catalog=SimpleNamespace(
            properties=properties or StubProperties(),
            images=images or StubImages(),
        ),
        publishing=SimpleNamespace(
            connections=connections or StubProviderConnections(),
        ),
        configuration=SimpleNamespace(
            defaults=defaults or StubDefaults(),
            automation=automation or StubAutomation(),
            social_templates=social_templates or StubSocialTemplates(),
        ),
        delivery=SimpleNamespace(
            jobs=jobs or StubJobs(),
            webhook_events=webhook_events or StubWebhookEvents(),
        ),
    )


def make_summary(
    *,
    external_source_id: str = "site-a",
    source_property_id: int = 7,
    workflow_state: str = "rendered",
    publish_status: str = "ready_to_publish",
    revision_media_path: str = "",
    revision_metadata_path: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        external_source_id=external_source_id,
        source_property_id=source_property_id,
        slug="test",
        title="Test",
        link=None,
        price=None,
        property_status=None,
        property_type_label=None,
        property_area_label=None,
        property_county_label=None,
        bedrooms=None,
        bathrooms=None,
        featured_image_url=None,
        agent_name=None,
        workflow_state=workflow_state,
        publish_status=publish_status,
        render_status="completed",
        last_published_provider_external_id="",
        pipeline_updated_at="",
        pipeline_created_at="",
        fetched_at="",
        current_revision_id="",
        revision_media_path=revision_media_path,
        revision_metadata_path=revision_metadata_path,
        revision_artifact_kind="",
        revision_created_at="",
    )


__all__ = [
    "StubAgencies",
    "StubAutomation",
    "StubDefaults",
    "StubImages",
    "StubJobs",
    "StubProperties",
    "StubProviderConnections",
    "StubReelQuery",
    "StubReelStates",
    "StubSocialTemplates",
    "StubWebhookEvents",
    "build_uow",
    "make_summary",
]
