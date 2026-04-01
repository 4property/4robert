from __future__ import annotations

import json
import logging
import time

from core.errors import (
    ResourceNotFoundError,
    SocialPublishingError,
    SocialPublishingResultError,
    TransientSocialPublishingError,
    TransientSocialPublishingResultError,
    ValidationError,
)
from core.logging import format_console_block, format_detail_line
from services.social_delivery.gohighlevel_client import GoHighLevelApiError
from services.social_delivery.gohighlevel_media_service import GoHighLevelMediaService
from services.social_delivery.gohighlevel_social_service import GoHighLevelSocialService
from services.social_delivery.models import (
    FAILED_PLATFORM_OUTCOMES,
    LocationUser,
    MultiPlatformPublishRequest,
    MultiPlatformPublishResult,
    PlatformPublishOutcome,
    PublishMediaRequest,
    PublishMediaResult,
    SocialAccount,
    UploadedMedia,
)
from services.social_delivery.platform_policy import (
    resolve_platform_social_post_type,
    validate_platform_publish_request,
)
from services.social_delivery.user_selection import (
    LocationUserFallbackSelector,
    select_first_available_location_user,
)

logger = logging.getLogger(__name__)

SUPPORTED_GOHIGHLEVEL_PLATFORMS = frozenset({"tiktok", "instagram", "linkedin", "youtube"})
_PLATFORM_ALIASES = {
    "linked-in": "linkedin",
    "linked_in": "linkedin",
    "you-tube": "youtube",
    "you_tube": "youtube",
}


class GoHighLevelPublisher:
    def __init__(
        self,
        *,
        media_service: GoHighLevelMediaService,
        social_service: GoHighLevelSocialService,
        fallback_user_selector: LocationUserFallbackSelector | None = None,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        post_status_poll_attempts: int = 3,
        post_status_poll_interval_seconds: float = 2.0,
    ) -> None:
        self.media_service = media_service
        self.social_service = social_service
        self.fallback_user_selector = fallback_user_selector or select_first_available_location_user
        self.retry_attempts = max(1, retry_attempts)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.post_status_poll_attempts = max(1, post_status_poll_attempts)
        self.post_status_poll_interval_seconds = max(0.0, post_status_poll_interval_seconds)

    def list_connected_accounts(
        self,
        *,
        location_id: str,
        access_token: str,
        platform: str,
    ) -> tuple[SocialAccount, ...]:
        normalized_platform = _normalise_platform_name(platform)
        return tuple(
            account
            for account in self._list_active_accounts(
                location_id=location_id,
                access_token=access_token,
            )
            if _normalise_platform_name(account.platform) == normalized_platform
        )

    def list_location_users(
        self,
        *,
        location_id: str,
        access_token: str,
    ) -> tuple[LocationUser, ...]:
        return self.social_service.list_location_users(
            location_id=location_id,
            access_token=access_token,
        )

    def publish_media(self, request: PublishMediaRequest) -> PublishMediaResult:
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return self._publish_media_once(request)
            except (TransientSocialPublishingError, GoHighLevelApiError) as error:
                last_error = error
                if not self._should_retry(error=error, attempt=attempt):
                    raise
                logger.warning(
                    format_console_block(
                        "GoHighLevel Publish Retry",
                        format_detail_line("Attempt", f"{attempt}/{self.retry_attempts}"),
                        format_detail_line("Location ID", request.location_id),
                        format_detail_line("Platform", request.platform),
                        format_detail_line("Reason", error),
                    )
                )
                time.sleep(self.retry_backoff_seconds * attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("GoHighLevel publish failed without an error.")

    def publish_video(self, request: PublishMediaRequest) -> PublishMediaResult:
        return self.publish_media(request)

    def publish_media_to_platforms(
        self,
        request: MultiPlatformPublishRequest,
    ) -> MultiPlatformPublishResult:
        desired_platforms = _normalise_requested_platforms(request.platforms)
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

        try:
            upload_file_name = self._resolve_batch_upload_file_name(request, desired_platforms)
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
            uploaded_media = self._run_with_retry(
                lambda: self.media_service.upload_media(
                    access_token=request.access_token,
                    media_path=request.media_path,
                    upload_file_name=upload_file_name,
                ),
                location_id=request.location_id,
                operation_name="Uploading GoHighLevel media",
                platform_label="all",
            )
        except Exception as error:
            self._raise_batch_failure(
                request=request,
                desired_platforms=desired_platforms,
                outcomes=tuple(
                    PlatformPublishOutcome(
                        platform=platform,
                        outcome="failed",
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
        for platform in desired_platforms:
            effective_social_post_type = resolve_platform_social_post_type(
                platform=platform,
                requested_social_post_type=request.social_post_type,
            )
            platform_warnings = validate_platform_publish_request(
                platform=platform,
                description=request.descriptions_by_platform.get(platform, ""),
                social_post_type=effective_social_post_type,
                artifact_kind=request.artifact_kind,
                title=request.titles_by_platform.get(platform),
            )
            for warning in platform_warnings:
                logger.warning(
                    format_console_block(
                        "Platform Publish Policy Warning",
                        format_detail_line("Location ID", request.location_id),
                        format_detail_line("Platform", platform),
                        format_detail_line("Warning", warning),
                    )
                )
            if platform not in SUPPORTED_GOHIGHLEVEL_PLATFORMS:
                outcomes.append(
                    PlatformPublishOutcome(
                        platform=platform,
                        outcome="skipped_unsupported_platform",
                        warnings=platform_warnings,
                        user_id=selected_user.id,
                        user_display_name=selected_user.display_name,
                        message=f"Platform is not supported in the current publisher: {platform}",
                    )
                )
                logger.warning(
                    "Skipping GoHighLevel publish for unsupported platform %s at location %s.",
                    platform,
                    request.location_id,
                )
                continue

            eligible_accounts = accounts_by_platform.get(platform, ())
            if not eligible_accounts:
                outcomes.append(
                    PlatformPublishOutcome(
                        platform=platform,
                        outcome="skipped_missing_account",
                        warnings=platform_warnings,
                        user_id=selected_user.id,
                        user_display_name=selected_user.display_name,
                        message=f"No connected {platform} account was found for this GoHighLevel location.",
                    )
                )
                logger.warning(
                    "Skipping GoHighLevel publish for platform %s at location %s because no active account was found.",
                    platform,
                    request.location_id,
                )
                continue

            selected_account = self._resolve_account(
                eligible_accounts=eligible_accounts,
                requested_account_id=None,
                platform=platform,
            )
            try:
                created_post = self._publish_platform_with_retry(
                    location_id=request.location_id,
                    access_token=request.access_token,
                    selected_account=selected_account,
                    selected_user=selected_user,
                    uploaded_media=uploaded_media,
                    platform=platform,
                    description=request.descriptions_by_platform.get(platform, ""),
                    title=request.titles_by_platform.get(platform),
                    social_post_type=effective_social_post_type,
                    target_url=request.target_url,
                )
                outcomes.append(
                    PlatformPublishOutcome(
                        platform=platform,
                        outcome=(created_post.status or "published").strip().lower() or "published",
                        warnings=platform_warnings,
                        account_id=selected_account.id,
                        account_name=selected_account.name,
                        user_id=selected_user.id,
                        user_display_name=selected_user.display_name,
                        post_id=created_post.post_id,
                        post_status=created_post.status,
                        message=created_post.message,
                        trace_id=_extract_trace_id(created_post.raw_response),
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
                        format_detail_line("Trace ID", error_trace_id or "<none>"),
                        format_detail_line("Response body", error_response_body or "<none>"),
                        format_detail_line("Reason", error),
                    )
                )

        result = MultiPlatformPublishResult(
            desired_platforms=desired_platforms,
            platform_results=tuple(outcomes),
            selected_user=selected_user,
            uploaded_media=uploaded_media,
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
                uploaded_media=uploaded_media,
                error=None,
            )

        logger.info(
            format_console_block(
                "GoHighLevel Multi-Platform Publish Completed",
                format_detail_line("Location ID", request.location_id),
                format_detail_line("Desired platforms", ", ".join(desired_platforms)),
                format_detail_line("Successful platforms", ", ".join(result.successful_platforms)),
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

    def _publish_media_once(self, request: PublishMediaRequest) -> PublishMediaResult:
        platform_warnings = validate_platform_publish_request(
            platform=request.platform,
            description=request.description,
            social_post_type=resolve_platform_social_post_type(
                platform=request.platform,
                requested_social_post_type=request.social_post_type,
            ),
            artifact_kind=request.artifact_kind,
            title=request.title,
        )
        for warning in platform_warnings:
            logger.warning(
                format_console_block(
                    "Platform Publish Policy Warning",
                    format_detail_line("Location ID", request.location_id),
                    format_detail_line("Platform", request.platform),
                    format_detail_line("Warning", warning),
                )
            )
        eligible_accounts = self.list_connected_accounts(
            location_id=request.location_id,
            access_token=request.access_token,
            platform=request.platform,
        )
        selected_account = self._resolve_account(
            eligible_accounts=eligible_accounts,
            requested_account_id=request.account_id,
            platform=request.platform,
        )

        location_users = self.list_location_users(
            location_id=request.location_id,
            access_token=request.access_token,
        )
        selected_user = self._resolve_user(
            location_users=location_users,
            requested_user_id=request.user_id,
        )

        uploaded_media = self.media_service.upload_media(
            access_token=request.access_token,
            media_path=request.media_path,
            upload_file_name=self._resolve_single_upload_file_name(request),
        )
        created_post = self._create_post(
            location_id=request.location_id,
            access_token=request.access_token,
            account_id=selected_account.id,
            user_id=selected_user.id,
            uploaded_media=uploaded_media,
            platform=request.platform,
            description=request.description,
            title=request.title,
            social_post_type=resolve_platform_social_post_type(
                platform=request.platform,
                requested_social_post_type=request.social_post_type,
            ),
            target_url=request.target_url,
        )
        logger.info(
            format_console_block(
                "GoHighLevel Publish Completed",
                format_detail_line("Location ID", request.location_id),
                format_detail_line("Platform", request.platform),
                format_detail_line("Selected account", f"{selected_account.name} [{selected_account.id}]"),
                format_detail_line("Resolved user", f"{selected_user.display_name} [{selected_user.id}]"),
                format_detail_line("Created post ID", created_post.post_id),
                format_detail_line("Social post type", request.social_post_type),
                format_detail_line("Source site", request.source_site_id),
            )
        )
        return PublishMediaResult(
            selected_account=selected_account,
            selected_user=selected_user,
            uploaded_media=uploaded_media,
            created_post=created_post,
            description=request.description,
            target_url=request.target_url,
            source_site_id=request.source_site_id,
            social_post_type=request.social_post_type,
            artifact_kind=request.artifact_kind,
        )

    def _publish_platform_with_retry(
        self,
        *,
        location_id: str,
        access_token: str,
        selected_account: SocialAccount,
        selected_user: LocationUser,
        uploaded_media: UploadedMedia,
        platform: str,
        description: str,
        title: str | None,
        social_post_type: str,
        target_url: str | None,
    ):
        return self._run_with_retry(
            lambda: self._create_post(
                location_id=location_id,
                access_token=access_token,
                account_id=selected_account.id,
                user_id=selected_user.id,
                uploaded_media=uploaded_media,
                platform=platform,
                description=description,
                title=title,
                social_post_type=social_post_type,
                target_url=target_url,
            ),
            location_id=location_id,
            operation_name="Creating GoHighLevel social post",
            platform_label=platform,
        )

    def _create_post(
        self,
        *,
        location_id: str,
        access_token: str,
        account_id: str,
        user_id: str,
        uploaded_media: UploadedMedia,
        platform: str,
        description: str,
        title: str | None,
        social_post_type: str,
        target_url: str | None,
    ):
        logger.info(
            format_console_block(
                "GoHighLevel Create Post Request",
                format_detail_line("Location ID", location_id),
                format_detail_line("Platform", platform),
                format_detail_line("Social post type", social_post_type),
                format_detail_line(
                    "Requested upload title",
                    str(title or "").strip() or "<none>",
                ),
                format_detail_line(
                    "Post payload title field",
                    "Not sent",
                ),
                format_detail_line("Uploaded media name", uploaded_media.file_name),
            )
        )
        created_post = self.social_service.create_social_post(
            location_id=location_id,
            access_token=access_token,
            account_id=account_id,
            user_id=user_id,
            uploaded_media=uploaded_media,
            platform=platform,
            description=description,
            title=title,
            social_post_type=social_post_type,
            target_url=target_url,
        )
        self._validate_created_post(created_post)
        return self._verify_created_post(
            location_id=location_id,
            access_token=access_token,
            account_id=account_id,
            platform=platform,
            created_post=created_post,
        )

    @staticmethod
    def _validate_created_post(created_post) -> None:
        normalized_status = (created_post.status or "").strip().lower()
        if normalized_status in {"failed", "error", "rejected"}:
            raise SocialPublishingError(
                f"GoHighLevel returned a non-success post status: {created_post.status}"
            )
        if created_post.post_id or created_post.status:
            return

        response_preview = json.dumps(created_post.raw_response, ensure_ascii=True)[:600]
        raise SocialPublishingError(
            "GoHighLevel create post did not return a post_id or post_status. "
            f"message={created_post.message or '<none>'}; response={response_preview}"
        )

    def _verify_created_post(
        self,
        *,
        location_id: str,
        access_token: str,
        account_id: str,
        platform: str,
        created_post,
    ):
        if not self._should_verify_created_post(platform=platform, created_post=created_post):
            return created_post

        last_seen_post = created_post
        for attempt in range(1, self.post_status_poll_attempts + 1):
            verified_post = self.social_service.get_social_post(
                location_id=location_id,
                access_token=access_token,
                post_id=created_post.post_id or "",
                platform=platform,
                account_id=account_id,
            )
            last_seen_post = verified_post
            normalized_status = (verified_post.status or "").strip().lower()
            response_preview = json.dumps(verified_post.raw_response, ensure_ascii=True)[:1000]
            logger.info(
                format_console_block(
                    "GoHighLevel Post Verification",
                    format_detail_line("Location ID", location_id),
                    format_detail_line("Platform", platform),
                    format_detail_line("Post ID", verified_post.post_id or created_post.post_id or "<none>"),
                    format_detail_line("Attempt", f"{attempt}/{self.post_status_poll_attempts}"),
                    format_detail_line("Verified status", normalized_status or "<none>"),
                    format_detail_line("Message", verified_post.message or "<none>"),
                    format_detail_line("Response preview", response_preview or "<none>"),
                )
            )
            if normalized_status in FAILED_PLATFORM_OUTCOMES:
                response_preview = json.dumps(verified_post.raw_response, ensure_ascii=True)[:1000]
                raise SocialPublishingError(
                    "GoHighLevel reported a failed downstream social publish. "
                    f"platform={platform}; post_id={verified_post.post_id or created_post.post_id or '<none>'}; "
                    f"status={verified_post.status or '<none>'}; "
                    f"message={verified_post.message or '<none>'}; response={response_preview}"
                )
            if normalized_status in {"published", "scheduled"}:
                return verified_post
            if normalized_status in {"queued", "processing"}:
                return verified_post
            if attempt < self.post_status_poll_attempts:
                time.sleep(self.post_status_poll_interval_seconds)

        logger.warning(
            format_console_block(
                "GoHighLevel Post Verification Pending",
                format_detail_line("Location ID", location_id),
                format_detail_line("Platform", platform),
                format_detail_line("Post ID", last_seen_post.post_id or created_post.post_id or "<none>"),
                format_detail_line("Verified status", (last_seen_post.status or "").strip() or "<none>"),
                format_detail_line("Message", last_seen_post.message or "<none>"),
            )
        )
        return last_seen_post.__class__(
            post_id=last_seen_post.post_id,
            status="verification_pending",
            message=last_seen_post.message,
            raw_response=last_seen_post.raw_response,
        )

    @staticmethod
    def _should_verify_created_post(*, platform: str, created_post) -> bool:
        normalized_platform = _normalise_platform_name(platform)
        if normalized_platform != "youtube":
            return False
        return bool(str(created_post.post_id or "").strip())

    def _run_with_retry(
        self,
        operation,
        *,
        location_id: str,
        operation_name: str,
        platform_label: str,
    ):
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return operation()
            except (TransientSocialPublishingError, GoHighLevelApiError) as error:
                last_error = error
                if not self._should_retry(error=error, attempt=attempt):
                    raise
                logger.warning(
                    format_console_block(
                        "GoHighLevel Publish Retry",
                        format_detail_line("Attempt", f"{attempt}/{self.retry_attempts}"),
                        format_detail_line("Location ID", location_id),
                        format_detail_line("Platform", platform_label),
                        format_detail_line("Operation", operation_name),
                        format_detail_line("Reason", error),
                    )
                )
                time.sleep(self.retry_backoff_seconds * attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"{operation_name} failed without an error.")

    def _should_retry(self, *, error: Exception, attempt: int) -> bool:
        if attempt >= self.retry_attempts:
            return False
        if isinstance(error, TransientSocialPublishingError):
            return True
        if isinstance(error, GoHighLevelApiError):
            return error.status_code >= 500
        return False

    def _is_retryable_error(self, error: Exception) -> bool:
        if isinstance(error, TransientSocialPublishingError):
            return True
        if isinstance(error, GoHighLevelApiError):
            return error.status_code >= 500
        return False

    def _list_active_accounts(
        self,
        *,
        location_id: str,
        access_token: str,
    ) -> tuple[SocialAccount, ...]:
        return tuple(
            account
            for account in self.social_service.list_accounts(
                location_id=location_id,
                access_token=access_token,
            )
            if not account.is_expired
        )

    def _group_accounts_by_platform(
        self,
        accounts: tuple[SocialAccount, ...],
    ) -> dict[str, tuple[SocialAccount, ...]]:
        grouped_accounts: dict[str, list[SocialAccount]] = {}
        for account in accounts:
            normalized_platform = _normalise_platform_name(account.platform)
            if not normalized_platform:
                continue
            grouped_accounts.setdefault(normalized_platform, []).append(account)
        return {
            platform: tuple(platform_accounts)
            for platform, platform_accounts in grouped_accounts.items()
        }

    def _raise_batch_failure(
        self,
        *,
        request: MultiPlatformPublishRequest,
        desired_platforms: tuple[str, ...],
        outcomes: tuple[PlatformPublishOutcome, ...],
        selected_user: LocationUser | None,
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
        message = _build_failed_batch_message(result)
        if error is not None and self._is_retryable_error(error):
            raise TransientSocialPublishingResultError(message, result=result) from error
        if result.should_retry:
            raise TransientSocialPublishingResultError(message, result=result)
        raise SocialPublishingResultError(message, result=result)

    @staticmethod
    def _resolve_account(
        *,
        eligible_accounts: tuple[SocialAccount, ...],
        requested_account_id: str | None,
        platform: str,
    ) -> SocialAccount:
        if not eligible_accounts:
            raise ResourceNotFoundError(
                f"No connected {platform} accounts were found for this GoHighLevel location.",
                context={"platform": platform},
                hint="Connect the social account in GoHighLevel before retrying the publish.",
            )

        if requested_account_id:
            for account in eligible_accounts:
                if account.id == requested_account_id:
                    return account
            raise ValidationError(
                f"Requested social account was not found for platform {platform}: {requested_account_id}",
                context={"platform": platform, "requested_account_id": requested_account_id},
                hint="Refresh the configured account mapping and confirm the account still exists in GoHighLevel.",
            )

        selected_account = sorted(
            eligible_accounts,
            key=lambda account: (account.name.lower(), account.id),
        )[0]
        if len(eligible_accounts) > 1:
            logger.info(
                "Automatically selected the first available %s account: %s (%s available accounts).",
                platform,
                selected_account.id,
                len(eligible_accounts),
            )
        return selected_account

    def _resolve_user(
        self,
        *,
        location_users: tuple[LocationUser, ...],
        requested_user_id: str | None,
    ) -> LocationUser:
        if not location_users:
            raise ResourceNotFoundError(
                "No location users were found for this GoHighLevel location.",
                hint="Add or sync at least one active user in the target GoHighLevel location before publishing.",
            )

        if requested_user_id:
            for user in location_users:
                if user.id == requested_user_id:
                    return user
            raise ValidationError(
                f"Requested GoHighLevel user was not found: {requested_user_id}",
                context={"requested_user_id": requested_user_id},
                hint="Refresh the configured user mapping and confirm the user still exists in GoHighLevel.",
            )

        selected_user = self.fallback_user_selector(location_users)
        if len(location_users) > 1:
            selector_name = _selector_name(self.fallback_user_selector)
            if selector_name == "select_first_available_location_user":
                logger.info(
                    "Automatically selected the first available GoHighLevel user: %s (%s available users).",
                    selected_user.id,
                    len(location_users),
                )
            else:
                logger.info(
                    "Automatically selected a GoHighLevel user via %s: %s (%s available users).",
                    selector_name,
                    selected_user.id,
                    len(location_users),
                )
        return selected_user

    @staticmethod
    def _resolve_batch_upload_file_name(
        request: MultiPlatformPublishRequest,
        desired_platforms: tuple[str, ...],
    ) -> str | None:
        if str(request.upload_file_name or "").strip():
            return request.upload_file_name
        if "youtube" not in desired_platforms:
            return None
        youtube_title = str(request.titles_by_platform.get("youtube") or "").strip()
        return youtube_title or None

    @staticmethod
    def _resolve_single_upload_file_name(request: PublishMediaRequest) -> str | None:
        if str(request.upload_file_name or "").strip():
            return request.upload_file_name
        if _normalise_platform_name(request.platform) != "youtube":
            return None
        normalized_title = str(request.title or "").strip()
        return normalized_title or None


def _selector_name(selector: LocationUserFallbackSelector) -> str:
    return getattr(selector, "__name__", selector.__class__.__name__)


def _normalise_platform_name(platform: str) -> str:
    normalized_platform = platform.strip().lower()
    return _PLATFORM_ALIASES.get(normalized_platform, normalized_platform)


def _normalise_requested_platforms(platforms: tuple[str, ...]) -> tuple[str, ...]:
    normalized_platforms: list[str] = []
    seen: set[str] = set()
    for platform in platforms:
        normalized_platform = _normalise_platform_name(platform)
        if not normalized_platform or normalized_platform in seen:
            continue
        seen.add(normalized_platform)
        normalized_platforms.append(normalized_platform)
    return tuple(normalized_platforms)


def _extract_trace_id(raw_response: dict[str, object]) -> str | None:
    trace_id = raw_response.get("traceId")
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id.strip()
    return None


def _build_failed_batch_message(result: MultiPlatformPublishResult) -> str:
    summarized_outcomes = ", ".join(
        f"{outcome.platform}={outcome.outcome}"
        + (f" ({outcome.error})" if outcome.error else "")
        for outcome in result.platform_results
    )
    return (
        "GoHighLevel multi-platform publish did not succeed on any platform. "
        f"Outcomes: {summarized_outcomes or '<none>'}"
    )


__all__ = ["GoHighLevelPublisher", "SUPPORTED_GOHIGHLEVEL_PLATFORMS"]
