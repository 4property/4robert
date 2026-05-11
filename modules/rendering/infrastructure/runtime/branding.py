"""Rendering runtime branding image preparation."""

from __future__ import annotations

import logging
import struct
import zlib
from pathlib import Path

from modules.rendering.infrastructure.runtime.assets import (
    download_remote_image,
    has_explicit_unsupported_image_suffix,
    resolve_cached_branding_destination,
    resolve_remote_image_basename,
    resolve_remote_image_suffix,
)
from modules.rendering.infrastructure.models import PropertyRenderData, PropertyReelTemplate

logger = logging.getLogger(__name__)


def normalize_image_basename(image_reference: str | None) -> str | None:
    basename = resolve_remote_image_basename(image_reference)
    return basename.lower() if basename else None


def is_duplicate_agent_and_agency_image(property_data: PropertyRenderData) -> bool:
    agent_photo_basename = normalize_image_basename(property_data.agent_photo_url)
    agency_logo_basename = normalize_image_basename(property_data.agency_logo_url)
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
    return cover_logo_path is not None or is_duplicate_agent_and_agency_image(property_data)


def prepare_cover_logo_image(
    workspace_dir: Path,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    *,
    suppress_if_duplicate: bool = True,
) -> Path | None:
    del settings
    agency_logo_url = str(property_data.agency_logo_url or "").strip()
    if not agency_logo_url:
        return None
    if suppress_if_duplicate and is_duplicate_agent_and_agency_image(property_data):
        logger.info(
            "Skipping agency logo for property %s (%s) because it matches the agent photo filename.",
            property_data.property_id,
            property_data.slug,
        )
        return None
    if has_explicit_unsupported_image_suffix(agency_logo_url):
        logger.warning(
            "Skipping agency logo %r for property %s (%s) because the file extension is not supported.",
            agency_logo_url,
            property_data.property_id,
            property_data.slug,
        )
        return None

    destination = resolve_cached_branding_destination(
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
            "Failed to download agency logo %r for property %s (%s). "
            "Continuing without agency logo. Error: %s",
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
        agency_logo_path = prepare_cover_logo_image(
            workspace_dir,
            property_data,
            settings,
            suppress_if_duplicate=False,
        )
        if agency_logo_path is not None:
            return agency_logo_path
        return write_transparent_placeholder(temp_dir / "agent_placeholder.png")

    suffix = resolve_remote_image_suffix(property_data.agent_photo_url)
    destination = temp_dir / f"agent_photo{suffix}"
    try:
        return download_remote_image(property_data.agent_photo_url, destination)
    except Exception as error:
        logger.warning(
            "Failed to download agent photo %r for property %s (%s). "
            "Continuing with fallback image. Error: %s",
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
        return write_transparent_placeholder(temp_dir / "agent_placeholder.png")


def write_transparent_placeholder(destination: Path) -> Path:
    def chunk(chunk_type: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + chunk_type
            + payload
            + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
        )

    png_payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(png_payload)
    return destination


__all__ = [
    "is_duplicate_agent_and_agency_image",
    "normalize_image_basename",
    "prepare_agent_image",
    "prepare_cover_logo_image",
    "should_reserve_agency_logo_space",
    "write_transparent_placeholder",
]
