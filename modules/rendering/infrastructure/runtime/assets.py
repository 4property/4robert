"""Rendering runtime asset resolution and remote image helpers."""

from __future__ import annotations

import hashlib
import logging
import random
import re
import shutil
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from modules.rendering.infrastructure.models import PropertyReelTemplate
from shared.storage.site_layout import safe_site_dirname
from settings.http import OUTBOUND_HTTP_TIMEOUT_SECONDS
from settings.images import IMAGE_EXTENSIONS, IMAGE_HEADERS
from shared.errors import ResourceNotFoundError
from shared.observability import require_dependency

logger = logging.getLogger(__name__)

BRANDING_CACHE_DIRNAME = "_branding"
VALID_BER_ICON_CODES = {
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
SUPPORTED_BACKGROUND_AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg"}
)
REMOTE_IMAGE_RETRY_STATUS_CODES = frozenset({403, 406})
RELAXED_REMOTE_IMAGE_HEADERS = {
    "Accept": "*/*",
    "User-Agent": IMAGE_HEADERS.get("User-Agent", "Mozilla/5.0 (compatible; CPIHED/1.0)"),
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
        project_relative_path = Path(__file__).resolve().parents[4] / path
        if project_relative_path.exists():
            return project_relative_path
    raise ResourceNotFoundError(
        "Font file not found for reel subtitle rendering.",
        context={"requested_path": str(path)},
        hint=(
            "Set REEL_SUBTITLE_FONT_PATH to a readable .ttf font and ensure "
            "the font file is present on the deployed host."
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
            "Ensure the assets directory is deployed with the application and "
            "that the service user can read the referenced file."
        ),
    )


def resolve_background_audio_paths(
    workspace_dir: Path,
    settings: PropertyReelTemplate,
    *,
    shuffle_candidates: bool,
) -> tuple[Path, ...]:
    configured_audio_path = (
        workspace_dir / settings.assets_dirname / settings.background_audio_filename
    )
    audio_directory = configured_audio_path.parent
    if not audio_directory.exists():
        raise ResourceNotFoundError(
            "Background audio directory not found for reel rendering.",
            context={"audio_directory": str(audio_directory)},
            hint=(
                "Ensure the assets/music directory is deployed with the application "
                "and contains at least one readable audio track."
            ),
        )

    candidates = [
        candidate
        for candidate in sorted(audio_directory.iterdir())
        if candidate.is_file()
        and candidate.suffix.lower() in SUPPORTED_BACKGROUND_AUDIO_EXTENSIONS
    ]
    if not candidates:
        raise ResourceNotFoundError(
            "No background audio tracks were found for reel rendering.",
            context={"audio_directory": str(audio_directory)},
            hint="Add at least one readable audio file under assets/music first.",
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
    if cleaned in VALID_BER_ICON_CODES:
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

    logger.warning("BER icon for rating %s was not found at %s.", normalized_code, icon_path)
    return None


def download_remote_image(image_url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request_headers = (IMAGE_HEADERS, RELAXED_REMOTE_IMAGE_HEADERS)
    last_error: HTTPError | None = None

    for attempt_index, headers in enumerate(request_headers):
        request = Request(image_url, headers=headers)
        try:
            with urlopen(request, timeout=OUTBOUND_HTTP_TIMEOUT_SECONDS) as response:
                with destination.open("wb") as file_handle:
                    shutil.copyfileobj(response, file_handle)
            return destination
        except HTTPError as error:
            last_error = error
            if attempt_index == 0 and error.code in REMOTE_IMAGE_RETRY_STATUS_CODES:
                continue
            raise

    if last_error is not None:
        raise last_error
    return destination


def download_primary_image(primary_image_url: str, destination: Path) -> Path:
    return download_remote_image(primary_image_url, destination)


def resolve_cached_branding_destination(
    *,
    workspace_dir: Path,
    site_id: str,
    slug: str,
    image_url: str,
    label: str,
) -> Path:
    branding_dir = (
        workspace_dir / "generated_media" / safe_site_dirname(site_id) / BRANDING_CACHE_DIRNAME
    )
    branding_dir.mkdir(parents=True, exist_ok=True)
    suffix = resolve_remote_image_suffix(image_url)
    image_hash = hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:12]
    return branding_dir / f"{slug}-{label}-{image_hash}{suffix}"


def resolve_remote_image_suffix(image_url: str) -> str:
    basename = resolve_remote_image_basename(image_url)
    suffix = Path(basename or "").suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix

    parsed_path = urlparse(image_url).path
    suffix = Path(parsed_path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    return ".png"


def has_explicit_unsupported_image_suffix(image_url: str) -> bool:
    if resolve_remote_image_suffix(image_url) in IMAGE_EXTENSIONS:
        return False

    parsed_path = urlparse(image_url).path
    suffix = Path(parsed_path).suffix.lower()
    return bool(suffix) and suffix not in IMAGE_EXTENSIONS


def resolve_remote_image_basename(image_reference: str | None) -> str | None:
    normalized_reference = str(image_reference or "").strip()
    if not normalized_reference:
        return None

    parsed_reference = urlparse(normalized_reference)
    for candidate in iter_remote_image_name_candidates(parsed_reference, normalized_reference):
        basename = Path(candidate).name.strip()
        if basename and Path(basename).suffix.lower() in IMAGE_EXTENSIONS:
            return basename

    fallback_basename = Path(parsed_reference.path or normalized_reference).name.strip()
    return fallback_basename or None


def iter_remote_image_name_candidates(parsed_reference, original_reference: str) -> list[str]:
    candidates: list[str] = []
    if parsed_reference.path:
        candidates.append(parsed_reference.path)

    for values in parse_qs(parsed_reference.query, keep_blank_values=False).values():
        for value in values:
            cleaned_value = str(value).strip()
            if not cleaned_value:
                continue
            parsed_value = urlparse(cleaned_value)
            candidate_path = parsed_value.path or cleaned_value
            candidates.append(candidate_path)

    if original_reference not in candidates:
        candidates.append(original_reference)
    return candidates


__all__ = [
    "download_primary_image",
    "download_remote_image",
    "has_explicit_unsupported_image_suffix",
    "normalize_ber_icon_code",
    "resolve_asset_path",
    "resolve_background_audio_paths",
    "resolve_ber_icon_path",
    "resolve_cached_branding_destination",
    "resolve_ffmpeg_binary",
    "resolve_font_path",
    "resolve_remote_image_basename",
    "resolve_remote_image_suffix",
]
