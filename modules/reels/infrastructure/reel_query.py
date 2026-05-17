"""Cross-aggregate read model for the admin "Reels" view.

Joins `properties` (catalog), `reels` (this module) and the latest
`media_revisions` row to deliver one record per reel for the admin UI. This
is a pure read; writes always go through the per-aggregate repositories.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from shared.db.repository_base import ModuleRepository


def _build_filter_clause(
    *,
    workflow_state: tuple[str, ...] | None,
    publish_status: tuple[str, ...] | None,
    q: str | None,
) -> tuple[str, dict[str, Any]]:
    """Build the shared WHERE fragment + bound params for list/count queries.

    The same predicate must run in both ``list_recent_for_agency`` and
    ``count_for_agency`` so the page totals stay consistent with the page
    body. The agency scoping (``p.agency_id = :agency_id``) is appended
    by the caller, not by this helper.
    """
    fragments: list[str] = []
    params: dict[str, Any] = {}
    if workflow_state:
        placeholders = ", ".join(
            f":workflow_state_{idx}" for idx in range(len(workflow_state))
        )
        fragments.append(f"r.workflow_state IN ({placeholders})")
        for idx, value in enumerate(workflow_state):
            params[f"workflow_state_{idx}"] = str(value)
    if publish_status:
        placeholders = ", ".join(
            f":publish_status_{idx}" for idx in range(len(publish_status))
        )
        fragments.append(f"r.publish_status IN ({placeholders})")
        for idx, value in enumerate(publish_status):
            params[f"publish_status_{idx}"] = str(value)
    if q:
        # Three-column ILIKE over the columns a real-estate user actually
        # types when looking for a reel: the reel title, the URL-safe
        # slug, and the property reference (``properties.list_reference``,
        # the human reference printed on the listing). ``q`` is already
        # trimmed by the router; we add the wildcards here so the bound
        # parameter carries the exact pattern.
        fragments.append(
            "(p.title ILIKE :q_pattern "
            "OR p.slug ILIKE :q_pattern "
            "OR p.list_reference ILIKE :q_pattern)"
        )
        params["q_pattern"] = f"%{q}%"
    clause = " AND ".join(fragments)
    return clause, params


def _isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _deserialize_text_tuple(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return ()
        if text_value.startswith("[") and text_value.endswith("]"):
            try:
                parsed = json.loads(text_value)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return _deserialize_text_tuple(parsed)
        return (text_value,)
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            items.extend(_deserialize_text_tuple(item))
        return tuple(items)
    text_value = str(value).strip()
    return (text_value,) if text_value else ()


@dataclass(slots=True)
class AgencyReelSummary:
    external_source_id: str
    source_property_id: int
    slug: str
    title: str | None
    link: str | None
    price: str | None
    property_status: str | None
    property_type_label: str | None
    property_area_label: str | None
    property_county_label: str | None
    bedrooms: int | None
    bathrooms: int | None
    featured_image_url: str | None
    agent_name: str | None
    workflow_state: str
    publish_status: str
    render_status: str
    last_published_provider_external_id: str
    pipeline_updated_at: str
    pipeline_created_at: str
    fetched_at: str
    current_revision_id: str
    revision_media_path: str
    revision_metadata_path: str
    revision_artifact_kind: str
    revision_created_at: str


@dataclass(slots=True)
class PropertyReelRecord:
    external_source_id: str
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


_REEL_SELECT_COLUMNS = ", ".join(
    (
        "p.external_source_id AS external_source_id",
        "p.source_property_id AS source_property_id",
        "p.slug AS slug",
        "p.title AS title",
        "p.link AS link",
        "p.featured_image_url AS featured_image_url",
        "p.bedrooms AS bedrooms",
        "p.bathrooms AS bathrooms",
        "p.ber_rating AS ber_rating",
        "p.property_status AS property_status",
        "p.agent_name AS agent_name",
        "p.agent_photo_url AS agent_photo_url",
        "p.agent_email AS agent_email",
        "p.agent_mobile AS agent_mobile",
        "p.agent_number AS agent_number",
        "p.agency_psra AS agency_psra",
        "p.agency_logo_url AS agency_logo_url",
        "p.price AS price",
        "p.price_term AS price_term",
        "p.property_type_label AS property_type_label",
        "p.property_area_label AS property_area_label",
        "p.property_county_label AS property_county_label",
        "p.property_size AS property_size",
        "p.eircode AS eircode",
        "p.viewing_times AS viewing_times",
        "r.selected_image_folder AS selected_image_folder",
        "r.artifact_kind AS artifact_kind",
        "r.local_artifact_path AS local_artifact_path",
        "r.local_metadata_path AS local_metadata_path",
        "r.render_profile AS render_profile",
        "r.local_manifest_path AS local_manifest_path",
        "r.local_video_path AS local_video_path",
    )
)


class ReelQuery(ModuleRepository):
    """Read-only JOIN reader. Lives in the reels module (not catalog) because
    `reels` is the central aggregate the admin UI navigates."""

    def list_recent_for_agency(
        self,
        *,
        agency_id: str,
        limit: int = 50,
        offset: int = 0,
        workflow_state: tuple[str, ...] | None = None,
        publish_status: tuple[str, ...] | None = None,
        q: str | None = None,
    ) -> tuple[AgencyReelSummary, ...]:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return ()
        filter_clause, filter_params = _build_filter_clause(
            workflow_state=workflow_state,
            publish_status=publish_status,
            q=q,
        )
        where_sql = "WHERE p.agency_id = :agency_id"
        if filter_clause:
            where_sql = f"{where_sql} AND {filter_clause}"
        params: dict[str, Any] = {
            "agency_id": normalized_agency_id,
            "limit": int(max(1, min(limit, 500))),
            "offset": int(max(0, offset)),
            **filter_params,
        }
        rows = self.session.execute(
            text(
                "SELECT p.external_source_id, p.source_property_id, p.slug, "
                "p.title, p.link, p.price, p.property_status, "
                "p.property_type_label, p.property_area_label, "
                "p.property_county_label, p.bedrooms, p.bathrooms, "
                "p.featured_image_url, p.agent_name, p.fetched_at, "
                "r.workflow_state, r.publish_status, r.render_status, "
                "r.last_published_provider_external_id, r.current_revision_id, "
                "r.created_at AS pipeline_created_at, "
                "r.updated_at AS pipeline_updated_at, "
                "mr.media_path AS revision_media_path, "
                "mr.metadata_path AS revision_metadata_path, "
                "mr.artifact_kind AS revision_artifact_kind, "
                "mr.created_at AS revision_created_at "
                "FROM properties AS p "
                "LEFT JOIN reels AS r "
                "  ON r.external_source_id = p.external_source_id "
                "  AND r.source_property_id = p.source_property_id "
                "LEFT JOIN LATERAL ("
                "  SELECT * FROM media_revisions m "
                "  WHERE m.external_source_id = p.external_source_id "
                "  AND m.source_property_id = p.source_property_id "
                "  ORDER BY m.created_at DESC LIMIT 1"
                ") AS mr ON TRUE "
                f"{where_sql} "
                "ORDER BY r.updated_at DESC NULLS LAST, p.fetched_at DESC NULLS LAST "
                "LIMIT :limit OFFSET :offset"
            ),
            params,
        ).all()
        return tuple(
            AgencyReelSummary(
                external_source_id=str(row.external_source_id or ""),
                source_property_id=int(row.source_property_id or 0),
                slug=str(row.slug or ""),
                title=row.title,
                link=row.link,
                price=row.price,
                property_status=row.property_status,
                property_type_label=row.property_type_label,
                property_area_label=row.property_area_label,
                property_county_label=row.property_county_label,
                bedrooms=row.bedrooms,
                bathrooms=row.bathrooms,
                featured_image_url=row.featured_image_url,
                agent_name=row.agent_name,
                workflow_state=str(row.workflow_state or ""),
                publish_status=str(row.publish_status or ""),
                render_status=str(row.render_status or ""),
                last_published_provider_external_id=str(
                    row.last_published_provider_external_id or ""
                ),
                pipeline_updated_at=_isoformat(row.pipeline_updated_at) or "",
                pipeline_created_at=_isoformat(row.pipeline_created_at) or "",
                fetched_at=_isoformat(row.fetched_at) or "",
                current_revision_id=str(row.current_revision_id or ""),
                revision_media_path=str(row.revision_media_path or ""),
                revision_metadata_path=str(row.revision_metadata_path or ""),
                revision_artifact_kind=str(row.revision_artifact_kind or ""),
                revision_created_at=_isoformat(row.revision_created_at) or "",
            )
            for row in rows
        )

    def count_for_agency(
        self,
        *,
        agency_id: str,
        workflow_state: tuple[str, ...] | None = None,
        publish_status: tuple[str, ...] | None = None,
        q: str | None = None,
    ) -> int:
        """Total rows that satisfy the same WHERE as ``list_recent_for_agency``.

        The two queries share ``_build_filter_clause`` so a request always
        gets a count that matches the body it received. The JOIN on
        ``reels`` stays a LEFT JOIN so the IN-list filters still match
        properties whose ``reels`` row has the matching value — and so
        rows without a ``reels`` row are excluded when a workflow/publish
        filter is set (the JOINed value is ``NULL`` and ``NULL IN (...)``
        is false).
        """
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return 0
        filter_clause, filter_params = _build_filter_clause(
            workflow_state=workflow_state,
            publish_status=publish_status,
            q=q,
        )
        where_sql = "WHERE p.agency_id = :agency_id"
        if filter_clause:
            where_sql = f"{where_sql} AND {filter_clause}"
        params: dict[str, Any] = {
            "agency_id": normalized_agency_id,
            **filter_params,
        }
        row = self.session.execute(
            text(
                "SELECT COUNT(*) AS total "
                "FROM properties AS p "
                "LEFT JOIN reels AS r "
                "  ON r.external_source_id = p.external_source_id "
                "  AND r.source_property_id = p.source_property_id "
                f"{where_sql}"
            ),
            params,
        ).first()
        if row is None:
            return 0
        return int(row.total or 0)

    def get_property_reel_record(
        self,
        *,
        external_source_id: str,
        property_id: int | None = None,
        slug: str | None = None,
    ) -> PropertyReelRecord | None:
        if property_id is not None:
            row = self.session.execute(
                text(
                    f"SELECT {_REEL_SELECT_COLUMNS} FROM properties AS p "
                    "LEFT JOIN reels AS r "
                    "  ON r.external_source_id = p.external_source_id "
                    "  AND r.source_property_id = p.source_property_id "
                    "WHERE p.external_source_id = :id "
                    "AND p.source_property_id = :property_id"
                ),
                {"id": external_source_id, "property_id": property_id},
            ).first()
        elif slug is not None:
            row = self.session.execute(
                text(
                    f"SELECT {_REEL_SELECT_COLUMNS} FROM properties AS p "
                    "LEFT JOIN reels AS r "
                    "  ON r.external_source_id = p.external_source_id "
                    "  AND r.source_property_id = p.source_property_id "
                    "WHERE p.external_source_id = :id AND p.slug = :slug"
                ),
                {"id": external_source_id, "slug": slug},
            ).first()
        else:
            row = self.session.execute(
                text(
                    f"SELECT {_REEL_SELECT_COLUMNS} FROM properties AS p "
                    "LEFT JOIN reels AS r "
                    "  ON r.external_source_id = p.external_source_id "
                    "  AND r.source_property_id = p.source_property_id "
                    "WHERE p.external_source_id = :id "
                    "AND COALESCE(r.selected_image_folder, '') != '' "
                    "ORDER BY p.fetched_at DESC LIMIT 1"
                ),
                {"id": external_source_id},
            ).first()

        if row is None:
            return None
        return PropertyReelRecord(
            external_source_id=str(row.external_source_id),
            property_id=int(row.source_property_id),
            slug=str(row.slug),
            title=None if row.title is None else str(row.title),
            link=None if row.link is None else str(row.link),
            selected_image_folder=str(row.selected_image_folder or ""),
            local_manifest_path=str(row.local_manifest_path or ""),
            local_video_path=str(row.local_video_path or ""),
            featured_image_url=(
                None if row.featured_image_url is None else str(row.featured_image_url)
            ),
            bedrooms=None if row.bedrooms is None else int(row.bedrooms),
            bathrooms=None if row.bathrooms is None else int(row.bathrooms),
            ber_rating=None if row.ber_rating is None else str(row.ber_rating),
            property_status=(
                None if row.property_status is None else str(row.property_status)
            ),
            agent_name=None if row.agent_name is None else str(row.agent_name),
            agent_photo_url=(
                None if row.agent_photo_url is None else str(row.agent_photo_url)
            ),
            agent_email=None if row.agent_email is None else str(row.agent_email),
            agent_mobile=None if row.agent_mobile is None else str(row.agent_mobile),
            agent_number=None if row.agent_number is None else str(row.agent_number),
            agency_psra=None if row.agency_psra is None else str(row.agency_psra),
            agency_logo_url=(
                None if row.agency_logo_url is None else str(row.agency_logo_url)
            ),
            price=None if row.price is None else str(row.price),
            price_term=None if row.price_term is None else str(row.price_term),
            property_type_label=(
                None
                if row.property_type_label is None
                else str(row.property_type_label)
            ),
            property_area_label=(
                None
                if row.property_area_label is None
                else str(row.property_area_label)
            ),
            property_county_label=(
                None
                if row.property_county_label is None
                else str(row.property_county_label)
            ),
            property_size=None if row.property_size is None else str(row.property_size),
            eircode=None if row.eircode is None else str(row.eircode),
            viewing_times=_deserialize_text_tuple(row.viewing_times),
            artifact_kind=str(row.artifact_kind or ""),
            local_artifact_path=str(row.local_artifact_path or ""),
            local_metadata_path=str(row.local_metadata_path or ""),
            render_profile=str(row.render_profile or ""),
        )


__all__ = ["AgencyReelSummary", "PropertyReelRecord", "ReelQuery"]
