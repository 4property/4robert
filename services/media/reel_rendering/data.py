from __future__ import annotations

from pathlib import Path

from settings import DATABASE_URL
from core.errors import PropertyReelError, ResourceNotFoundError
from repositories.stores.property_store import PropertyReelRecord, PropertyStore
from services.media.reel_rendering.formatting import clean_text
from services.media.reel_rendering.models import PropertyRenderData
from services.media.reel_rendering.runtime import build_local_selected_slides


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
    workspace_dir = Path(base_dir).expanduser().resolve()
    with PropertyStore(database_locator, workspace_dir) as repository:
        record = repository.get_property_reel_record(
            site_id=site_id,
            property_id=property_id,
            slug=slug,
        )

    if record is None:
        raise PropertyReelError(
            "No property record found for reel generation.",
            context={
                "site_id": site_id,
                "property_id": property_id if property_id is not None else "",
                "slug": slug or "",
            },
            hint="Ensure the property was ingested into PostgreSQL before attempting a standalone render.",
        )

    property_data = record_to_property_reel_data(workspace_dir, record)
    if not property_data.selected_image_dir.exists():
        raise ResourceNotFoundError(
            "Selected photos folder not found for reel generation.",
            context={"selected_image_dir": str(property_data.selected_image_dir)},
            hint=(
                "Run media preparation again or verify the property_media volume is persisted and mounted "
                "correctly in the deployed environment."
            ),
        )
    return property_data


__all__ = ["load_property_reel_data", "record_to_property_reel_data"]

