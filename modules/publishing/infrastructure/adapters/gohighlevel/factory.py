"""Default GoHighLevel property publisher factory.

Originally moved from ``application/bootstrap/runtime.py`` during
sub-feature 18b; sub-feature 18c migrated the underlying adapter classes
out of ``services/publishing/social_delivery/`` into this package so the
factory now imports everything locally.
"""

from __future__ import annotations

from settings import (
    GO_HIGH_LEVEL_API_VERSION,
    GO_HIGH_LEVEL_BASE_URL,
    OUTBOUND_HTTP_TIMEOUT_SECONDS,
    SOCIAL_PUBLISHING_POST_STATUS_POLL_ATTEMPTS,
    SOCIAL_PUBLISHING_POST_STATUS_POLL_INTERVAL_SECONDS,
    SOCIAL_PUBLISHING_RETRY_ATTEMPTS,
    SOCIAL_PUBLISHING_RETRY_BACKOFF_SECONDS,
)
from modules.publishing.infrastructure.adapters.gohighlevel.client import GoHighLevelClient
from modules.publishing.infrastructure.adapters.gohighlevel.media_service import (
    GoHighLevelMediaService,
)
from modules.publishing.infrastructure.adapters.gohighlevel.property_publisher import (
    GoHighLevelPropertyPublisher,
)
from modules.publishing.infrastructure.adapters.gohighlevel.publisher import GoHighLevelPublisher
from modules.publishing.infrastructure.adapters.gohighlevel.social_service import (
    GoHighLevelSocialService,
)
from modules.publishing.infrastructure.adapters.gohighlevel.user_selection import (
    select_first_available_location_user,
)


def build_default_social_property_publisher() -> GoHighLevelPropertyPublisher:
    client = GoHighLevelClient(
        base_url=GO_HIGH_LEVEL_BASE_URL,
        api_version=GO_HIGH_LEVEL_API_VERSION,
        timeout_seconds=OUTBOUND_HTTP_TIMEOUT_SECONDS,
    )
    publisher = GoHighLevelPublisher(
        media_service=GoHighLevelMediaService(client=client),
        social_service=GoHighLevelSocialService(client=client),
        fallback_user_selector=select_first_available_location_user,
        retry_attempts=SOCIAL_PUBLISHING_RETRY_ATTEMPTS,
        retry_backoff_seconds=SOCIAL_PUBLISHING_RETRY_BACKOFF_SECONDS,
        post_status_poll_attempts=SOCIAL_PUBLISHING_POST_STATUS_POLL_ATTEMPTS,
        post_status_poll_interval_seconds=SOCIAL_PUBLISHING_POST_STATUS_POLL_INTERVAL_SECONDS,
    )
    return GoHighLevelPropertyPublisher(
        publisher=publisher,
    )


__all__ = ["build_default_social_property_publisher"]
