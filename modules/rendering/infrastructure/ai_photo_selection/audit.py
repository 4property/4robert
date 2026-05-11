"""Gemini photo-selection audit payload helpers.

Migrated from ``services/ai/photo_selection/selection.py`` during
sub-feature 18c. The original 774-LoC file was split: this module owns
the audit payload assembly and JSON writer, while ``selection.py`` keeps
the classification orchestrator and ranking algorithm.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from settings import DEFAULT_PHOTOS_TO_SELECT
from shared.observability import format_duration


def build_output_payload(
    property_context: dict[str, Any],
    model: str,
    downloads_dir: str,
    results: list[dict[str, Any]],
    started_at: float,
    *,
    annotate_results,
    schema_version: int,
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
        "schema_version": schema_version,
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


__all__ = [
    "build_output_payload",
    "write_output_payload",
]
