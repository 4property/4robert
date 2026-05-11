"""SQLAlchemy mappings for catalog tables."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base


class PropertyORM(Base):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint(
            "external_source_id",
            "source_property_id",
            name="uq_properties_external_source_property",
        ),
        Index("idx_properties_external_source_slug", "external_source_id", "slug"),
        Index("idx_properties_agency_fetched_at", "agency_id", text("fetched_at DESC")),
    )

    record_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    agency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agencies.id"),
        nullable=False,
    )
    ingestion_source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ingestion_sources.id"),
        nullable=False,
    )
    external_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_property_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    guid: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[int | None] = mapped_column(Integer)
    importer_id: Mapped[str | None] = mapped_column(Text)
    list_reference: Mapped[str | None] = mapped_column(Text)
    date: Mapped[str | None] = mapped_column(Text)
    date_gmt: Mapped[str | None] = mapped_column(Text)
    modified: Mapped[str | None] = mapped_column(Text)
    modified_gmt: Mapped[str | None] = mapped_column(Text)
    excerpt_html: Mapped[str | None] = mapped_column(Text)
    content_html: Mapped[str | None] = mapped_column(Text)
    price: Mapped[str | None] = mapped_column(Text)
    price_sold: Mapped[str | None] = mapped_column(Text)
    price_term: Mapped[str | None] = mapped_column(Text)
    property_status: Mapped[str | None] = mapped_column(Text)
    property_market: Mapped[str | None] = mapped_column(Text)
    property_type_label: Mapped[str | None] = mapped_column(Text)
    property_county_label: Mapped[str | None] = mapped_column(Text)
    property_area_label: Mapped[str | None] = mapped_column(Text)
    property_size: Mapped[str | None] = mapped_column(Text)
    property_land_size: Mapped[str | None] = mapped_column(Text)
    property_accommodation: Mapped[str | None] = mapped_column(Text)
    property_disclaimer: Mapped[str | None] = mapped_column(Text)
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    bathrooms: Mapped[int | None] = mapped_column(Integer)
    ber_rating: Mapped[str | None] = mapped_column(Text)
    ber_number: Mapped[str | None] = mapped_column(Text)
    energy_details: Mapped[str | None] = mapped_column(Text)
    bidding_method: Mapped[str | None] = mapped_column(Text)
    living_type: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    eircode: Mapped[str | None] = mapped_column(Text)
    directions: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    agent_name: Mapped[str | None] = mapped_column(Text)
    agent_photo_url: Mapped[str | None] = mapped_column(Text)
    agent_email: Mapped[str | None] = mapped_column(Text)
    agent_mobile: Mapped[str | None] = mapped_column(Text)
    agent_number: Mapped[str | None] = mapped_column(Text)
    agent_qualification: Mapped[str | None] = mapped_column(Text)
    agency_psra: Mapped[str | None] = mapped_column(Text)
    agency_logo_url: Mapped[str | None] = mapped_column(Text)
    featured_media_id: Mapped[int | None] = mapped_column(Integer)
    featured_image_url: Mapped[str | None] = mapped_column(Text)
    amenities: Mapped[str | None] = mapped_column(Text)
    property_order: Mapped[int | None] = mapped_column(Integer)
    wppd_parent_id: Mapped[str | None] = mapped_column(Text)
    property_type_ids: Mapped[str | None] = mapped_column(Text)
    property_county_ids: Mapped[str | None] = mapped_column(Text)
    property_area_ids: Mapped[str | None] = mapped_column(Text)
    property_features: Mapped[str | None] = mapped_column(Text)
    media_attachments_json: Mapped[str | None] = mapped_column(Text)
    brochure_urls: Mapped[str | None] = mapped_column(Text)
    floorplan_urls: Mapped[str | None] = mapped_column(Text)
    tour_urls: Mapped[str | None] = mapped_column(Text)
    viewing_times: Mapped[str | None] = mapped_column(Text)
    image_folder: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    social_publish_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    social_publish_details_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    raw_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    fetched_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class PropertyImageORM(Base):
    __tablename__ = "property_images"
    __table_args__ = (
        PrimaryKeyConstraint("record_id", "position", name="pk_property_images"),
    )

    record_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("properties.record_id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text)


__all__ = ["PropertyImageORM", "PropertyORM"]
