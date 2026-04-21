from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import shutil
import struct
import zlib
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse
from urllib.request import Request, urlopen

from config import GEMINI_SELECTION_AUDIT_FILENAME
from settings.images import IMAGE_EXTENSIONS, IMAGE_HEADERS
from settings.http import OUTBOUND_HTTP_TIMEOUT_SECONDS
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
_REMOTE_IMAGE_QUERY_FILENAME_KEYS = frozenset({"img", "image", "filename", "file", "src"})
_REMOTE_IMAGE_EXTENSION_CANDIDATES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
    ".avif",
    ".heic",
    ".heif",
    ".jfif",
    ".svg",
)
_REMOTE_IMAGE_EXTENSIONS = frozenset(_REMOTE_IMAGE_EXTENSION_CANDIDATES)
_REMOTE_IMAGE_SUFFIX_BY_CONTENT_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/x-ms-bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/x-tiff": ".tiff",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/svg+xml": ".svg",
}
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
_SUPPORTED_BACKGROUND_AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg"}
)


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


def resolve_background_audio_paths(
    workspace_dir: Path,
    settings: PropertyReelTemplate,
    *,
    shuffle_candidates: bool,
) -> tuple[Path, ...]:
    configured_audio_path = workspace_dir / settings.assets_dirname / settings.background_audio_filename
    audio_directory = configured_audio_path.parent
    if not audio_directory.exists():
        raise ResourceNotFoundError(
            "Background audio directory not found for reel rendering.",
            context={"audio_directory": str(audio_directory)},
            hint=(
                "Ensure the assets/music directory is deployed with the application and contains "
                "at least one readable audio track."
            ),
        )

    candidates = [
        candidate
        for candidate in sorted(audio_directory.iterdir())
        if candidate.is_file() and candidate.suffix.lower() in _SUPPORTED_BACKGROUND_AUDIO_EXTENSIONS
    ]
    if not candidates:
        raise ResourceNotFoundError(
            "No background audio tracks were found for reel rendering.",
            context={"audio_directory": str(audio_directory)},
            hint=(
                "Add at least one readable audio file under assets/music before starting reel generation."
            ),
        )

    if shuffle_candidates and len(candidates) > 1:
        randomized_candidates = list(candidates)
        random.SystemRandom().shuffle(randomized_candidates)
        return tuple(randomized_candidates)
    return tuple(candidates)


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
    request = Request(image_url, headers=IMAGE_HEADERS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    download_token = hashlib.sha1(f"{image_url}|{destination}".encode("utf-8")).hexdigest()[:10]
    temporary_destination = destination.parent / f"{destination.name}.{download_token}.download"

    try:
        with urlopen(request, timeout=OUTBOUND_HTTP_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type")
            content_disposition = response.headers.get("Content-Disposition")
            with temporary_destination.open("wb") as file_handle:
                shutil.copyfileobj(response, file_handle)

        final_destination = _resolve_downloaded_image_destination(
            image_url=image_url,
            requested_destination=destination,
            downloaded_path=temporary_destination,
            content_type=content_type,
            content_disposition=content_disposition,
        )
        if final_destination.exists() and final_destination != temporary_destination:
            final_destination.unlink(missing_ok=True)
        temporary_destination.replace(final_destination)
        return final_destination
    except Exception:
        temporary_destination.unlink(missing_ok=True)
        raise


def download_primary_image(primary_image_url: str, destination: Path) -> Path:
    return download_remote_image(primary_image_url, destination)


def _normalize_image_basename(image_reference: str | None) -> str | None:
    normalized_reference = str(image_reference or "").strip()
    if not normalized_reference:
        return None

    basename = _resolve_remote_image_name(normalized_reference).strip().lower()
    return basename or None


def _is_duplicate_agent_and_agency_image(property_data: PropertyRenderData) -> bool:
    agent_photo_basename = _normalize_image_basename(property_data.agent_photo_url)
    agency_logo_basename = _normalize_image_basename(property_data.agency_logo_url)
    return bool(
        agent_photo_basename
        and agency_logo_basename
        and agent_photo_basename == agency_logo_basename
    )


def should_reserve_agency_logo_space(
    property_data: PropertyRenderData,
    *,
    cover_logo_path: Path | None = None,
) -> bool:
    return cover_logo_path is not None or _is_duplicate_agent_and_agency_image(property_data)


def prepare_cover_logo_image(
    workspace_dir: Path,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    *,
    suppress_if_duplicate: bool = True,
) -> Path | None:
    agency_logo_url = str(property_data.agency_logo_url or "").strip()
    if not agency_logo_url:
        return None
    if suppress_if_duplicate and _is_duplicate_agent_and_agency_image(property_data):
        logger.info(
            "Skipping agency logo for property %s (%s) because it matches the agent photo filename.",
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
    existing_destination = _find_existing_remote_image(destination)
    if existing_destination is not None:
        return existing_destination

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
    temp_dir.mkdir(parents=True, exist_ok=True)
    if not property_data.agent_photo_url:
        agency_logo_path = prepare_cover_logo_image(
            workspace_dir,
            property_data,
            settings,
            suppress_if_duplicate=False,
        )
        if agency_logo_path is not None:
            return agency_logo_path
        return _write_transparent_placeholder(temp_dir / "agent_placeholder.png")

    suffix = _resolve_remote_image_suffix(property_data.agent_photo_url)
    destination = temp_dir / f"agent_photo{suffix}"
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
        agency_logo_path = prepare_cover_logo_image(
            workspace_dir,
            property_data,
            settings,
            suppress_if_duplicate=False,
        )
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
    suffix = _normalize_remote_image_suffix(Path(_resolve_remote_image_name(image_url)).suffix)
    if suffix is not None:
        return suffix
    return ".png"


def _resolve_remote_image_name(image_url: str) -> str:
    parsed_url = urlparse(image_url)
    query_pairs = parse_qsl(parsed_url.query, keep_blank_values=False)

    for key, value in query_pairs:
        if key.lower() not in _REMOTE_IMAGE_QUERY_FILENAME_KEYS:
            continue
        basename = Path(unquote(value)).name.strip()
        if basename:
            return basename

    path_basename = Path(unquote(parsed_url.path)).name.strip()
    if path_basename:
        return path_basename
    return image_url.strip()


def _resolve_downloaded_image_destination(
    *,
    image_url: str,
    requested_destination: Path,
    downloaded_path: Path,
    content_type: str | None,
    content_disposition: str | None,
) -> Path:
    resolved_suffix = _resolve_downloaded_image_suffix(
        image_url=image_url,
        downloaded_path=downloaded_path,
        content_type=content_type,
        content_disposition=content_disposition,
        fallback_suffix=requested_destination.suffix,
    )
    current_suffix = _normalize_remote_image_suffix(requested_destination.suffix)
    if current_suffix == resolved_suffix:
        return requested_destination
    if requested_destination.suffix:
        return requested_destination.with_suffix(resolved_suffix)
    return requested_destination.with_name(f"{requested_destination.name}{resolved_suffix}")


def _resolve_downloaded_image_suffix(
    *,
    image_url: str,
    downloaded_path: Path,
    content_type: str | None,
    content_disposition: str | None,
    fallback_suffix: str | None,
) -> str:
    sniffed_suffix = _sniff_downloaded_image_suffix(downloaded_path)
    if _is_probably_non_image_response(content_type, sniffed_suffix):
        raise ValueError(
            f"Remote image download for {image_url!r} did not return an image response."
        )

    content_disposition_filename = _resolve_content_disposition_filename(content_disposition)
    candidates = (
        sniffed_suffix,
        _normalize_remote_image_suffix(Path(content_disposition_filename or "").suffix),
        _suffix_from_content_type(content_type),
        _normalize_remote_image_suffix(Path(_resolve_remote_image_name(image_url)).suffix),
        _normalize_remote_image_suffix(fallback_suffix),
    )
    for candidate in candidates:
        if candidate is not None:
            return candidate
    return ".png"


def _resolve_content_disposition_filename(content_disposition: str | None) -> str | None:
    if not content_disposition:
        return None

    encoded_match = re.search(r"filename\*\s*=\s*(?:UTF-8''|utf-8'')?([^;]+)", content_disposition)
    if encoded_match is not None:
        filename = unquote(encoded_match.group(1).strip().strip('"'))
        resolved = Path(filename).name.strip()
        return resolved or None

    plain_match = re.search(r'filename\s*=\s*"?(?P<filename>[^";]+)"?', content_disposition)
    if plain_match is not None:
        filename = unquote(plain_match.group("filename").strip())
        resolved = Path(filename).name.strip()
        return resolved or None
    return None


def _suffix_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    normalized_content_type = content_type.split(";", 1)[0].strip().lower()
    return _REMOTE_IMAGE_SUFFIX_BY_CONTENT_TYPE.get(normalized_content_type)


def _normalize_remote_image_suffix(suffix: str | None) -> str | None:
    normalized_suffix = str(suffix or "").strip().lower()
    if not normalized_suffix:
        return None
    if not normalized_suffix.startswith("."):
        normalized_suffix = f".{normalized_suffix}"
    if normalized_suffix == ".jpe":
        normalized_suffix = ".jpg"
    if normalized_suffix in _REMOTE_IMAGE_EXTENSIONS or normalized_suffix in IMAGE_EXTENSIONS:
        return normalized_suffix
    return None


def _sniff_downloaded_image_suffix(downloaded_path: Path) -> str | None:
    try:
        header = downloaded_path.read_bytes()[:4096]
    except OSError:
        return None
    if not header:
        return None

    stripped_header = header.lstrip()
    if stripped_header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if header.startswith(b"BM"):
        return ".bmp"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand in {b"avif", b"avis"}:
            return ".avif"
        if brand in {b"heic", b"heix", b"hevc", b"hevx"}:
            return ".heic"
        if brand in {b"mif1", b"msf1"}:
            return ".heif"
    lowered_text = stripped_header[:512].lower()
    if b"<svg" in lowered_text:
        return ".svg"
    return None


def _is_probably_non_image_response(content_type: str | None, sniffed_suffix: str | None) -> bool:
    if sniffed_suffix is not None:
        return False
    if not content_type:
        return False
    normalized_content_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_content_type.startswith("image/"):
        return False
    return normalized_content_type not in {
        "application/octet-stream",
        "binary/octet-stream",
        "application/binary",
    }


def _find_existing_remote_image(destination: Path) -> Path | None:
    candidates: list[Path] = [destination]
    candidates.extend(sorted(destination.parent.glob(f"{destination.stem}.*")))
    seen_candidates: set[Path] = set()
    for candidate in candidates:
        if candidate in seen_candidates:
            continue
        seen_candidates.add(candidate)
        if (
            candidate.exists()
            and candidate.is_file()
            and candidate.stat().st_size > 0
            and _normalize_remote_image_suffix(candidate.suffix) is not None
        ):
            return candidate
    return None


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
    "resolve_background_audio_paths",
    "resolve_ffmpeg_binary",
    "resolve_font_path",
    "resolve_manifest_output_path",
    "resolve_reel_output_path",
    "select_reel_images",
    "select_reel_slides",
    "should_reserve_agency_logo_space",
    "sorted_image_paths",
]

