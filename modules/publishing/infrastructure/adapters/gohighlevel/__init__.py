"""GoHighLevel publishing adapter."""

from modules.publishing.infrastructure.adapters.gohighlevel.client import (
    GoHighLevelApiError,
    GoHighLevelClient,
)
from modules.publishing.infrastructure.adapters.gohighlevel.factory import (
    build_default_social_property_publisher,
)
from modules.publishing.infrastructure.adapters.gohighlevel.interfaces import (
    SocialMediaPublisher,
)
from modules.publishing.infrastructure.adapters.gohighlevel.media_service import (
    GoHighLevelMediaService,
    MAX_GHL_GENERAL_UPLOAD_BYTES,
    MAX_GHL_VIDEO_UPLOAD_BYTES,
)
from modules.publishing.infrastructure.adapters.gohighlevel.models import (
    CreatedSocialPost,
    LocationUser,
    MultiPlatformPublishRequest,
    MultiPlatformPublishResult,
    PlatformPublishOutcome,
    PlatformPublishTarget,
    PublishMediaRequest,
    PublishMediaResult,
    PublishVideoRequest,
    PublishVideoResult,
    SUCCESSFUL_PLATFORM_OUTCOMES,
    SocialAccount,
    UploadedMedia,
)
from modules.publishing.infrastructure.adapters.gohighlevel.normalization import (
    SUPPORTED_GOHIGHLEVEL_PLATFORMS,
    build_failed_batch_message,
    extract_trace_id,
    normalise_platform_name,
    normalise_publish_targets,
    normalise_requested_platforms,
    selector_name,
)
from modules.publishing.infrastructure.adapters.gohighlevel.platform_policy import (
    PlatformPolicy,
    get_platform_policy,
    resolve_platform_artifact_kind,
    resolve_platform_social_post_type,
    validate_platform_publish_request,
)
from modules.publishing.infrastructure.adapters.gohighlevel.property_publisher import (
    GoHighLevelPropertyPublisher,
)
from modules.publishing.infrastructure.adapters.gohighlevel.publisher import (
    GoHighLevelPublisher,
)
from modules.publishing.infrastructure.adapters.gohighlevel.social_service import (
    GoHighLevelSocialService,
)
from modules.publishing.infrastructure.adapters.gohighlevel.user_selection import (
    LocationUserFallbackSelector,
    select_first_available_location_user,
    select_random_location_user,
)

__all__ = [
    "CreatedSocialPost",
    "GoHighLevelApiError",
    "GoHighLevelClient",
    "GoHighLevelMediaService",
    "GoHighLevelPropertyPublisher",
    "GoHighLevelPublisher",
    "GoHighLevelSocialService",
    "LocationUser",
    "LocationUserFallbackSelector",
    "MAX_GHL_GENERAL_UPLOAD_BYTES",
    "MAX_GHL_VIDEO_UPLOAD_BYTES",
    "MultiPlatformPublishRequest",
    "MultiPlatformPublishResult",
    "PlatformPolicy",
    "PlatformPublishOutcome",
    "PlatformPublishTarget",
    "PublishMediaRequest",
    "PublishMediaResult",
    "PublishVideoRequest",
    "PublishVideoResult",
    "SocialMediaPublisher",
    "SocialAccount",
    "SUCCESSFUL_PLATFORM_OUTCOMES",
    "SUPPORTED_GOHIGHLEVEL_PLATFORMS",
    "UploadedMedia",
    "build_default_social_property_publisher",
    "build_failed_batch_message",
    "extract_trace_id",
    "get_platform_policy",
    "normalise_platform_name",
    "normalise_publish_targets",
    "normalise_requested_platforms",
    "resolve_platform_artifact_kind",
    "resolve_platform_social_post_type",
    "select_first_available_location_user",
    "select_random_location_user",
    "selector_name",
    "validate_platform_publish_request",
]
