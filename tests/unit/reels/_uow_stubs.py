"""Lightweight UoW stubs used across reels admin use-case unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class StubAgencies:
    """In-memory stand-in for ``AgencyRepository``.

    Exposes the same ``get_by_id`` signature the real repo uses. The
    optional ``timezone`` kwarg (feature 14) lets tests assert that the
    use case forwards the agency's IANA timezone to
    ``compute_next_publish_slot``.
    """

    def __init__(
        self,
        *,
        present: bool = True,
        timezone: str = "UTC",
    ) -> None:
        self.present = present
        self.timezone = str(timezone or "UTC")
        self.calls: list[str] = []

    def get_by_id(self, agency_id: str) -> Any:
        self.calls.append(str(agency_id or ""))
        if not self.present:
            return None
        return SimpleNamespace(agency_id=agency_id, timezone=self.timezone)


class StubReelQuery:
    def __init__(
        self,
        *,
        items: tuple = (),
        count_total: int | None = None,
    ) -> None:
        self.items = tuple(items)
        self._count_total = count_total
        self.calls: list[dict[str, Any]] = []
        self.count_calls: list[dict[str, Any]] = []

    def list_recent_for_agency(
        self,
        *,
        agency_id: str,
        limit: int,
        offset: int = 0,
        workflow_state: tuple[str, ...] | None = None,
        publish_status: tuple[str, ...] | None = None,
        q: str | None = None,
    ) -> tuple:
        self.calls.append(
            {
                "agency_id": agency_id,
                "limit": limit,
                "offset": offset,
                "workflow_state": workflow_state,
                "publish_status": publish_status,
                "q": q,
            }
        )
        return self.items

    def count_for_agency(
        self,
        *,
        agency_id: str,
        workflow_state: tuple[str, ...] | None = None,
        publish_status: tuple[str, ...] | None = None,
        q: str | None = None,
    ) -> int:
        self.count_calls.append(
            {
                "agency_id": agency_id,
                "workflow_state": workflow_state,
                "publish_status": publish_status,
                "q": q,
            }
        )
        if self._count_total is not None:
            return int(self._count_total)
        return len(self.items)


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
    def __init__(self, *, active_job: Any = None) -> None:
        self.supersede_calls: list[dict[str, Any]] = []
        self.enqueue_calls: list[Any] = []
        self.find_active_calls: list[dict[str, Any]] = []
        self.active_job = active_job

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

    def find_active_job_for_property(
        self,
        *,
        external_source_id: str,
        property_id: int | None,
        kind: str = "reel_publish",
    ) -> Any:
        self.find_active_calls.append(
            {
                "external_source_id": external_source_id,
                "property_id": property_id,
                "kind": kind,
            }
        )
        return self.active_job

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
    agency_timezone: str = "UTC",
    agencies: StubAgencies | None = None,
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
        tenancy=SimpleNamespace(
            agencies=agencies
            or StubAgencies(present=agency_present, timezone=agency_timezone),
        ),
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
