"""Unit tests for `MultiPlatformPublishResult.aggregate_status`.

The aggregate status must treat ``skipped_missing_account`` outcomes as
non-effective (the agency simply doesn't have that platform connected).
Real failures still drag the publish into ``partial``/``failed``.
"""

from __future__ import annotations

from modules.publishing.infrastructure.adapters.gohighlevel.models import (
    MultiPlatformPublishResult,
    PlatformPublishOutcome,
)


def _outcome(platform: str, outcome: str) -> PlatformPublishOutcome:
    return PlatformPublishOutcome(platform=platform, outcome=outcome)


def _build_result(
    *,
    desired_platforms: tuple[str, ...],
    platform_results: tuple[PlatformPublishOutcome, ...],
) -> MultiPlatformPublishResult:
    return MultiPlatformPublishResult(
        desired_platforms=desired_platforms,
        platform_results=platform_results,
        selected_user=None,
        uploaded_media=None,
        source_site_id=None,
        target_url=None,
        social_post_type="reel",
        artifact_kind="reel_video",
    )


def test_aggregate_status_published_when_all_four_desired_succeed() -> None:
    desired = ("tiktok", "instagram", "linkedin", "youtube")
    result = _build_result(
        desired_platforms=desired,
        platform_results=tuple(_outcome(p, "published") for p in desired),
    )
    assert result.aggregate_status == "published"


def test_aggregate_status_published_when_skipped_missing_account_extras() -> None:
    # The bug case: 4 platforms publish OK, 2 are skipped because the agency
    # never connected facebook/google_business_profile. Should still be
    # ``published`` because the effective outcomes are all successes.
    desired = (
        "tiktok",
        "instagram",
        "linkedin",
        "youtube",
        "facebook",
        "google_business_profile",
    )
    platform_results = (
        _outcome("tiktok", "published"),
        _outcome("instagram", "published"),
        _outcome("linkedin", "published"),
        _outcome("youtube", "published"),
        _outcome("facebook", "skipped_missing_account"),
        _outcome("google_business_profile", "skipped_missing_account"),
    )
    result = _build_result(
        desired_platforms=desired, platform_results=platform_results
    )
    assert result.aggregate_status == "published"


def test_aggregate_status_partial_when_real_failure_mixed_with_skipped() -> None:
    desired = (
        "tiktok",
        "instagram",
        "linkedin",
        "youtube",
        "facebook",
        "google_business_profile",
    )
    platform_results = (
        _outcome("tiktok", "published"),
        _outcome("instagram", "published"),
        _outcome("linkedin", "published"),
        _outcome("youtube", "failed"),
        _outcome("facebook", "skipped_missing_account"),
        _outcome("google_business_profile", "skipped_missing_account"),
    )
    result = _build_result(
        desired_platforms=desired, platform_results=platform_results
    )
    assert result.aggregate_status == "partial"


def test_aggregate_status_failed_when_all_effective_failed_with_skipped_extras() -> None:
    desired = (
        "tiktok",
        "instagram",
        "linkedin",
        "youtube",
        "facebook",
        "google_business_profile",
    )
    platform_results = (
        _outcome("tiktok", "failed"),
        _outcome("instagram", "failed"),
        _outcome("linkedin", "skipped_missing_account"),
        _outcome("youtube", "skipped_missing_account"),
        _outcome("facebook", "skipped_missing_account"),
        _outcome("google_business_profile", "skipped_missing_account"),
    )
    result = _build_result(
        desired_platforms=desired, platform_results=platform_results
    )
    assert result.aggregate_status == "failed"


def test_aggregate_status_failed_when_all_desired_are_skipped_missing_account() -> None:
    # Agency mis-configured: every desired platform is skipped. The product
    # decision is to keep this as ``failed`` so the operator sees the issue.
    desired = (
        "tiktok",
        "instagram",
        "linkedin",
        "youtube",
        "facebook",
        "google_business_profile",
    )
    platform_results = tuple(
        _outcome(p, "skipped_missing_account") for p in desired
    )
    result = _build_result(
        desired_platforms=desired, platform_results=platform_results
    )
    assert result.aggregate_status == "failed"


def test_aggregate_status_skipped_when_no_desired_platforms() -> None:
    result = _build_result(desired_platforms=(), platform_results=())
    assert result.aggregate_status == "skipped"


def test_aggregate_status_published_when_all_six_desired_succeed() -> None:
    desired = (
        "tiktok",
        "instagram",
        "linkedin",
        "youtube",
        "facebook",
        "google_business_profile",
    )
    result = _build_result(
        desired_platforms=desired,
        platform_results=tuple(_outcome(p, "published") for p in desired),
    )
    assert result.aggregate_status == "published"
