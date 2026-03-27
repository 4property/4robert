from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SocialAccount:
    id: str
    name: str
    platform: str
    account_type: str
    is_expired: bool
    raw_data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LocationUser:
    id: str
    first_name: str
    last_name: str
    email: str
    raw_data: dict[str, Any]

    @property
    def display_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part).strip() or self.email or self.id


@dataclass(frozen=True, slots=True)
class UploadedMedia:
    file_id: str
    url: str
    mime_type: str
    file_name: str
    raw_response: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CreatedSocialPost:
    post_id: str | None
    status: str | None
    message: str | None
    raw_response: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PublishVideoRequest:
    video_path: Path
    description: str = ""
    target_url: str | None = None
    provider: str = "gohighlevel"
    location_id: str = ""
    access_token: str = ""
    platform: str = "tiktok"
    account_id: str | None = None
    user_id: str | None = None
    source_site_id: str | None = None


@dataclass(frozen=True, slots=True)
class PublishVideoResult:
    selected_account: SocialAccount
    selected_user: LocationUser
    uploaded_media: UploadedMedia
    created_post: CreatedSocialPost
    description: str
    target_url: str | None
    source_site_id: str | None


__all__ = [
    "CreatedSocialPost",
    "LocationUser",
    "PublishVideoRequest",
    "PublishVideoResult",
    "SocialAccount",
    "UploadedMedia",
]
