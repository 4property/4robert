"""Gemini photo-selection ranking algorithm.

Migrated from ``services/ai/photo_selection/selection.py`` during
sub-feature 18c. The original 774-LoC file was split into:

- ``selection.py`` (this module) — selection algorithm + result-row
  builders + audit-payload wrapper.
- ``classify.py`` — per-image Gemini classification driver
  (``classify_property_images``).
- ``audit.py`` — payload assembly + JSON writer.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from settings import (
    DEFAULT_PHOTOS_TO_SELECT,
    GEMINI_AREA_SET,
    GEMINI_EXTERIOR_AREAS,
    GEMINI_SERVICE_AREAS,
)
from modules.rendering.infrastructure.ai_photo_selection.audit import (
    build_output_payload as _build_output_payload,
)
from modules.rendering.infrastructure.ai_photo_selection.prompting import (
    clamp_int,
    normalize_caption,
    normalize_highlights,
    normalize_reject_reason,
    normalize_space_id,
)

SCHEMA_VERSION = 4
logger = logging.getLogger(__name__)
_REJECTED_NON_PHOTO_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "floorplan",
        re.compile(
            r"(?<![a-z0-9])floor[\s_-]*plan(?![a-z0-9])|(?<![a-z0-9])site[\s_-]*plan(?![a-z0-9])|"
            r"(?<![a-z0-9])house[\s_-]*plan(?![a-z0-9])|(?<![a-z0-9])property[\s_-]*plan(?![a-z0-9])|"
            r"(?<![a-z0-9])architectural[\s_-]*plan(?![a-z0-9])|(?<![a-z0-9])blueprint(?![a-z0-9])",
            re.IGNORECASE,
        ),
    ),
    (
        "map",
        re.compile(
            r"(?<![a-z0-9])location[\s_-]*map(?![a-z0-9])|(?<![a-z0-9])site[\s_-]*map(?![a-z0-9])|"
            r"(?<![a-z0-9])google[\s_-]*map(?![a-z0-9])|(?<![a-z0-9])map(?![a-z0-9])",
            re.IGNORECASE,
        ),
    ),
    (
        "aerial_view",
        re.compile(
            r"(?<![a-z0-9])aerial(?![a-z0-9])|(?<![a-z0-9])satellite(?![a-z0-9])|"
            r"(?<![a-z0-9])bird'?s[\s_-]*eye(?![a-z0-9])|(?<![a-z0-9])sky[\s_-]*view(?![a-z0-9])",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class GeminiImageRecord:
    file: str
    source_url: str
    source_index: int
    local_path: Path
    relative_path: str
    reserved: bool = False


@dataclass(frozen=True, slots=True)
class GeminiSelectionOutcome:
    audit_path: Path
    payload: dict[str, Any]
    selected_photo_paths: tuple[Path, ...]


def build_result_row(image_record: GeminiImageRecord, result: dict[str, Any]) -> dict[str, Any]:
    area = str(result.get("area", "other")).strip()
    if area not in GEMINI_AREA_SET:
        area = "other"

    rejected_reason = detect_rejected_non_photo_asset(image_record, result)
    rejected = rejected_reason is not None
    highlights = normalize_highlights(result.get("highlights"))
    caption = normalize_caption(
        result.get("caption"),
        "Well-presented interior photo.",
    )
    space_id = normalize_space_id(result.get("space_id"), area)
    showcase_score = clamp_int(result.get("showcase_score"), 0)
    if rejected:
        area = "other"
        showcase_score = 0
        space_id = "discarded_non_photo_asset"
        highlights = []
        caption = "Discarded non-photo asset."

    return {
        "file": image_record.file,
        "source_url": image_record.source_url,
        "source_index": image_record.source_index,
        "local_path": image_record.relative_path,
        "area": area,
        "confidence": clamp_int(result.get("confidence"), 0),
        "showcase_score": showcase_score,
        "space_id": space_id,
        "highlights": highlights,
        "caption": caption,
        "rejected": rejected,
        "rejected_reason": rejected_reason,
        "reserved": image_record.reserved,
    }


def build_error_row(image_record: GeminiImageRecord, area: str, message: str) -> dict[str, Any]:
    return {
        "file": image_record.file,
        "source_url": image_record.source_url,
        "source_index": image_record.source_index,
        "local_path": image_record.relative_path,
        "area": area,
        "confidence": 0,
        "showcase_score": 0,
        "space_id": normalize_space_id(area, area),
        "highlights": [],
        "caption": normalize_caption(message, "Processing issue."),
        "rejected": False,
        "rejected_reason": None,
        "reserved": image_record.reserved,
    }


def build_ordered_results(
    image_records: Sequence[GeminiImageRecord],
    results_by_file: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered_results = []
    for image_record in image_records:
        row = results_by_file.get(image_record.file)
        if row is not None:
            ordered_results.append(dict(row))
    return ordered_results


def is_valid_candidate(row: dict[str, Any]) -> bool:
    return row.get("area") in GEMINI_AREA_SET and not bool(row.get("rejected"))


def detect_rejected_non_photo_asset(
    image_record: GeminiImageRecord,
    result: dict[str, Any],
) -> str | None:
    explicit_reason = normalize_reject_reason(result.get("reject_reason"))
    if bool(result.get("reject_asset")):
        return explicit_reason or "non_photo_asset"

    signals = [
        image_record.file,
        image_record.source_url,
        str(result.get("space_id") or ""),
        str(result.get("caption") or ""),
        *(str(item) for item in normalize_highlights(result.get("highlights"))),
        explicit_reason or "",
    ]
    combined_signal_text = "\n".join(signal for signal in signals if signal).strip()
    if not combined_signal_text:
        return None

    for rejected_reason, pattern in _REJECTED_NON_PHOTO_PATTERNS:
        if pattern.search(combined_signal_text):
            return rejected_reason
    return None


def area_limit(area: str) -> int:
    if area == "bedroom":
        return 3
    if area == "bathroom":
        return 2
    return 1


def can_add_candidate(
    row: dict[str, Any],
    selected_rows: list[dict[str, Any]],
    area_counts: Counter[str],
    used_files: set[str],
) -> bool:
    if row["file"] in used_files:
        return False
    area = row["area"]
    space_id = row.get("space_id") or area
    if area not in GEMINI_AREA_SET:
        return False
    if area_counts[area] >= area_limit(area):
        return False
    if any(
        (selected.get("space_id") or selected["area"]) == space_id
        for selected in selected_rows
    ):
        return False
    if area in GEMINI_SERVICE_AREAS:
        current_service_count = sum(
            1
            for selected in selected_rows
            if selected["area"] in GEMINI_SERVICE_AREAS
        )
        if current_service_count >= 1:
            return False
    return True


def rank_rows(
    rows: list[dict[str, Any]],
    priority_map: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    priority_map = priority_map or {}
    return sorted(
        rows,
        key=lambda row: (
            priority_map.get(row["area"], -999),
            row["showcase_score"],
            row["confidence"],
        ),
        reverse=True,
    )


def choose_first_match(
    ranked_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    area_counts: Counter[str],
    used_files: set[str],
    predicate,
) -> dict[str, Any] | None:
    for row in ranked_rows:
        if predicate(row) and can_add_candidate(row, selected_rows, area_counts, used_files):
            return row
    return None


def choose_selected_rows(
    results: list[dict[str, Any]],
    *,
    max_images: int = DEFAULT_PHOTOS_TO_SELECT,
    reserved_file: str | None = None,
) -> list[dict[str, Any]]:
    candidates = [row for row in results if is_valid_candidate(row)]
    selected_rows: list[dict[str, Any]] = []
    used_files: set[str] = set()
    area_counts: Counter[str] = Counter()

    def add_row(row: dict[str, Any]) -> None:
        selected_rows.append(dict(row))
        used_files.add(row["file"])
        area_counts[row["area"]] += 1

    general_ranked = rank_rows(candidates)
    hero_ranked = rank_rows(
        candidates,
        {
            "exterior_front": 10,
            "living_room": 9,
            "kitchen": 8,
            "dining_room": 8,
            "garden_patio": 7,
            "terrace_balcony": 7,
            "bedroom": 6,
            "bathroom": 5,
        },
    )
    exterior_ranked = rank_rows(
        candidates,
        {
            "garden_patio": 10,
            "terrace_balcony": 9,
            "exterior_front": 8,
            "pool": 7,
        },
    )

    if reserved_file:
        reserved_row = next(
            (row for row in general_ranked if row["file"] == reserved_file),
            None,
        )
        if reserved_row is not None:
            add_row(reserved_row)

    if not selected_rows:
        hero = choose_first_match(
            hero_ranked,
            selected_rows,
            area_counts,
            used_files,
            lambda row: row["area"]
            in {
                "exterior_front",
                "living_room",
                "kitchen",
                "dining_room",
                "garden_patio",
                "terrace_balcony",
                "bedroom",
                "bathroom",
            },
        )
        if hero is None and general_ranked:
            hero = choose_first_match(
                general_ranked,
                selected_rows,
                area_counts,
                used_files,
                lambda row: True,
            )
        if hero is not None:
            add_row(hero)

    if len(selected_rows) < max_images:
        exterior = choose_first_match(
            exterior_ranked,
            selected_rows,
            area_counts,
            used_files,
            lambda row: row["area"] in GEMINI_EXTERIOR_AREAS,
        )
        if exterior is None:
            exterior = choose_first_match(
                general_ranked,
                selected_rows,
                area_counts,
                used_files,
                lambda row: True,
            )
        if exterior is not None:
            add_row(exterior)

    desired_predicates = [
        lambda row: row["area"] == "living_room",
        lambda row: row["area"] in {"kitchen", "dining_room"},
        lambda row: row["area"] == "bedroom",
        lambda row: row["area"] == "bathroom",
    ]
    for predicate in desired_predicates:
        if len(selected_rows) >= max_images:
            break
        row = choose_first_match(
            general_ranked,
            selected_rows,
            area_counts,
            used_files,
            predicate,
        )
        if row is not None:
            add_row(row)

    for row in general_ranked:
        if len(selected_rows) >= max_images:
            break
        if can_add_candidate(row, selected_rows, area_counts, used_files):
            add_row(row)

    return selected_rows[:max_images]


def annotate_results(
    results: list[dict[str, Any]],
    property_context: dict[str, Any],
    *,
    max_images: int = DEFAULT_PHOTOS_TO_SELECT,
    reserved_file: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del property_context
    selected_rows = choose_selected_rows(
        results,
        max_images=max_images,
        reserved_file=reserved_file,
    )
    selected_by_file: dict[str, dict[str, Any]] = {}

    for slide_number, row in enumerate(selected_rows, start=1):
        selected_row = dict(row)
        selected_row["selected"] = True
        selected_row["slide_number"] = slide_number
        selected_by_file[selected_row["file"]] = selected_row

    annotated_results = []
    for row in results:
        annotated = dict(row)
        selected_row = selected_by_file.get(row["file"])
        if selected_row is not None:
            annotated["selected"] = True
            annotated["slide_number"] = selected_row["slide_number"]
            annotated["caption"] = selected_row["caption"]
        else:
            annotated["selected"] = False
            annotated["slide_number"] = None
        annotated_results.append(annotated)

    selected_images = [
        row
        for row in sorted(
            selected_by_file.values(),
            key=lambda row: row["slide_number"],
        )
    ]
    return annotated_results, selected_images


def build_output_payload(
    property_context: dict[str, Any],
    model: str,
    downloads_dir: str,
    results: list[dict[str, Any]],
    started_at: float,
    *,
    max_images: int = DEFAULT_PHOTOS_TO_SELECT,
    reserved_file: str | None = None,
    status: str = "completed",
    processing_error: str | None = None,
) -> dict[str, Any]:
    """Local thin wrapper preserving the legacy public signature."""
    return _build_output_payload(
        property_context,
        model,
        downloads_dir,
        results,
        started_at,
        annotate_results=annotate_results,
        schema_version=SCHEMA_VERSION,
        max_images=max_images,
        reserved_file=reserved_file,
        status=status,
        processing_error=processing_error,
    )


__all__ = [
    "GeminiImageRecord",
    "GeminiSelectionOutcome",
    "annotate_results",
    "area_limit",
    "build_error_row",
    "build_ordered_results",
    "build_output_payload",
    "build_result_row",
    "can_add_candidate",
    "choose_selected_rows",
    "detect_rejected_non_photo_asset",
    "is_valid_candidate",
    "rank_rows",
]
