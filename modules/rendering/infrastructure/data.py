"""Property reel record + load_property_reel_data legacy stub.

Migrated from ``services/media/reel_rendering/data.py`` during sub-feature
18c. ``PropertyReelRecord`` is the inline replacement for the retired
``repositories.stores.property_store`` dataclass kept while
``build_tiktok_description_for_record`` and other legacy callers still
exist in publishing copy paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from settings import DATABASE_URL
from shared.errors import PropertyReelError
from modules.rendering.infrastructure.formatting import clean_text
from modules.rendering.infrastructure.models import PropertyRenderData
from modules.rendering.infrastructure.runtime import build_local_selected_slides


@dataclass(slots=True)
class PropertyReelRecord:
    """Inline replacement for the legacy ``repositories.stores.property_store``
    dataclass. Kept to honour the legacy production ``load_property_reel_data``
    path until the modern reel pipeline (uow.catalog.properties +
    uow.reels.queries) replaces every caller."""

    site_id: str
    property_id: int
    slug: str
    title: str | None
    link: str | None
    selected_image_folder: str
    local_manifest_path: str
    local_video_path: str
    featured_image_url: str | None
    bedrooms: int | None
    bathrooms: int | None
    ber_rating: str | None
    property_status: str | None
    agent_name: str | None
    agent_photo_url: str | None
    agent_email: str | None
    agent_mobile: str | None
    agent_number: str | None
    agency_psra: str | None
    agency_logo_url: str | None
    price: str | None
    price_term: str | None
    property_type_label: str | None
    property_area_label: str | None
    property_county_label: str | None
    property_size: str | None
    eircode: str | None
    viewing_times: tuple[str, ...]
    artifact_kind: str
    local_artifact_path: str
    local_metadata_path: str
    render_profile: str


def record_to_property_reel_data(base_dir: Path, record: PropertyReelRecord) -> PropertyRenderData:
    image_folder = Path(record.selected_image_folder)
    selected_image_dir = (base_dir / image_folder).resolve()
    selected_image_paths = tuple(
        path
        for path in sorted(selected_image_dir.iterdir())
        if path.is_file()
    ) if selected_image_dir.exists() else ()
    selected_slides = build_local_selected_slides(
        selected_image_dir,
        selected_image_paths,
    )
    return PropertyRenderData(
        site_id=record.site_id,
        property_id=record.property_id,
        slug=record.slug,
        title=clean_text(record.title) or record.slug,
        link=clean_text(record.link),
        property_status=clean_text(record.property_status),
        listing_lifecycle=None,
        banner_text=clean_text(record.property_status),
        selected_image_dir=selected_image_dir,
        selected_image_paths=selected_image_paths,
        featured_image_url=clean_text(record.featured_image_url),
        bedrooms=record.bedrooms,
        bathrooms=record.bathrooms,
        ber_rating=clean_text(record.ber_rating),
        agent_name=clean_text(record.agent_name),
        agent_photo_url=clean_text(record.agent_photo_url),
        agent_email=clean_text(record.agent_email),
        agent_mobile=clean_text(record.agent_mobile),
        agent_number=clean_text(record.agent_number),
        agency_psra=clean_text(record.agency_psra),
        agency_logo_url=clean_text(record.agency_logo_url),
        price=clean_text(record.price),
        price_display_text=clean_text(record.price),
        property_type_label=clean_text(record.property_type_label),
        property_area_label=clean_text(record.property_area_label),
        property_county_label=clean_text(record.property_county_label),
        eircode=clean_text(record.eircode),
        property_size=clean_text(record.property_size),
        viewing_times=record.viewing_times,
        selected_slides=selected_slides,
    )


def load_property_reel_data(
    base_dir: str | Path,
    *,
    site_id: str,
    property_id: int | None = None,
    slug: str | None = None,
    database_locator: str | Path | None = DATABASE_URL,
) -> PropertyRenderData:
    del base_dir, site_id, property_id, slug, database_locator
    raise PropertyReelError(
        "Legacy standalone render entry point has been retired.",
        hint=(
            "Use the modern reel pipeline (uow.catalog.properties + "
            "uow.reels.queries) instead of the legacy property-reel data loader."
        ),
    )


__all__ = [
    "PropertyReelRecord",
    "load_property_reel_data",
    "record_to_property_reel_data",
]
