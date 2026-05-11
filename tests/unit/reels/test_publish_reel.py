"""Unit tests for `PublishReelUseCase` (no DB).

Persistence calls hit inline UoW stubs that record kwargs for assertion;
the social provider is faked with `_FakePublisher` and the local
publisher with `_StubLocalPublisher`. Covers all branches:
`publish_completed`, `partial`, `awaiting_review` (per-agency &
env-flag), `skipped` (no provider, no requires_external, provider
returns `None`), `failed` (raises that includes a result), and the
`execute_existing` validation path.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from modules.catalog.domain.wordpress_property import Property
from modules.reels.domain.types import (
    MediaDeliveryPlan,
    PlatformPublishTargetPlan,
    PropertyContext,
    PublishedMediaArtifact,
    RenderedMediaArtifact,
    SocialPublishContext,
)
from modules.tenancy.domain.context import TenantContext
from shared.errors import (
    SocialPublishingResultError,
    TransientSocialPublishingResultError,
    ValidationError,
)
from modules.reels.application.use_cases.publish_reel import PublishReelUseCase
from modules.reels.domain import MediaRevision
from shared.storage.site_layout import resolve_site_storage_layout


_PAYLOAD = {
    "id": 11,
    "slug": "casa-publica",
    "title": {"rendered": "Casa Publica"},
    "link": "https://example.com/casa-publica",
    "property_status": "for sale",
    "price": "200000",
    "wppd_pics": ["https://example.com/imgA.jpg"],
}


# ---------------------------------------------------------------------------
# UoW stubs
# ---------------------------------------------------------------------------


class _StubReelStates:
    def __init__(self) -> None:
        self.publish_calls: list[dict[str, Any]] = []
        self.workflow_calls: list[dict[str, Any]] = []

    def update_publish_status(self, **kwargs: Any) -> None:
        self.publish_calls.append(kwargs)

    def update_workflow_state(self, **kwargs: Any) -> None:
        self.workflow_calls.append(kwargs)


class _StubMediaRevisions:
    def __init__(self) -> None:
        self.save_calls: list[MediaRevision] = []

    def save_revision(self, record: MediaRevision) -> None:
        self.save_calls.append(record)


class _StubOutbox:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


def _build_uow(
    *,
    states: _StubReelStates | None = None,
    revisions: _StubMediaRevisions | None = None,
    outbox: _StubOutbox | None = None,
) -> Any:
    return SimpleNamespace(
        reels=SimpleNamespace(
            states=states or _StubReelStates(),
            revisions=revisions or _StubMediaRevisions(),
        ),
        delivery=SimpleNamespace(
            outbox=outbox or _StubOutbox(),
        ),
    )


# ---------------------------------------------------------------------------
# Provider stub
# ---------------------------------------------------------------------------


class _FakePublisher:
    def __init__(
        self,
        *,
        result: Any = None,
        raises: Exception | None = None,
    ) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[tuple[Any, Any]] = []

    def publish_property_media(
        self, context: PropertyContext, published_media: PublishedMediaArtifact
    ) -> Any:
        self.calls.append((context, published_media))
        if self.raises is not None:
            raise self.raises
        return self.result


# ---------------------------------------------------------------------------
# Local publisher stub
# ---------------------------------------------------------------------------


class _StubLocalPublisher:
    def __init__(self, *, published_media: PublishedMediaArtifact) -> None:
        self.published_media = published_media
        self.publish_media_calls: list[tuple[Any, Any]] = []
        self.publish_existing_media_calls: list[Any] = []

    def publish_media(
        self,
        context: PropertyContext,
        rendered_media: RenderedMediaArtifact,
    ) -> PublishedMediaArtifact:
        self.publish_media_calls.append((context, rendered_media))
        return self.published_media

    def publish_existing_media(
        self, context: PropertyContext
    ) -> PublishedMediaArtifact:
        self.publish_existing_media_calls.append(context)
        if context.existing_published_media is None:
            raise ValidationError(
                "existing media required",
                code="EXISTING_MEDIA_REQUIRED",
            )
        return context.existing_published_media


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _build_context(
    workspace_dir: Path,
    *,
    requires_external_publish: bool = True,
    publish_context: SocialPublishContext | None = None,
    pending_publish_platforms: tuple[str, ...] = ("tiktok",),
    existing_published_media: PublishedMediaArtifact | None = None,
) -> PropertyContext:
    site_id = "site-pub"
    storage_paths = resolve_site_storage_layout(workspace_dir, site_id)
    property_item = Property.from_api_payload(_PAYLOAD)
    delivery_plan = MediaDeliveryPlan(
        listing_lifecycle="for_sale",
        artifact_kind="reel_video",
        render_profile="for_sale_reel",
        social_post_type="reel",
        asset_strategy="curated_selection",
        banner_text="FOR SALE",
        price_display_text=None,
    )
    tenant = TenantContext(
        site_id=site_id,
        agency_id="agency-pub",
        wordpress_source_id="ingestion-pub",
    )
    publish_targets = (
        PlatformPublishTargetPlan(
            platform="tiktok",
            artifact_kind="reel_video",
            social_post_type="reel",
            description="desc",
        ),
    )
    return PropertyContext(
        workspace_dir=workspace_dir,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
        publish_context=publish_context,
        publish_targets=publish_targets,
        pending_publish_platforms=pending_publish_platforms,
        requires_asset_preparation=False,
        requires_render=True,
        requires_external_publish=requires_external_publish,
        content_fingerprint="content-fp",
        publish_target_fingerprint="publish-fp",
        existing_published_media=existing_published_media,
    )


def _build_published_media(workspace_dir: Path) -> PublishedMediaArtifact:
    media_path = workspace_dir / "reel.mp4"
    metadata_path = workspace_dir / "reel.json"
    media_path.write_bytes(b"video")
    metadata_path.write_bytes(b"{}")
    return PublishedMediaArtifact(
        artifact_kind="reel_video",
        media_path=media_path,
        metadata_path=metadata_path,
        revision_id="revision-pub",
    )


def _build_rendered(workspace_dir: Path) -> RenderedMediaArtifact:
    staging_dir = workspace_dir / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    media_path = staging_dir / "casa-publica-reel.mp4"
    media_path.write_bytes(b"vid")
    metadata_path = staging_dir / "casa-publica-reel.json"
    metadata_path.write_bytes(b"{}")
    return RenderedMediaArtifact(
        staging_dir=staging_dir,
        artifact_kind="reel_video",
        media_path=media_path,
        metadata_path=metadata_path,
        revision_id="revision-pub",
    )


def _build_publish_context(
    *, approval_required: bool = False
) -> SocialPublishContext:
    return SocialPublishContext(
        provider="gohighlevel",
        location_id="loc-1",
        access_token="token-1",
        platforms=("tiktok",),
        approval_required=approval_required,
    )


def _build_multi_platform_result(*, aggregate_status: str = "published") -> Any:
    successful = ("tiktok",) if aggregate_status in {"published", "partial"} else ()
    return SimpleNamespace(
        aggregate_status=aggregate_status,
        successful_platforms=successful,
        to_dict=lambda: {
            "aggregate_status": aggregate_status,
            "successful_platforms": list(successful),
            "desired_platforms": ["tiktok"],
        },
    )


# ---------------------------------------------------------------------------
# Tests — happy paths (publish_completed)
# ---------------------------------------------------------------------------


def test_execute_publish_completed_writes_outbox_with_status_completed(
    tmp_path: Path,
) -> None:
    publish_context = _build_publish_context()
    context = _build_context(tmp_path, publish_context=publish_context)
    published = _build_published_media(tmp_path)
    rendered = _build_rendered(tmp_path)
    fake_publisher = _FakePublisher(
        result=_build_multi_platform_result(aggregate_status="published")
    )
    local_publisher = _StubLocalPublisher(published_media=published)
    states = _StubReelStates()
    revisions = _StubMediaRevisions()
    outbox = _StubOutbox()
    uow = _build_uow(states=states, revisions=revisions, outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=fake_publisher,
    )
    result = use_case.execute(context, rendered, uow=uow)

    assert result is published
    assert local_publisher.publish_media_calls == [(context, rendered)]
    assert len(fake_publisher.calls) == 1
    assert states.workflow_calls and states.workflow_calls[0]["workflow_state"] == "published"
    assert states.publish_calls and states.publish_calls[0]["status"] == "published"
    assert states.publish_calls[0]["last_published_provider_external_id"] == "loc-1"
    assert states.publish_calls[0]["external_source_id"] == "site-pub"
    assert states.publish_calls[0]["ingestion_source_id"] == "ingestion-pub"
    assert len(revisions.save_calls) == 1
    assert revisions.save_calls[0].workflow_state == "published"
    assert len(outbox.events) == 1
    event = outbox.events[0]
    assert event["event_type"] == "publish_completed"
    assert event["status"] == "completed"
    payload = event["payload"]
    assert payload["workflow_state"] == "published"
    assert payload["aggregate_status"] == "published"
    assert payload["successful_platforms"] == ["tiktok"]


def test_execute_partial_aggregate_writes_publish_completed_with_status_completed(
    tmp_path: Path,
) -> None:
    publish_context = _build_publish_context()
    context = _build_context(
        tmp_path,
        publish_context=publish_context,
        pending_publish_platforms=("tiktok", "facebook"),
    )
    published = _build_published_media(tmp_path)
    rendered = _build_rendered(tmp_path)
    fake_publisher = _FakePublisher(
        result=_build_multi_platform_result(aggregate_status="partial")
    )
    local_publisher = _StubLocalPublisher(published_media=published)
    outbox = _StubOutbox()
    uow = _build_uow(outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=fake_publisher,
    )
    use_case.execute(context, rendered, uow=uow)

    assert len(outbox.events) == 1
    event = outbox.events[0]
    assert event["event_type"] == "publish_completed"
    assert event["status"] == "completed"
    assert event["payload"]["workflow_state"] == "partial"


# ---------------------------------------------------------------------------
# Tests — skipped paths
# ---------------------------------------------------------------------------


def test_execute_skipped_when_social_publisher_is_none(tmp_path: Path) -> None:
    publish_context = _build_publish_context()
    context = _build_context(tmp_path, publish_context=publish_context)
    published = _build_published_media(tmp_path)
    rendered = _build_rendered(tmp_path)
    local_publisher = _StubLocalPublisher(published_media=published)
    states = _StubReelStates()
    outbox = _StubOutbox()
    uow = _build_uow(states=states, outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=None,
    )
    use_case.execute(context, rendered, uow=uow)

    assert states.workflow_calls[0]["workflow_state"] == "skipped"
    assert states.publish_calls[0]["status"] == "skipped"
    assert len(outbox.events) == 1
    event = outbox.events[0]
    assert event["event_type"] == "publish_skipped"
    assert event["status"] == "pending"


def test_execute_skipped_when_requires_external_publish_is_false(
    tmp_path: Path,
) -> None:
    publish_context = _build_publish_context()
    context = _build_context(
        tmp_path,
        publish_context=publish_context,
        requires_external_publish=False,
    )
    published = _build_published_media(tmp_path)
    rendered = _build_rendered(tmp_path)
    fake_publisher = _FakePublisher(result=_build_multi_platform_result())
    local_publisher = _StubLocalPublisher(published_media=published)
    outbox = _StubOutbox()
    uow = _build_uow(outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=fake_publisher,
    )
    use_case.execute(context, rendered, uow=uow)

    # Provider was NOT called — gating short-circuited.
    assert fake_publisher.calls == []
    assert outbox.events[0]["event_type"] == "publish_skipped"
    assert outbox.events[0]["status"] == "pending"


def test_execute_skipped_when_publish_context_is_none(tmp_path: Path) -> None:
    context = _build_context(tmp_path, publish_context=None)
    published = _build_published_media(tmp_path)
    rendered = _build_rendered(tmp_path)
    fake_publisher = _FakePublisher(result=_build_multi_platform_result())
    local_publisher = _StubLocalPublisher(published_media=published)
    outbox = _StubOutbox()
    uow = _build_uow(outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=fake_publisher,
    )
    use_case.execute(context, rendered, uow=uow)

    assert fake_publisher.calls == []
    assert outbox.events[0]["event_type"] == "publish_skipped"
    assert outbox.events[0]["status"] == "pending"


def test_execute_skipped_when_provider_returns_none(tmp_path: Path) -> None:
    publish_context = _build_publish_context()
    context = _build_context(tmp_path, publish_context=publish_context)
    published = _build_published_media(tmp_path)
    rendered = _build_rendered(tmp_path)
    fake_publisher = _FakePublisher(result=None)
    local_publisher = _StubLocalPublisher(published_media=published)
    outbox = _StubOutbox()
    uow = _build_uow(outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=fake_publisher,
    )
    use_case.execute(context, rendered, uow=uow)

    assert len(fake_publisher.calls) == 1
    assert outbox.events[0]["event_type"] == "publish_skipped"
    assert outbox.events[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Tests — awaiting_review paths
# ---------------------------------------------------------------------------


def test_execute_awaiting_review_when_agency_approval_required(
    tmp_path: Path,
) -> None:
    publish_context = _build_publish_context(approval_required=True)
    context = _build_context(tmp_path, publish_context=publish_context)
    published = _build_published_media(tmp_path)
    rendered = _build_rendered(tmp_path)
    fake_publisher = _FakePublisher(result=_build_multi_platform_result())
    local_publisher = _StubLocalPublisher(published_media=published)
    states = _StubReelStates()
    outbox = _StubOutbox()
    uow = _build_uow(states=states, outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=fake_publisher,
    )
    use_case.execute(context, rendered, uow=uow)

    # Provider not called when review is required.
    assert fake_publisher.calls == []
    assert states.workflow_calls[0]["workflow_state"] == "awaiting_review"
    assert states.publish_calls[0]["status"] == "pending_review"
    assert states.publish_calls[0]["last_published_provider_external_id"] == "loc-1"
    event = outbox.events[0]
    assert event["event_type"] == "review_requested"
    assert event["status"] == "pending"
    assert event["payload"]["workflow_state"] == "awaiting_review"


def test_execute_awaiting_review_when_env_flag_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "modules.reels.application.use_cases.publish_reel.REVIEW_WORKFLOW_ENABLED",
        True,
    )
    publish_context = _build_publish_context(approval_required=False)
    context = _build_context(tmp_path, publish_context=publish_context)
    published = _build_published_media(tmp_path)
    rendered = _build_rendered(tmp_path)
    fake_publisher = _FakePublisher(result=_build_multi_platform_result())
    local_publisher = _StubLocalPublisher(published_media=published)
    states = _StubReelStates()
    outbox = _StubOutbox()
    uow = _build_uow(states=states, outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=fake_publisher,
    )
    use_case.execute(context, rendered, uow=uow)

    assert fake_publisher.calls == []
    assert states.workflow_calls[0]["workflow_state"] == "awaiting_review"
    assert outbox.events[0]["event_type"] == "review_requested"


# ---------------------------------------------------------------------------
# Tests — failed paths
# ---------------------------------------------------------------------------


def test_execute_failed_persists_failed_state_and_reraises(tmp_path: Path) -> None:
    publish_context = _build_publish_context()
    context = _build_context(tmp_path, publish_context=publish_context)
    published = _build_published_media(tmp_path)
    rendered = _build_rendered(tmp_path)
    error = SocialPublishingResultError(
        "boom",
        result=_build_multi_platform_result(aggregate_status="failed"),
    )
    fake_publisher = _FakePublisher(raises=error)
    local_publisher = _StubLocalPublisher(published_media=published)
    states = _StubReelStates()
    outbox = _StubOutbox()
    uow = _build_uow(states=states, outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=fake_publisher,
    )
    with pytest.raises(SocialPublishingResultError):
        use_case.execute(context, rendered, uow=uow)

    assert states.workflow_calls[0]["workflow_state"] == "failed"
    assert states.publish_calls[0]["status"] == "failed"
    event = outbox.events[0]
    assert event["event_type"] == "publish_failed"
    assert event["status"] == "pending"


def test_execute_transient_failed_persists_failed_state_and_reraises(
    tmp_path: Path,
) -> None:
    publish_context = _build_publish_context()
    context = _build_context(tmp_path, publish_context=publish_context)
    published = _build_published_media(tmp_path)
    rendered = _build_rendered(tmp_path)
    error = TransientSocialPublishingResultError("transient", result=None)
    fake_publisher = _FakePublisher(raises=error)
    local_publisher = _StubLocalPublisher(published_media=published)
    states = _StubReelStates()
    outbox = _StubOutbox()
    uow = _build_uow(states=states, outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=fake_publisher,
    )
    with pytest.raises(TransientSocialPublishingResultError):
        use_case.execute(context, rendered, uow=uow)

    assert states.workflow_calls[0]["workflow_state"] == "failed"
    assert outbox.events[0]["event_type"] == "publish_failed"


# ---------------------------------------------------------------------------
# Tests — execute_existing
# ---------------------------------------------------------------------------


def test_execute_existing_raises_when_no_existing_artifact(tmp_path: Path) -> None:
    context = _build_context(tmp_path, publish_context=None)
    # Local publisher delegates to PersistLocalArtifactsUseCase which
    # raises EXISTING_MEDIA_REQUIRED. Single source of truth (D7).
    local_publisher = _StubLocalPublisher(
        published_media=_build_published_media(tmp_path)
    )
    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=None,
    )
    with pytest.raises(ValidationError) as excinfo:
        use_case.execute_existing(context)
    assert excinfo.value.code == "EXISTING_MEDIA_REQUIRED"


def test_execute_existing_publishes_with_existing_artifact(tmp_path: Path) -> None:
    existing = _build_published_media(tmp_path)
    publish_context = _build_publish_context()
    context = _build_context(
        tmp_path,
        publish_context=publish_context,
        existing_published_media=existing,
    )
    fake_publisher = _FakePublisher(
        result=_build_multi_platform_result(aggregate_status="published")
    )
    local_publisher = _StubLocalPublisher(published_media=existing)
    outbox = _StubOutbox()
    uow = _build_uow(outbox=outbox)

    use_case = PublishReelUseCase(
        local_publisher=local_publisher,
        workspace_dir=tmp_path,
        social_publisher=fake_publisher,
    )
    result = use_case.execute_existing(context, uow=uow)

    assert result is existing
    assert local_publisher.publish_existing_media_calls == [context]
    assert len(fake_publisher.calls) == 1
    assert outbox.events[0]["event_type"] == "publish_completed"
    assert outbox.events[0]["status"] == "completed"
