from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class SocialPlatformContentSource(Protocol):
    slug: str
    title: str | None
    price: str | None
    agent_name: str | None
    agent_email: str | None
    agent_mobile: str | None
    agent_number: str | None
    agency_psra: str | None


DescriptionBuilder = Callable[[SocialPlatformContentSource, str], str]
TitleBuilder = Callable[[SocialPlatformContentSource], str | None]
UploadFileNameBuilder = Callable[[str | None], str | None]
GoHighLevelPayloadBuilder = Callable[[str | None, str | None], dict[str, object]]


@dataclass(frozen=True, slots=True)
class SocialPlatformConfig:
    platform: str
    aliases: tuple[str, ...]
    default_artifact_kind: str
    default_social_post_type: str
    allowed_artifact_kinds: tuple[str, ...]
    allowed_social_post_types: tuple[str, ...]
    max_caption_length: int | None
    build_description: DescriptionBuilder
    build_title: TitleBuilder
    build_upload_file_name: UploadFileNameBuilder
    build_gohighlevel_payload: GoHighLevelPayloadBuilder

    def resolve_artifact_kind(self, requested_artifact_kind: str) -> str:
        normalized_requested = str(requested_artifact_kind or "").strip().lower()
        if normalized_requested in self.allowed_artifact_kinds:
            return normalized_requested
        return self.default_artifact_kind

    def resolve_social_post_type(self, requested_social_post_type: str) -> str:
        normalized_requested = str(requested_social_post_type or "").strip().lower()
        if normalized_requested in self.allowed_social_post_types:
            return normalized_requested
        return self.default_social_post_type


__all__ = [
    "DescriptionBuilder",
    "GoHighLevelPayloadBuilder",
    "SocialPlatformConfig",
    "SocialPlatformContentSource",
    "TitleBuilder",
    "UploadFileNameBuilder",
]
