from __future__ import annotations

from typing import Protocol

from services.social_delivery.models import (
    LocationUser,
    PublishVideoRequest,
    PublishVideoResult,
    SocialAccount,
)


class SocialVideoPublisher(Protocol):
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

    def publish_video(self, request: PublishVideoRequest) -> PublishVideoResult:
        ...


__all__ = ["SocialVideoPublisher"]

