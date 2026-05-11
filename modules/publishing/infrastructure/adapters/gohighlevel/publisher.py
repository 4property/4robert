from __future__ import annotations

from modules.publishing.infrastructure.adapters.gohighlevel.multi_publish import (
    GoHighLevelMultiPublishMixin,
)
from modules.publishing.infrastructure.adapters.gohighlevel.normalization import (
    SUPPORTED_GOHIGHLEVEL_PLATFORMS,
    normalise_platform_name,
)
from modules.publishing.infrastructure.adapters.gohighlevel.post_creation import (
    GoHighLevelPostCreationMixin,
)
from modules.publishing.infrastructure.adapters.gohighlevel.retrying import (
    GoHighLevelRetryMixin,
)
from modules.publishing.infrastructure.adapters.gohighlevel.selection import (
    GoHighLevelSelectionMixin,
)
from modules.publishing.infrastructure.adapters.gohighlevel.single_publish import (
    GoHighLevelSinglePublishMixin,
)
from modules.publishing.infrastructure.adapters.gohighlevel.media_service import (
    GoHighLevelMediaService,
)
from modules.publishing.infrastructure.adapters.gohighlevel.social_service import (
    GoHighLevelSocialService,
)
from modules.publishing.infrastructure.adapters.gohighlevel.models import (
    LocationUser,
    SocialAccount,
)
from modules.publishing.infrastructure.adapters.gohighlevel.user_selection import (
    LocationUserFallbackSelector,
    select_first_available_location_user,
)


class GoHighLevelPublisher(
    GoHighLevelSinglePublishMixin,
    GoHighLevelMultiPublishMixin,
    GoHighLevelPostCreationMixin,
    GoHighLevelSelectionMixin,
    GoHighLevelRetryMixin,
):
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
        self.fallback_user_selector = (
            fallback_user_selector or select_first_available_location_user
        )
        self.retry_attempts = max(1, retry_attempts)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.post_status_poll_attempts = max(1, post_status_poll_attempts)
        self.post_status_poll_interval_seconds = max(
            0.0,
            post_status_poll_interval_seconds,
        )

    def list_connected_accounts(
        self,
        *,
        location_id: str,
        access_token: str,
        platform: str,
    ) -> tuple[SocialAccount, ...]:
        normalized_platform = normalise_platform_name(platform)
        return tuple(
            account
            for account in self._list_active_accounts(
                location_id=location_id,
                access_token=access_token,
            )
            if normalise_platform_name(account.platform) == normalized_platform
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


__all__ = ["GoHighLevelPublisher", "SUPPORTED_GOHIGHLEVEL_PLATFORMS"]
