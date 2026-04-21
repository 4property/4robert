from __future__ import annotations

from typing import Protocol

from services.publishing.social_delivery.models import (
    LocationUser,
    MultiPlatformPublishRequest,
    MultiPlatformPublishResult,
    PublishMediaRequest,
    PublishMediaResult,
    SocialAccount,
)


class SocialMediaPublisher(Protocol):
    def list_connected_accounts(
        self,
        *,
        location_id: str,
        access_token: str,
        platform: str,
    ) -> tuple[SocialAccount, ...]:
        ...

    def list_location_users(
        self,
        *,
        location_id: str,
        access_token: str,
    ) -> tuple[LocationUser, ...]:
        ...

    def publish_media(self, request: PublishMediaRequest) -> PublishMediaResult:
        ...

    def publish_media_to_platforms(
        self,
        request: MultiPlatformPublishRequest,
    ) -> MultiPlatformPublishResult:
        ...
__all__ = ["SocialMediaPublisher"]
