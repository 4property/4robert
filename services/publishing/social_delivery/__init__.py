from services.publishing.social_delivery.description import (
    TIKTOK_MAX_DESCRIPTION_LENGTH,
    build_base_social_description,
    build_platform_description,
    build_platform_description_for_property,
    build_platform_descriptions_for_property,
    build_platform_descriptions_for_property_with_url,
    build_platform_title_for_property,
    build_platform_titles_for_property,
    build_property_public_url,
    build_tiktok_description,
    build_tiktok_description_for_property,
    build_tiktok_description_for_record,
)
from services.publishing.social_delivery.post_copy import (
    CaptionLayout,
    DEFAULT_PROPERTY_CAPTION_LAYOUT,
    PropertyCaptionContext,
    SocialCopyBundle,
    build_property_caption,
    build_property_copy_bundle,
    render_property_caption,
)
from services.publishing.social_delivery.gohighlevel_client import GoHighLevelApiError, GoHighLevelClient
from services.publishing.social_delivery.gohighlevel_media_service import (
    GoHighLevelMediaService,
    MAX_GHL_GENERAL_UPLOAD_BYTES,
    MAX_GHL_VIDEO_UPLOAD_BYTES,
)
from services.publishing.social_delivery.gohighlevel_publisher import (
    GoHighLevelPublisher,
    SUPPORTED_GOHIGHLEVEL_PLATFORMS,
)
from services.publishing.social_delivery.gohighlevel_social_service import GoHighLevelSocialService
from services.publishing.social_delivery.interfaces import SocialMediaPublisher, SocialMediaPublisher
from services.publishing.social_delivery.models import (
    CreatedSocialPost,
    LocationUser,
    MultiPlatformPublishRequest,
    MultiPlatformPublishResult,
    PlatformPublishTarget,
    PlatformPublishOutcome,
    PublishMediaRequest,
    PublishMediaResult,
    PublishVideoRequest,
    PublishVideoResult,
    SocialAccount,
    SUCCESSFUL_PLATFORM_OUTCOMES,
    UploadedMedia,
)
from services.publishing.social_delivery.platforms import (
    SocialPlatformConfig,
    get_platform_config,
    list_supported_platforms,
    normalize_platform_name,
)
from services.publishing.social_delivery.user_selection import (
    LocationUserFallbackSelector,
    select_first_available_location_user,
    select_random_location_user,
)

__all__ = [
    "CreatedSocialPost",
    "CaptionLayout",
    "DEFAULT_PROPERTY_CAPTION_LAYOUT",
    "GoHighLevelApiError",
    "GoHighLevelClient",
    "GoHighLevelMediaService",
    "GoHighLevelPublisher",
    "GoHighLevelPropertyPublisher",
    "GoHighLevelSocialService",
    "LocationUser",
    "LocationUserFallbackSelector",
    "MAX_GHL_GENERAL_UPLOAD_BYTES",
    "MAX_GHL_VIDEO_UPLOAD_BYTES",
    "MultiPlatformPublishRequest",
    "MultiPlatformPublishResult",
    "PlatformPublishTarget",
    "PlatformPublishOutcome",
    "PropertyCaptionContext",
    "PublishMediaRequest",
    "PublishMediaResult",
    "PublishVideoRequest",
    "PublishVideoResult",
    "SocialCopyBundle",
    "SocialMediaPublisher",
    "SocialPlatformConfig",
    "SUPPORTED_GOHIGHLEVEL_PLATFORMS",
    "SUCCESSFUL_PLATFORM_OUTCOMES",
    "SocialAccount",
    "SocialMediaPublisher",
    "TIKTOK_MAX_DESCRIPTION_LENGTH",
    "UploadedMedia",
    "build_base_social_description",
    "build_platform_description",
    "build_platform_description_for_property",
    "build_platform_descriptions_for_property",
    "build_platform_descriptions_for_property_with_url",
    "build_platform_title_for_property",
    "build_platform_titles_for_property",
    "build_property_caption",
    "build_property_copy_bundle",
    "build_property_public_url",
    "get_platform_config",
    "list_supported_platforms",
    "normalize_platform_name",
    "render_property_caption",
    "build_tiktok_description",
    "build_tiktok_description_for_property",
    "build_tiktok_description_for_record",
    "select_first_available_location_user",
    "select_random_location_user",
]


def __getattr__(name: str):
    if name == "GoHighLevelPropertyPublisher":
        from services.publishing.social_delivery.property_publisher import GoHighLevelPropertyPublisher

        return GoHighLevelPropertyPublisher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
