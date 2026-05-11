from __future__ import annotations

import logging

from modules.publishing.infrastructure.adapters.gohighlevel.normalization import (
    SUPPORTED_GOHIGHLEVEL_PLATFORMS,
    build_failed_batch_message,
    extract_trace_id,
    normalise_publish_targets,
)
from shared.errors import (
    SocialPublishingResultError,
    TransientSocialPublishingResultError,
)
from shared.observability import format_console_block, format_detail_line
from modules.publishing.infrastructure.adapters.gohighlevel.client import GoHighLevelApiError
from modules.publishing.infrastructure.adapters.gohighlevel.models import (
    MultiPlatformPublishRequest,
    MultiPlatformPublishResult,
    PlatformPublishOutcome,
    UploadedMedia,
)
from modules.publishing.infrastructure.adapters.gohighlevel.platform_policy import (
    resolve_platform_social_post_type,
    validate_platform_publish_request,
)

logger = logging.getLogger(__name__)


class GoHighLevelMultiPublishMixin:
    def publish_media_to_platforms(
        self,
        request: MultiPlatformPublishRequest,
    ) -> MultiPlatformPublishResult:
        normalized_targets = normalise_publish_targets(request.publish_targets)
        desired_platforms = tuple(target.platform for target in normalized_targets)
        if not desired_platforms:
            return MultiPlatformPublishResult(
                desired_platforms=(),
                platform_results=(),
                selected_user=None,
                uploaded_media=None,
                source_site_id=request.source_site_id,
                target_url=request.target_url,
                social_post_type=request.social_post_type,
                artifact_kind=request.artifact_kind,
            )

        logger.info(
            format_console_block(
                "GoHighLevel Multi-Platform Publish Started",
                format_detail_line("Location ID", request.location_id),
                format_detail_line("Desired platforms", ", ".join(desired_platforms)),
                format_detail_line(
                    "Artifact targets",
                    ", ".join(
                        f"{target.platform}:{target.artifact_kind}"
                        for target in normalized_targets
                    ),
                ),
                format_detail_line("Source site", request.source_site_id or "<none>"),
            )
        )

        try:
            all_accounts = self._run_with_retry(
                lambda: self._list_active_accounts(
                    location_id=request.location_id,
                    access_token=request.access_token,
                ),
                location_id=request.location_id,
                operation_name="Loading GoHighLevel accounts",
                platform_label="all",
            )
            location_users = self._run_with_retry(
                lambda: self.list_location_users(
                    location_id=request.location_id,
                    access_token=request.access_token,
                ),
                location_id=request.location_id,
                operation_name="Loading GoHighLevel users",
                platform_label="all",
            )
            selected_user = self._resolve_user(
                location_users=location_users,
                requested_user_id=request.user_id,
            )
        except Exception as error:
            self._raise_batch_failure(
                request=request,
                desired_platforms=desired_platforms,
                outcomes=tuple(
                    PlatformPublishOutcome(
                        platform=platform,
                        outcome="failed",
                        artifact_kind=request.artifact_kind,
                        social_post_type=request.social_post_type,
                        retryable=self._is_retryable_error(error),
                        error=str(error),
                    )
                    for platform in desired_platforms
                ),
                selected_user=None,
                uploaded_media=None,
                error=error,
            )

        accounts_by_platform = self._group_accounts_by_platform(all_accounts)
        outcomes: list[PlatformPublishOutcome] = []
        uploaded_media_by_group: dict[tuple[str, str], UploadedMedia] = {}
        first_uploaded_media: UploadedMedia | None = None
        for target in normalized_targets:
            platform = target.platform
            effective_social_post_type = resolve_platform_social_post_type(
                platform=platform,
                requested_social_post_type=target.social_post_type,
            )
            platform_warnings = validate_platform_publish_request(
                platform=platform,
                description=target.description,
                social_post_type=effective_social_post_type,
                artifact_kind=target.artifact_kind,
                title=target.title,
            )
            for warning in platform_warnings:
                logger.warning(
                    format_console_block(
                        "Platform Publish Policy Warning",
                        format_detail_line("Location ID", request.location_id),
                        format_detail_line("Platform", platform),
                        format_detail_line("Artifact kind", target.artifact_kind),
                        format_detail_line("Warning", warning),
                    )
                )
            if platform not in SUPPORTED_GOHIGHLEVEL_PLATFORMS:
                outcomes.append(
                    PlatformPublishOutcome(
                        platform=platform,
                        outcome="skipped_unsupported_platform",
                        artifact_kind=target.artifact_kind,
                        social_post_type=effective_social_post_type,
                        warnings=platform_warnings,
                        user_id=selected_user.id,
                        user_display_name=selected_user.display_name,
                        message=(
                            "Platform is not supported in the current publisher: "
                            f"{platform}"
                        ),
                    )
                )
                logger.warning(
                    "Skipping GoHighLevel publish for unsupported platform %s at "
                    "location %s.",
                    platform,
                    request.location_id,
                )
                continue

            eligible_accounts = accounts_by_platform.get(platform, ())
            if not eligible_accounts:
                available_platforms = tuple(sorted(accounts_by_platform))
                outcomes.append(
                    PlatformPublishOutcome(
                        platform=platform,
                        outcome="skipped_missing_account",
                        artifact_kind=target.artifact_kind,
                        social_post_type=effective_social_post_type,
                        warnings=platform_warnings,
                        user_id=selected_user.id,
                        user_display_name=selected_user.display_name,
                        message=(
                            f"No connected {platform} account was found for this "
                            "GoHighLevel location."
                            if not available_platforms
                            else (
                                f"No connected {platform} account was found for this "
                                "GoHighLevel location. Available connected "
                                f"platforms: {', '.join(available_platforms)}."
                            )
                        ),
                    )
                )
                logger.warning(
                    "Skipping GoHighLevel publish for platform %s at location %s "
                    "because no active account was found. Available connected "
                    "platforms: %s.",
                    platform,
                    request.location_id,
                    ", ".join(available_platforms) if available_platforms else "<none>",
                )
                continue

            selected_account = self._resolve_account(
                eligible_accounts=eligible_accounts,
                requested_account_id=None,
                platform=platform,
            )
            upload_group_key = (str(target.media_path.resolve()), target.artifact_kind)
            uploaded_media = uploaded_media_by_group.get(upload_group_key)
            if uploaded_media is None:
                upload_file_name = self._resolve_upload_file_name_for_targets((target,))
                uploaded_media = self._run_with_retry(
                    lambda: self.media_service.upload_media(
                        access_token=request.access_token,
                        media_path=target.media_path,
                        upload_file_name=upload_file_name,
                    ),
                    location_id=request.location_id,
                    operation_name="Uploading GoHighLevel media",
                    platform_label=platform,
                )
                uploaded_media_by_group[upload_group_key] = uploaded_media
                if first_uploaded_media is None:
                    first_uploaded_media = uploaded_media
                logger.info(
                    format_console_block(
                        "GoHighLevel Artifact Upload Completed",
                        format_detail_line("Location ID", request.location_id),
                        format_detail_line("Platform", platform),
                        format_detail_line("Artifact kind", target.artifact_kind),
                        format_detail_line("Media path", target.media_path),
                        format_detail_line(
                            "Upload file name",
                            upload_file_name or "<none>",
                        ),
                        format_detail_line("Uploaded media ID", uploaded_media.file_id),
                    )
                )
            else:
                logger.info(
                    format_console_block(
                        "GoHighLevel Artifact Upload Reused",
                        format_detail_line("Location ID", request.location_id),
                        format_detail_line("Platform", platform),
                        format_detail_line("Artifact kind", target.artifact_kind),
                        format_detail_line("Media path", target.media_path),
                        format_detail_line("Uploaded media ID", uploaded_media.file_id),
                    )
                )
            try:
                created_post = self._publish_platform_with_retry(
                    location_id=request.location_id,
                    access_token=request.access_token,
                    selected_account=selected_account,
                    selected_user=selected_user,
                    uploaded_media=uploaded_media,
                    platform=platform,
                    description=target.description,
                    title=target.title,
                    social_post_type=effective_social_post_type,
                    target_url=target.target_url,
                )
                outcomes.append(
                    PlatformPublishOutcome(
                        platform=platform,
                        outcome=(
                            (created_post.status or "published").strip().lower()
                            or "published"
                        ),
                        artifact_kind=target.artifact_kind,
                        social_post_type=effective_social_post_type,
                        warnings=platform_warnings,
                        account_id=selected_account.id,
                        account_name=selected_account.name,
                        user_id=selected_user.id,
                        user_display_name=selected_user.display_name,
                        post_id=created_post.post_id,
                        post_status=created_post.status,
                        message=created_post.message,
                        trace_id=extract_trace_id(created_post.raw_response),
                    )
                )
                logger.info(
                    format_console_block(
                        "GoHighLevel Platform Publish Completed",
                        format_detail_line("Location ID", request.location_id),
                        format_detail_line("Platform", platform),
                        format_detail_line("Artifact kind", target.artifact_kind),
                        format_detail_line(
                            "Social post type",
                            effective_social_post_type,
                        ),
                        format_detail_line("Account ID", selected_account.id),
                        format_detail_line("User ID", selected_user.id),
                        format_detail_line("Post ID", created_post.post_id or "<none>"),
                        format_detail_line(
                            "Post status",
                            created_post.status or "<none>",
                        ),
                    )
                )
            except Exception as error:
                error_trace_id = None
                error_response_body = None
                if isinstance(error, GoHighLevelApiError):
                    error_trace_id = error.external_trace_id
                    error_response_body = error.response_body
                outcomes.append(
                    PlatformPublishOutcome(
                        platform=platform,
                        outcome="failed",
                        artifact_kind=target.artifact_kind,
                        social_post_type=effective_social_post_type,
                        retryable=self._is_retryable_error(error),
                        warnings=platform_warnings,
                        account_id=selected_account.id,
                        account_name=selected_account.name,
                        user_id=selected_user.id,
                        user_display_name=selected_user.display_name,
                        error=str(error),
                    )
                )
                logger.warning(
                    format_console_block(
                        "GoHighLevel Platform Publish Failed",
                        format_detail_line("Location ID", request.location_id),
                        format_detail_line("Platform", platform),
                        format_detail_line("Artifact kind", target.artifact_kind),
                        format_detail_line(
                            "Social post type",
                            effective_social_post_type,
                        ),
                        format_detail_line("Account ID", selected_account.id),
                        format_detail_line("User ID", selected_user.id),
                        format_detail_line("Trace ID", error_trace_id or "<none>"),
                        format_detail_line(
                            "Response body",
                            error_response_body or "<none>",
                        ),
                        format_detail_line("Reason", error),
                    )
                )

        result = MultiPlatformPublishResult(
            desired_platforms=desired_platforms,
            platform_results=tuple(outcomes),
            selected_user=selected_user,
            uploaded_media=first_uploaded_media,
            source_site_id=request.source_site_id,
            target_url=request.target_url,
            social_post_type=request.social_post_type,
            artifact_kind=request.artifact_kind,
        )
        if not result.has_any_success:
            self._raise_batch_failure(
                request=request,
                desired_platforms=desired_platforms,
                outcomes=result.platform_results,
                selected_user=selected_user,
                uploaded_media=first_uploaded_media,
                error=None,
            )

        logger.info(
            format_console_block(
                "GoHighLevel Multi-Platform Publish Completed",
                format_detail_line("Location ID", request.location_id),
                format_detail_line("Desired platforms", ", ".join(desired_platforms)),
                format_detail_line(
                    "Successful platforms",
                    ", ".join(result.successful_platforms),
                ),
                format_detail_line("Aggregate status", result.aggregate_status),
                format_detail_line("Source site", request.source_site_id),
            )
        )
        return result

    def publish_video_to_platforms(
        self,
        request: MultiPlatformPublishRequest,
    ) -> MultiPlatformPublishResult:
        return self.publish_media_to_platforms(request)

    def _raise_batch_failure(
        self,
        *,
        request: MultiPlatformPublishRequest,
        desired_platforms: tuple[str, ...],
        outcomes: tuple[PlatformPublishOutcome, ...],
        selected_user,
        uploaded_media: UploadedMedia | None,
        error: Exception | None,
    ) -> None:
        result = MultiPlatformPublishResult(
            desired_platforms=desired_platforms,
            platform_results=outcomes,
            selected_user=selected_user,
            uploaded_media=uploaded_media,
            source_site_id=request.source_site_id,
            target_url=request.target_url,
            social_post_type=request.social_post_type,
            artifact_kind=request.artifact_kind,
        )
        message = build_failed_batch_message(result)
        if error is not None and self._is_retryable_error(error):
            raise TransientSocialPublishingResultError(message, result=result) from error
        if result.should_retry:
            raise TransientSocialPublishingResultError(message, result=result)
        raise SocialPublishingResultError(message, result=result)


__all__ = ["GoHighLevelMultiPublishMixin"]
