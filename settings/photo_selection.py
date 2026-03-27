from __future__ import annotations

from settings.app import APP_SETTINGS

DEFAULT_PHOTOS_TO_SELECT = 7
GEMINI_SELECTION_AUDIT_FILENAME = "gemini_selection.json"
GEMINI_MODEL = APP_SETTINGS.gemini_model
GEMINI_API_KEY = APP_SETTINGS.gemini_api_key
GEMINI_TIMEOUT_SECONDS = APP_SETTINGS.gemini_timeout_seconds
GEMINI_RETRY_ATTEMPTS = APP_SETTINGS.gemini_retry_attempts
GEMINI_AREA_LABELS = (
    "exterior_front",
    "entry_hall",
    "living_room",
    "dining_room",
    "kitchen",
    "bedroom",
    "bathroom",
    "hallway",
    "stairs",
    "office",
    "laundry_room",
    "garage",
    "terrace_balcony",
    "garden_patio",
    "pool",
    "storage_room",
    "other",
)
GEMINI_AREA_SET = frozenset(GEMINI_AREA_LABELS)
GEMINI_EXTERIOR_AREAS = frozenset(
    {"exterior_front", "garden_patio", "terrace_balcony", "pool"}
)
GEMINI_SERVICE_AREAS = frozenset(
    {
        "entry_hall",
        "hallway",
        "stairs",
        "laundry_room",
        "garage",
        "storage_room",
        "other",
    }
)
GEMINI_VALID_RESULT_AREAS = GEMINI_AREA_SET | frozenset({"error", "quota_exhausted"})

__all__ = [
    "DEFAULT_PHOTOS_TO_SELECT",
    "GEMINI_API_KEY",
    "GEMINI_AREA_LABELS",
    "GEMINI_AREA_SET",
    "GEMINI_EXTERIOR_AREAS",
    "GEMINI_MODEL",
    "GEMINI_RETRY_ATTEMPTS",
    "GEMINI_SELECTION_AUDIT_FILENAME",
    "GEMINI_SERVICE_AREAS",
    "GEMINI_TIMEOUT_SECONDS",
    "GEMINI_VALID_RESULT_AREAS",
]
