"""AI photo-selection adapter."""

from modules.rendering.infrastructure.ai_photo_selection.classify import (
    classify_property_images,
)
from modules.rendering.infrastructure.ai_photo_selection.client import (
    GeminiConfigurationError,
    GeminiPhotoSelectionClient,
    GeminiQuotaExhaustedError,
    GeminiSelectionError,
)
from modules.rendering.infrastructure.ai_photo_selection.prompting import (
    build_prompt,
    build_property_context,
    normalize_caption,
    normalize_highlights,
    normalize_space_id,
)
from modules.rendering.infrastructure.ai_photo_selection.selection import (
    GeminiImageRecord,
    GeminiSelectionOutcome,
    annotate_results,
    choose_selected_rows,
)

__all__ = [
    "GeminiConfigurationError",
    "GeminiImageRecord",
    "GeminiPhotoSelectionClient",
    "GeminiQuotaExhaustedError",
    "GeminiSelectionError",
    "GeminiSelectionOutcome",
    "annotate_results",
    "build_prompt",
    "build_property_context",
    "choose_selected_rows",
    "classify_property_images",
    "normalize_caption",
    "normalize_highlights",
    "normalize_space_id",
]
