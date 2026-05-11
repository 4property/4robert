"""Catalog row value objects.

Thin DB-backed value objects the modern repositories convert from ORM rows.
The rich WordPress-payload aggregate (``Property``) lives next to them in
``wordpress_property.py``; both share the same bounded context.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogProperty:
    record_id: int
    agency_id: str
    ingestion_source_id: str
    external_source_id: str
    source_property_id: int
    slug: str
    title: str | None
    raw_json: str
    fetched_at: str | None


@dataclass(frozen=True, slots=True)
class CatalogPropertyImage:
    record_id: int
    position: int
    image_url: str
    local_path: str | None


@dataclass(slots=True)
class PropertySyncState:
    modified_gmt: str | None
    raw_json: str
    image_folder: str
    social_publish_status: str


__all__ = ["CatalogProperty", "CatalogPropertyImage", "PropertySyncState"]
