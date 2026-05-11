"""Gemini photo classification driver.

Wraps the per-image Gemini classification call with logging, retry-aware
error handling and audit-payload assembly. Split out of ``selection.py``
during sub-feature 18c to keep that module under the ~500 LoC budget.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Sequence

from settings import DEFAULT_PHOTOS_TO_SELECT, GEMINI_MODEL
from shared.errors import PhotoFilteringError
from shared.observability import (
    LoggedProcess,
    create_progress,
    format_detail_line,
    format_duration,
    format_message_line,
)
from modules.catalog.domain.wordpress_property import Property
from modules.rendering.infrastructure.ai_photo_selection.audit import (
    write_output_payload,
)
from modules.rendering.infrastructure.ai_photo_selection.client import (
    GeminiConfigurationError,
    GeminiPhotoSelectionClient,
    GeminiQuotaExhaustedError,
)
from modules.rendering.infrastructure.ai_photo_selection.prompting import (
    build_prompt,
    build_property_context,
)
from modules.rendering.infrastructure.ai_photo_selection.selection import (
    GeminiImageRecord,
    GeminiSelectionOutcome,
    build_error_row,
    build_ordered_results,
    build_output_payload,
    build_result_row,
)

logger = logging.getLogger(__name__)


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


__all__ = ["classify_property_images"]
