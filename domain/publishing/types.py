from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.publishing.platforms import normalize_platform_name


def _normalise_platforms(raw_platforms: list[object] | tuple[object, ...]) -> tuple[str, ...]:
    normalized_platforms: list[str] = []
    seen: set[str] = set()
    for raw_platform in raw_platforms:
        platform = normalize_platform_name(str(raw_platform or ""))
        if not platform or platform in seen:
            continue
        seen.add(platform)
        normalized_platforms.append(platform)
    return tuple(normalized_platforms)


@dataclass(frozen=True, slots=True)
class SocialPublishContext:
    provider: str
    location_id: str
    access_token: str
    platforms: tuple[str, ...]

    def to_dict(self, *, include_access_token: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "provider": self.provider,
            "location_id": self.location_id,
            "platforms": list(self.platforms),
        }
        if include_access_token:
            payload["access_token"] = self.access_token
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SocialPublishContext | None":
        if not payload:
            return None
        provider = str(payload.get("provider") or "").strip()
        location_id = str(payload.get("location_id") or "").strip()
        access_token = str(payload.get("access_token") or "").strip()
        raw_platforms = payload.get("platforms")
        platforms: tuple[str, ...]
        if isinstance(raw_platforms, (list, tuple)):
            platforms = _normalise_platforms(tuple(raw_platforms))
        elif raw_platforms is not None:
            platforms = _normalise_platforms((raw_platforms,))
        else:
            platforms = _normalise_platforms((payload.get("platform"),))
        if not provider or not location_id or not platforms:
            return None
        return cls(
            provider=provider,
            location_id=location_id,
            access_token=access_token,
            platforms=platforms,
        )


@dataclass(frozen=True, slots=True)
class PlatformPublishTargetPlan:
    platform: str
    artifact_kind: str
    social_post_type: str
    description: str
    title: str | None = None
    target_url: str | None = None


@dataclass(frozen=True, slots=True)
class GeneratedPropertyContent:
    default_caption: str
    captions_by_platform: dict[str, str]
    titles_by_platform: dict[str, str]
    overlay_text: dict[str, str] = field(default_factory=dict)
    narration_script: str = ""


__all__ = [
    "GeneratedPropertyContent",
    "PlatformPublishTargetPlan",
    "SocialPublishContext",
]
