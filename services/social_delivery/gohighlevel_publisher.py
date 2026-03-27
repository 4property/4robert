from __future__ import annotations

import json
import logging
import time

from core.logging import format_console_block, format_detail_line
from core.errors import (
    ResourceNotFoundError,
    SocialPublishingError,
    TransientSocialPublishingError,
    ValidationError,
)
from services.social_delivery.gohighlevel_client import GoHighLevelApiError
from services.social_delivery.gohighlevel_media_service import GoHighLevelMediaService
from services.social_delivery.gohighlevel_social_service import GoHighLevelSocialService
from services.social_delivery.models import (
    LocationUser,
    PublishVideoRequest,
    PublishVideoResult,
    SocialAccount,
)
from services.social_delivery.user_selection import (
    LocationUserFallbackSelector,
    select_first_available_location_user,
)

logger = logging.getLogger(__name__)


class GoHighLevelPublisher:
    def __init__(
        self,
        *,
        media_service: GoHighLevelMediaService,
        social_service: GoHighLevelSocialService,
        fallback_user_selector: LocationUserFallbackSelector | None = None,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.media_service = media_service
        self.social_service = social_service
        self.fallback_user_selector = fallback_user_selector or select_first_available_location_user
        self.retry_attempts = max(1, retry_attempts)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    def list_connected_accounts(
        self,
        *,
        location_id: str,
        access_token: str,
        platform: str,
    ) -> tuple[SocialAccount, ...]:
        normalized_platform = platform.strip().lower()
        return tuple(
            account
            for account in self.social_service.list_accounts(
                location_id=location_id,
                access_token=access_token,
            )
            if account.platform == normalized_platform and not account.is_expired
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

    def publish_video(self, request: PublishVideoRequest) -> PublishVideoResult:
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return self._publish_video_once(request)
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

    def _publish_video_once(self, request: PublishVideoRequest) -> PublishVideoResult:
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

        uploaded_media = self.media_service.upload_video(
            access_token=request.access_token,
            video_path=request.video_path,
        )
        created_post = self.social_service.create_reel_post(
            location_id=request.location_id,
            access_token=request.access_token,
            account_id=selected_account.id,
            user_id=selected_user.id,
            uploaded_media=uploaded_media,
            platform=request.platform,
            description=request.description,
            target_url=request.target_url,
        )
        self._validate_created_post(created_post)
        logger.info(
            format_console_block(
                "GoHighLevel Publish Completed",
                format_detail_line("Location ID", request.location_id),
                format_detail_line("Platform", request.platform),
                format_detail_line("Selected account", f"{selected_account.name} [{selected_account.id}]"),
                format_detail_line("Resolved user", f"{selected_user.display_name} [{selected_user.id}]"),
                format_detail_line("Created post ID", created_post.post_id),
                format_detail_line("Source site", request.source_site_id),
            )
        )
        return PublishVideoResult(
            selected_account=selected_account,
            selected_user=selected_user,
            uploaded_media=uploaded_media,
            created_post=created_post,
            description=request.description,
            target_url=request.target_url,
            source_site_id=request.source_site_id,
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

    def _should_retry(self, *, error: Exception, attempt: int) -> bool:
        if attempt >= self.retry_attempts:
            return False
        if isinstance(error, TransientSocialPublishingError):
            return True
        if isinstance(error, GoHighLevelApiError):
            return error.status_code >= 500
        return False

    @staticmethod
    def _resolve_account(
        *,
        eligible_accounts: tuple[SocialAccount, ...],
        requested_account_id: str | None,
        platform: str,
    ) -> SocialAccount:
        if not eligible_accounts:
            raise ResourceNotFoundError(
                f"No connected {platform} accounts were found for this GoHighLevel location."
            )

        if requested_account_id:
            for account in eligible_accounts:
                if account.id == requested_account_id:
                    return account
            raise ValidationError(
                f"Requested social account was not found for platform {platform}: {requested_account_id}"
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
            raise ResourceNotFoundError("No location users were found for this GoHighLevel location.")

        if requested_user_id:
            for user in location_users:
                if user.id == requested_user_id:
                    return user
            raise ValidationError(f"Requested GoHighLevel user was not found: {requested_user_id}")

        selected_user = self.fallback_user_selector(location_users)
        if len(location_users) > 1:
            logger.info(
                "Automatically selected a GoHighLevel user via %s: %s (%s available users).",
                _selector_name(self.fallback_user_selector),
                selected_user.id,
                len(location_users),
            )
        return selected_user


def _selector_name(selector: LocationUserFallbackSelector) -> str:
    return getattr(selector, "__name__", selector.__class__.__name__)


__all__ = ["GoHighLevelPublisher"]

