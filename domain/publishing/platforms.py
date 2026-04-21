from __future__ import annotations

_PLATFORM_ALIASES = {
    "google business profile": "google_business_profile",
    "google-business-profile": "google_business_profile",
    "google_business_profile": "google_business_profile",
    "gbp": "google_business_profile",
}


def normalize_platform_name(platform: str) -> str:
    normalized_platform = str(platform or "").strip().lower()
    return _PLATFORM_ALIASES.get(normalized_platform, normalized_platform)


__all__ = ["normalize_platform_name"]
