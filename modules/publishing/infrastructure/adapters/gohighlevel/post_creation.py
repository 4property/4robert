from __future__ import annotations

import json
import logging
import time

from modules.publishing.infrastructure.adapters.gohighlevel.normalization import (
    normalise_platform_name,
)
from shared.errors import SocialPublishingError
from shared.observability import format_console_block, format_detail_line
from modules.publishing.infrastructure.adapters.gohighlevel.models import (
    FAILED_PLATFORM_OUTCOMES,
    LocationUser,
    SocialAccount,
    UploadedMedia,
)

logger = logging.getLogger(__name__)


class GoHighLevelPostCreationMixin:
    post_status_poll_attempts: int
    post_status_poll_interval_seconds: float

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
        scheduled_at: str | None = None,
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
                scheduled_at=scheduled_at,
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
        scheduled_at: str | None = None,
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
                format_detail_line("Post payload title field", "Not sent"),
                format_detail_line("Uploaded media name", uploaded_media.file_name),
                format_detail_line("Scheduled at", scheduled_at or "<immediate>"),
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
            scheduled_at=scheduled_at,
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
                "GoHighLevel returned a non-success post status: "
                f"{created_post.status}"
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
        if not self._should_verify_created_post(
            platform=platform,
            created_post=created_post,
        ):
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
            response_preview = json.dumps(
                verified_post.raw_response,
                ensure_ascii=True,
            )[:1000]
            logger.info(
                format_console_block(
                    "GoHighLevel Post Verification",
                    format_detail_line("Location ID", location_id),
                    format_detail_line("Platform", platform),
                    format_detail_line(
                        "Post ID",
                        verified_post.post_id or created_post.post_id or "<none>",
                    ),
                    format_detail_line(
                        "Attempt",
                        f"{attempt}/{self.post_status_poll_attempts}",
                    ),
                    format_detail_line(
                        "Verified status",
                        normalized_status or "<none>",
                    ),
                    format_detail_line("Message", verified_post.message or "<none>"),
                    format_detail_line(
                        "Response preview",
                        response_preview or "<none>",
                    ),
                )
            )
            if normalized_status in FAILED_PLATFORM_OUTCOMES:
                response_preview = json.dumps(
                    verified_post.raw_response,
                    ensure_ascii=True,
                )[:1000]
                raise SocialPublishingError(
                    "GoHighLevel reported a failed downstream social publish. "
                    f"platform={platform}; post_id="
                    f"{verified_post.post_id or created_post.post_id or '<none>'}; "
                    f"status={verified_post.status or '<none>'}; "
                    f"message={verified_post.message or '<none>'}; "
                    f"response={response_preview}"
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
                format_detail_line(
                    "Post ID",
                    last_seen_post.post_id or created_post.post_id or "<none>",
                ),
                format_detail_line(
                    "Verified status",
                    (last_seen_post.status or "").strip() or "<none>",
                ),
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
        normalized_platform = normalise_platform_name(platform)
        if normalized_platform != "youtube":
            return False
        return bool(str(created_post.post_id or "").strip())


__all__ = ["GoHighLevelPostCreationMixin"]
