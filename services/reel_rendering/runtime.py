from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import struct
import zlib
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import GEMINI_SELECTION_AUDIT_FILENAME
from settings.images import IMAGE_EXTENSIONS
from settings.http import HTTP_HEADERS, OUTBOUND_HTTP_TIMEOUT_SECONDS
from core.dependencies import require_dependency
from core.errors import PropertyReelError, ResourceNotFoundError
from services.ai_photo_selection.prompting import normalize_caption
from services.reel_rendering.models import (
    PRIMARY_IMAGE_NAME,
    PropertyRenderData,
    PropertyReelSlide,
    PropertyReelTemplate,
)
from services.webhook_transport.site_storage import resolve_site_storage_layout, safe_site_dirname

logger = logging.getLogger(__name__)
_BRANDING_CACHE_DIRNAME = "_branding"
_VALID_BER_ICON_CODES = {
    "A1",
    "A2",
    "A3",
    "B1",
    "B2",
    "B3",
    "C1",
    "C2",
    "C3",
    "D1",
    "D2",
    "E1",
    "E2",
    "F",
    "G",
}


def resolve_ffmpeg_binary() -> str:
    ffmpeg_binary = shutil.which("ffmpeg")
    if ffmpeg_binary:
        return ffmpeg_binary

    imageio_ffmpeg = require_dependency(
        "imageio_ffmpeg",
        package_name="imageio-ffmpeg",
        display_name="imageio-ffmpeg",
        feature="reel generation when ffmpeg is not on PATH",
    )
    return imageio_ffmpeg.get_ffmpeg_exe()


def resolve_font_path(path: Path) -> Path:
    if path.exists():
        return path
    if not path.is_absolute():
        project_relative_path = Path(__file__).resolve().parents[2] / path
        if project_relative_path.exists():
            return project_relative_path
    raise ResourceNotFoundError(
        "Font file not found for reel subtitle rendering.",
        context={"requested_path": str(path)},
        hint=(
            "Set REEL_SUBTITLE_FONT_PATH to a readable .ttf font and ensure the font file is "
            "present on the deployed host."
        ),
    )


def resolve_asset_path(
    workspace_dir: Path,
    settings: PropertyReelTemplate,
    filename: str,
) -> Path:
    asset_path = workspace_dir / settings.assets_dirname / filename
    if asset_path.exists():
        return asset_path
    raise ResourceNotFoundError(
        "Asset file not found for reel rendering.",
        context={"asset_path": str(asset_path), "filename": filename},
        hint=(
            "Ensure the assets directory is deployed with the application and that the service user "
            "can read the referenced file."
        ),
    )


def normalize_ber_icon_code(ber_rating: str | None) -> str | None:
    if ber_rating is None:
        return None

    cleaned = re.sub(r"^BER", "", ber_rating.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"[^A-Za-z0-9]", "", cleaned).upper()
    if not cleaned:
        return None
    if cleaned in _VALID_BER_ICON_CODES:
        return cleaned
    return None


def resolve_ber_icon_path(
    workspace_dir: Path,
    settings: PropertyReelTemplate,
    ber_rating: str | None,
) -> Path | None:
    normalized_code = normalize_ber_icon_code(ber_rating)
    cleaned_rating = (ber_rating or "").strip()
    if normalized_code is None:
        if cleaned_rating:
            logger.warning("Unsupported BER rating %r for reel header icon.", cleaned_rating)
        return None

    icon_path = (
        workspace_dir
        / settings.assets_dirname
        / settings.ber_icons_dirname
        / f"{normalized_code}.png"
    )
    if icon_path.exists():
        return icon_path

    logger.warning(
        "BER icon for rating %s was not found at %s.",
        normalized_code,
        icon_path,
    )
    return None


def download_remote_image(image_url: str, destination: Path) -> Path:
    request = Request(image_url, headers=HTTP_HEADERS)
    with urlopen(request, timeout=OUTBOUND_HTTP_TIMEOUT_SECONDS) as response:
        with destination.open("wb") as file_handle:
            shutil.copyfileobj(response, file_handle)
    return destination


def download_primary_image(primary_image_url: str, destination: Path) -> Path:
    return download_remote_image(primary_image_url, destination)


def prepare_cover_logo_image(
    workspace_dir: Path,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
) -> Path | None:
    agency_logo_url = str(property_data.agency_logo_url or "").strip()
    if not agency_logo_url:
        return None
    if _has_explicit_unsupported_image_suffix(agency_logo_url):
        logger.warning(
            "Skipping agency logo %r for property %s (%s) because the file extension is not supported.",
            agency_logo_url,
            property_data.property_id,
            property_data.slug,
        )
        return None

    destination = _resolve_cached_branding_destination(
        workspace_dir=workspace_dir,
        site_id=property_data.site_id,
        slug=property_data.slug,
        image_url=agency_logo_url,
        label="agency-logo",
    )
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    try:
        return download_remote_image(agency_logo_url, destination)
    except Exception as error:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        logger.warning(
            "Failed to download agency logo %r for property %s (%s). Continuing without agency logo. Error: %s",
            agency_logo_url,
            property_data.property_id,
            property_data.slug,
            error,
        )
        return None


def prepare_agent_image(
    workspace_dir: Path,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    temp_dir: Path,
) -> Path:
    if not property_data.agent_photo_url:
        agency_logo_path = prepare_cover_logo_image(workspace_dir, property_data, settings)
        if agency_logo_path is not None:
            return agency_logo_path
        return _write_transparent_placeholder(temp_dir / "agent_placeholder.png")

    suffix = Path(property_data.agent_photo_url).suffix or ".jpg"
    destination = temp_dir / f"agent_photo{suffix.lower()}"
    try:
        return download_remote_image(property_data.agent_photo_url, destination)
    except Exception as error:
        logger.warning(
            "Failed to download agent photo %r for property %s (%s). Continuing with fallback image. Error: %s",
            property_data.agent_photo_url,
            property_data.property_id,
            property_data.slug,
            error,
        )
        agency_logo_path = prepare_cover_logo_image(workspace_dir, property_data, settings)
        if agency_logo_path is not None:
            return agency_logo_path
        return _write_transparent_placeholder(temp_dir / "agent_placeholder.png")


def sorted_image_paths(folder: Path) -> list[Path]:
    return sorted(
        candidate
        for candidate in folder.iterdir()
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS
    )


def _selection_audit_path(selected_image_dir: Path) -> Path:
    return selected_image_dir.parent / GEMINI_SELECTION_AUDIT_FILENAME


def _strip_selected_prefix(filename: str) -> str:
    return re.sub(r"^\d+_", "", filename)


def _load_selected_image_rows(selected_image_dir: Path) -> list[dict[str, object]]:
    audit_path = _selection_audit_path(selected_image_dir)
    if not audit_path.exists():
        return []

    try:
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Failed to read Gemini selection audit at %s: %s",
            audit_path,
            exc,
        )
        return []

    rows = payload.get("selected_images")
    if not isinstance(rows, list):
        logger.warning(
            "Gemini selection audit at %s does not contain a valid selected_images list.",
            audit_path,
        )
        return []

    return [row for row in rows if isinstance(row, dict)]


def _row_caption(row: dict[str, object] | None) -> str | None:
    if row is None:
        return None
    caption = row.get("caption")
    if not isinstance(caption, str):
        return None
    cleaned = normalize_caption(caption, "").strip()
    return cleaned or None


def _match_selected_row(
    image_path: Path,
    *,
    rows_by_exact: dict[str, dict[str, object]],
    rows_by_normalized: dict[str, dict[str, object]],
    reserved_row: dict[str, object] | None,
) -> dict[str, object] | None:
    if image_path.stem.lower() == PRIMARY_IMAGE_NAME:
        return reserved_row or rows_by_exact.get(image_path.name)

    normalized_name = _strip_selected_prefix(image_path.name)
    normalized_stem = _strip_selected_prefix(image_path.stem)
    return (
        rows_by_exact.get(image_path.name)
        or rows_by_exact.get(normalized_name)
        or rows_by_normalized.get(image_path.name)
        or rows_by_normalized.get(normalized_name)
        or rows_by_normalized.get(f"{normalized_stem}{image_path.suffix}")
    )


def build_local_selected_slides(
    selected_image_dir: Path,
    selected_image_paths: tuple[Path, ...] = (),
) -> tuple[PropertyReelSlide, ...]:
    if selected_image_paths:
        image_paths = selected_image_paths
    elif selected_image_dir.exists():
        image_paths = tuple(sorted_image_paths(selected_image_dir))
    else:
        image_paths = ()
    if not image_paths:
        return ()

    rows = _load_selected_image_rows(selected_image_dir)
    reserved_row = next(
        (row for row in rows if row.get("reserved") is True),
        None,
    )
    rows_by_exact = {
        str(row["file"]).strip(): row
        for row in rows
        if str(row.get("file", "")).strip()
    }
    rows_by_normalized = {
        _strip_selected_prefix(file_name): row
        for file_name, row in rows_by_exact.items()
    }

    slides: list[PropertyReelSlide] = []
    for image_path in image_paths:
        matched_row = _match_selected_row(
            image_path,
            rows_by_exact=rows_by_exact,
            rows_by_normalized=rows_by_normalized,
            reserved_row=reserved_row,
        )
        if matched_row is None and rows:
            logger.warning(
                "No Gemini caption match found for selected reel image %s.",
                image_path.name,
            )
        slides.append(
            PropertyReelSlide(
                image_path=image_path,
                caption=_row_caption(matched_row),
            )
        )
    return tuple(slides)


def select_reel_slides(
    property_data: PropertyRenderData,
    *,
    max_slide_count: int,
    temp_dir: Path,
) -> list[PropertyReelSlide]:
    slides = list(property_data.selected_slides) or list(
        build_local_selected_slides(
            property_data.selected_image_dir,
            property_data.selected_image_paths,
        )
    )
    reserved_row = next(
        (
            row
            for row in _load_selected_image_rows(property_data.selected_image_dir)
            if row.get("reserved") is True
        ),
        None,
    )
    primary_slide = next(
        (
            slide
            for slide in slides
            if slide.image_path.stem.lower() == PRIMARY_IMAGE_NAME
        ),
        None,
    )

    if primary_slide is None and property_data.featured_image_url:
        suffix = Path(property_data.featured_image_url).suffix or ".jpg"
        primary_image_path = download_primary_image(
            property_data.featured_image_url,
            temp_dir / f"{PRIMARY_IMAGE_NAME}{suffix.lower()}",
        )
        primary_slide = PropertyReelSlide(
            image_path=primary_image_path,
            caption=_row_caption(reserved_row),
        )

    ordered_slides: list[PropertyReelSlide] = []
    if primary_slide is not None:
        ordered_slides.append(primary_slide)

    ordered_slides.extend(
        slide
        for slide in slides
        if primary_slide is None
        or slide.image_path.resolve() != primary_slide.image_path.resolve()
    )

    if not ordered_slides:
        raise PropertyReelError(
            "No local images are available for reel generation.",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "selected_image_dir": str(property_data.selected_image_dir),
            },
            hint=(
                "Run the asset preparation stage first and verify the selected_photos directory is "
                "persisted on the deployed host."
            ),
        )

    return ordered_slides[:max_slide_count]


def select_reel_images(
    property_data: PropertyRenderData,
    *,
    max_slide_count: int,
    temp_dir: Path,
) -> list[Path]:
    return [
        slide.image_path
        for slide in select_reel_slides(
            property_data,
            max_slide_count=max_slide_count,
            temp_dir=temp_dir,
        )
    ]


def resolve_reel_output_path(
    workspace_dir: Path,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    output_path: str | Path | None,
) -> Path:
    del settings
    output_dir = resolve_site_storage_layout(
        workspace_dir,
        property_data.site_id,
    ).generated_reels_root
    output_dir.mkdir(parents=True, exist_ok=True)
    final_output_path = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else output_dir / f"{property_data.slug}-reel.mp4"
    )
    final_output_path.parent.mkdir(parents=True, exist_ok=True)
    return final_output_path


def resolve_manifest_output_path(
    workspace_dir: Path,
    site_id: str,
    slug: str,
    settings: PropertyReelTemplate,
    output_path: str | Path | None,
) -> Path:
    del settings
    storage_paths = resolve_site_storage_layout(workspace_dir, site_id)
    manifest_path = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else storage_paths.generated_reels_root / f"{slug}-reel.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    return manifest_path


def compute_slide_timing(
    settings: PropertyReelTemplate,
    slide_count: int,
) -> tuple[int, float, float]:
    segment_frames, segment_durations, total_duration = compute_segment_timing(
        settings,
        slide_count,
    )
    if not segment_frames or not segment_durations:
        return 0, 0.0, total_duration
    return segment_frames[0], segment_durations[0], total_duration


def compute_segment_timing(
    settings: PropertyReelTemplate,
    slide_count: int,
) -> tuple[list[int], list[float], float]:
    if slide_count <= 0:
        intro_duration = settings.intro_duration_seconds if settings.include_intro else 0.0
        return [], [], intro_duration

    slide_frames = max(1, round(settings.seconds_per_slide * settings.fps))
    segment_frames = [slide_frames for _ in range(slide_count)]
    intro_duration = settings.intro_duration_seconds if settings.include_intro else 0.0
    if slide_count >= settings.max_slide_count:
        available_duration = max(settings.total_duration_seconds - intro_duration, 0.0)
        target_total_frames = max(slide_count, round(available_duration * settings.fps))
        base_frames, remainder = divmod(target_total_frames, slide_count)
        base_frames = max(base_frames, 1)
        segment_frames = [
            base_frames + (1 if index < remainder else 0)
            for index in range(slide_count)
        ]

    segment_durations = [frame_count / settings.fps for frame_count in segment_frames]
    total_duration = intro_duration + sum(segment_durations)
    return segment_frames, segment_durations, total_duration


def _resolve_cached_branding_destination(
    *,
    workspace_dir: Path,
    site_id: str,
    slug: str,
    image_url: str,
    label: str,
) -> Path:
    branding_dir = (
        workspace_dir
        / "generated_media"
        / safe_site_dirname(site_id)
        / _BRANDING_CACHE_DIRNAME
    )
    branding_dir.mkdir(parents=True, exist_ok=True)
    suffix = _resolve_remote_image_suffix(image_url)
    image_hash = hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:12]
    return branding_dir / f"{slug}-{label}-{image_hash}{suffix}"


def _resolve_remote_image_suffix(image_url: str) -> str:
    parsed_path = urlparse(image_url).path
    suffix = Path(parsed_path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    return ".png"


def _has_explicit_unsupported_image_suffix(image_url: str) -> bool:
    parsed_path = urlparse(image_url).path
    suffix = Path(parsed_path).suffix.lower()
    return bool(suffix) and suffix not in IMAGE_EXTENSIONS


def _write_transparent_placeholder(destination: Path) -> Path:
    def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + chunk_type
            + payload
            + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
        )

    png_payload = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0),
        )
        + _chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + _chunk(b"IEND", b"")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(png_payload)
    return destination


def compute_audio_fade(total_duration: float) -> tuple[float, float]:
    audio_fade_duration = min(1.5, total_duration)
    audio_fade_start = max(total_duration - audio_fade_duration, 0.0)
    return audio_fade_duration, audio_fade_start


__all__ = [
    "build_local_selected_slides",
    "compute_audio_fade",
    "compute_slide_timing",
    "download_primary_image",
    "download_remote_image",
    "normalize_ber_icon_code",
    "prepare_cover_logo_image",
    "prepare_agent_image",
    "resolve_ber_icon_path",
    "resolve_asset_path",
    "resolve_ffmpeg_binary",
    "resolve_font_path",
    "resolve_manifest_output_path",
    "resolve_reel_output_path",
    "select_reel_images",
    "select_reel_slides",
    "sorted_image_paths",
]

