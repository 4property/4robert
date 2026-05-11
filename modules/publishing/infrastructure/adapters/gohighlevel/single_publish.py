from __future__ import annotations

import logging
import time

from shared.errors import TransientSocialPublishingError
from shared.observability import format_console_block, format_detail_line
from modules.publishing.infrastructure.adapters.gohighlevel.client import GoHighLevelApiError
from modules.publishing.infrastructure.adapters.gohighlevel.models import (
    PublishMediaRequest,
    PublishMediaResult,
)
from modules.publishing.infrastructure.adapters.gohighlevel.platform_policy import (
    resolve_platform_social_post_type,
    validate_platform_publish_request,
)

logger = logging.getLogger(__name__)


class GoHighLevelSinglePublishMixin:
    retry_attempts: int
    retry_backoff_seconds: float

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
        social_post_type = resolve_platform_social_post_type(
            platform=request.platform,
            requested_social_post_type=request.social_post_type,
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
            social_post_type=social_post_type,
            target_url=request.target_url,
        )
        logger.info(
            format_console_block(
                "GoHighLevel Publish Completed",
                format_detail_line("Location ID", request.location_id),
                format_detail_line("Platform", request.platform),
                format_detail_line(
                    "Selected account",
                    f"{selected_account.name} [{selected_account.id}]",
                ),
                format_detail_line(
                    "Resolved user",
                    f"{selected_user.display_name} [{selected_user.id}]",
                ),
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


__all__ = ["GoHighLevelSinglePublishMixin"]
