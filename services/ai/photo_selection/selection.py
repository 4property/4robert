from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from settings import (
    DEFAULT_PHOTOS_TO_SELECT,
    GEMINI_AREA_SET,
    GEMINI_EXTERIOR_AREAS,
    GEMINI_MODEL,
    GEMINI_SERVICE_AREAS,
)
from core.logging import LoggedProcess, create_progress, format_detail_line, format_duration, format_message_line
from core.errors import PhotoFilteringError
from domain.properties.model import Property
from services.ai.photo_selection.client import (
    GeminiConfigurationError,
    GeminiPhotoSelectionClient,
    GeminiQuotaExhaustedError,
)
from services.ai.photo_selection.prompting import (
    build_prompt,
    build_property_context,
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


def format_fragment_list(fragments: list[str]) -> str:
    if not fragments:
        return ""
    if len(fragments) == 1:
        return fragments[0]
    if len(fragments) == 2:
        return f"{fragments[0]} and {fragments[1]}"
    return ", ".join(fragments[:-1]) + f", and {fragments[-1]}"


def pick_caption_highlights(
    row: dict[str, Any],
    used_highlights: set[str],
    *,
    limit: int = 2,
) -> list[str]:
    highlights = row.get("highlights") or []
    preferred = [item for item in highlights if item.lower() not in used_highlights]
    chosen = preferred[:limit]
    if len(chosen) < limit:
        for item in highlights:
            if item not in chosen:
                chosen.append(item)
            if len(chosen) >= limit:
                break
    return chosen


def build_standard_caption(
    row: dict[str, Any],
    used_highlights: set[str],
    area_occurrence: int,
) -> str:
    area = row["area"]
    highlights = pick_caption_highlights(row, used_highlights, limit=2)
    fragments = format_fragment_list(highlights)

    if area == "living_room" and fragments:
        return normalize_caption(f"Living room with {fragments}")
    if area == "kitchen" and fragments:
        return normalize_caption(f"Kitchen with {fragments}")
    if area == "dining_room" and fragments:
        return normalize_caption(f"Dining area with {fragments}")
    if area == "bedroom" and fragments:
        if area_occurrence > 1:
            return normalize_caption(f"Another bedroom includes {fragments}")
        return normalize_caption(f"Bedroom with {fragments}")
    if area == "bathroom" and fragments:
        if area_occurrence > 1:
            return normalize_caption(f"A further bathroom features {fragments}")
        return normalize_caption(f"Bathroom with {fragments}")
    if area == "office" and fragments:
        return normalize_caption(f"Versatile room with {fragments}")
    if area == "garden_patio" and fragments:
        return normalize_caption(f"Private patio with {fragments}")
    if area == "terrace_balcony" and fragments:
        return normalize_caption(f"Outdoor area with {fragments}")
    if area == "exterior_front" and fragments:
        return normalize_caption(f"Exterior view with {fragments}")
    if fragments:
        return normalize_caption(f"{area.replace('_', ' ').title()} with {fragments}")
    return normalize_caption(row.get("caption"), "Well-presented property photo.")


def build_hero_caption(area: str, property_context: dict[str, Any]) -> str:
    facts = (
        f"{property_context['bedrooms']}-bedroom, "
        f"{property_context['bathrooms']}-bathroom home with BER {property_context['ber_rating']}"
    ).strip()

    if area == "exterior_front":
        return normalize_caption(f"Own-door access to this {facts}")
    if area == "living_room":
        return normalize_caption(f"Bright living space in this {facts}")
    if area in {"kitchen", "dining_room"}:
        return normalize_caption(f"Well-presented day space within this {facts}")
    if area in {"garden_patio", "terrace_balcony"}:
        return normalize_caption(f"Private outdoor space complements this {facts}")
    if area == "bedroom":
        return normalize_caption(f"One of the three bedrooms in this {facts}")
    if area == "bathroom":
        return normalize_caption(f"The bathroom within this {facts}")
    return normalize_caption(f"Well-presented interiors in this {facts}")


def build_exterior_caption(area: str, property_context: dict[str, Any]) -> str:
    features = " ".join(property_context["property_features"]).lower()
    description = property_context["description"].lower()

    if area == "garden_patio":
        if "side access" in description:
            return "Private rear patio with side access adds practical outdoor space."
        if "garden shed" in description:
            return "Private rear patio with a garden shed adds useful outdoor space."
        return "Private outdoor space adds low-maintenance appeal to the home."
    if area == "terrace_balcony":
        return "Private outdoor space adds an extra layer of everyday enjoyment."
    if area == "exterior_front":
        if "own-door access" in features:
            return "Own-door access adds privacy and everyday convenience from the outset."
        return "Welcoming exterior presentation sets a strong first impression."
    if area == "pool":
        return "Outdoor leisure space adds an extra lifestyle feature to the property."
    return "Outdoor space adds another practical and appealing aspect to the home."


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
    annotated_results, selected_images = annotate_results(
        results,
        property_context,
        max_images=max_images,
        reserved_file=reserved_file,
    )
    elapsed_seconds = time.perf_counter() - started_at
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "model": model,
        "downloads_dir": downloads_dir,
        "property": {
            "id": property_context["id"],
            "title": property_context["title"],
            "address": property_context["address"],
            "property_type": property_context["property_type"],
            "status": property_context["status"],
            "bedrooms": property_context["bedrooms"],
            "bathrooms": property_context["bathrooms"],
            "ber_rating": property_context["ber_rating"],
            "property_features": property_context["property_features"],
        },
        "timing": {
            "elapsed_seconds": round(elapsed_seconds, 3),
            "elapsed_human": format_duration(elapsed_seconds),
        },
        "total_images": len(results),
        "processed_images": len(results),
        "selected_images": selected_images,
        "results": annotated_results,
    }
    if processing_error:
        payload["processing_error"] = processing_error
    return payload


def write_output_payload(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def classify_property_images(
    property_item: Property,
    image_records: Sequence[GeminiImageRecord],
    *,
    output_path: Path,
    downloads_dir: str,
    photos_to_select: int = DEFAULT_PHOTOS_TO_SELECT,
    client: GeminiPhotoSelectionClient | None = None,
) -> GeminiSelectionOutcome:
    started_at = time.perf_counter()
    property_context = build_property_context(property_item)
    prompt_text = build_prompt(property_context)
    reserved_file = next(
        (record.file for record in image_records if record.reserved),
        None,
    )
    results_by_file: dict[str, dict[str, Any]] = {}

    with LoggedProcess(
        logger,
        "GEMINI IMAGE CLASSIFICATION",
        (
            format_detail_line("Property ID", property_item.id, highlight=True),
            format_detail_line("Image count", len(image_records), highlight=True),
            format_detail_line("Downloads directory", downloads_dir),
            format_detail_line("Audit path", output_path),
        ),
        total_label="Total time",
    ):
        try:
            active_client = client or GeminiPhotoSelectionClient()
        except GeminiConfigurationError as exc:
            payload = build_output_payload(
                property_context,
                GEMINI_MODEL,
                downloads_dir,
                [],
                started_at,
                max_images=photos_to_select,
                reserved_file=reserved_file,
                status="failed",
                processing_error=str(exc),
            )
            write_output_payload(output_path, payload)
            logger.error(
                "%s\n%s",
                format_message_line("Gemini client configuration failed", tone="failure"),
                format_detail_line("Error", exc, highlight=True),
            )
            raise PhotoFilteringError(str(exc)) from exc

        try:
            with create_progress(transient=False) as progress:
                task_id = progress.add_task(
                    f"CLASSIFYING IMAGES WITH GEMINI FOR PROPERTY {property_item.id}",
                    total=len(image_records),
                )
                for image_number, image_record in enumerate(image_records, start=1):
                    progress.update(
                        task_id,
                        description=(
                            f"CLASSIFYING IMAGES WITH GEMINI FOR PROPERTY {property_item.id} "
                            f"[{image_number}/{len(image_records)}]"
                        ),
                    )
                    logger.info(
                        "%s\n%s\n%s\n%s",
                        format_message_line("Classifying image with Gemini", tone="progress"),
                        format_detail_line("Image", f"{image_number}/{len(image_records)}", highlight=True),
                        format_detail_line("File", image_record.file, highlight=True),
                        format_detail_line("Source URL", image_record.source_url),
                    )
                    try:
                        result = active_client.classify_image(image_record.local_path, prompt_text)
                        row = build_result_row(image_record, result)
                        if row["rejected"]:
                            logger.warning(
                                "%s\n%s\n%s\n%s\n%s",
                                format_message_line("Gemini image discarded", tone="warning"),
                                format_detail_line("File", row["file"], highlight=True),
                                format_detail_line("Rejected reason", row["rejected_reason"], highlight=True),
                                format_detail_line("Area", row["area"]),
                                format_detail_line("Caption", row["caption"]),
                            )
                        else:
                            logger.info(
                                "%s\n%s\n%s\n%s\n%s\n%s",
                                format_message_line("Gemini image classification completed", tone="success"),
                                format_detail_line("File", row["file"], highlight=True),
                                format_detail_line("Area", row["area"], highlight=True),
                                format_detail_line("Confidence", row["confidence"]),
                                format_detail_line("Showcase score", row["showcase_score"]),
                                format_detail_line("Caption", row["caption"]),
                            )
                    except GeminiQuotaExhaustedError as exc:
                        row = build_error_row(image_record, "quota_exhausted", str(exc))
                        results_by_file[row["file"]] = row
                        payload = build_output_payload(
                            property_context,
                            active_client.model,
                            downloads_dir,
                            build_ordered_results(image_records, results_by_file),
                            started_at,
                            max_images=photos_to_select,
                            reserved_file=reserved_file,
                            status="failed",
                            processing_error=str(exc),
                        )
                        write_output_payload(output_path, payload)
                        logger.error(
                            "%s\n%s\n%s",
                            format_message_line("Gemini daily quota exhausted", tone="failure"),
                            format_detail_line("File", image_record.file, highlight=True),
                            format_detail_line("Error", exc, highlight=True),
                        )
                        raise PhotoFilteringError(str(exc)) from exc
                    except Exception as exc:
                        row = build_error_row(image_record, "error", str(exc))
                        results_by_file[row["file"]] = row
                        payload = build_output_payload(
                            property_context,
                            active_client.model,
                            downloads_dir,
                            build_ordered_results(image_records, results_by_file),
                            started_at,
                            max_images=photos_to_select,
                            reserved_file=reserved_file,
                            status="failed",
                            processing_error=str(exc),
                        )
                        write_output_payload(output_path, payload)
                        logger.error(
                            "%s\n%s\n%s",
                            format_message_line("Gemini image classification failed", tone="failure"),
                            format_detail_line("File", image_record.file, highlight=True),
                            format_detail_line("Error", exc, highlight=True),
                        )
                        raise PhotoFilteringError(str(exc)) from exc

                    results_by_file[row["file"]] = row
                    progress.advance(task_id)

            ordered_results = build_ordered_results(image_records, results_by_file)
            payload = build_output_payload(
                property_context,
                active_client.model,
                downloads_dir,
                ordered_results,
                started_at,
                max_images=photos_to_select,
                reserved_file=reserved_file,
                status="completed",
            )
            write_output_payload(output_path, payload)
            logger.info(
                "%s\n%s\n%s\n%s\n%s",
                format_message_line("Gemini selection audit written", tone="success"),
                format_detail_line("Selected image count", len(payload["selected_images"]), highlight=True),
                format_detail_line("Processed image count", len(payload["results"]), highlight=True),
                format_detail_line("Audit path", output_path),
                format_detail_line("Elapsed", format_duration(time.perf_counter() - started_at), highlight=True),
            )
        finally:
            active_client.close()

    selected_photo_paths = tuple(
        next(
            record.local_path
            for record in image_records
            if record.file == row["file"]
        )
        for row in payload["selected_images"]
        if not row.get("reserved", False)
    )
    return GeminiSelectionOutcome(
        audit_path=output_path,
        payload=payload,
        selected_photo_paths=selected_photo_paths,
    )


__all__ = [
    "GeminiImageRecord",
    "GeminiSelectionOutcome",
    "annotate_results",
    "area_limit",
    "build_output_payload",
    "build_result_row",
    "can_add_candidate",
    "choose_selected_rows",
    "classify_property_images",
    "write_output_payload",
]

