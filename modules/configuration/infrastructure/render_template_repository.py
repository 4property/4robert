"""Persistence for DB-backed render template catalog packs."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from modules.configuration.domain import RenderTemplate, RenderTemplatePreviewImage
from modules.configuration.infrastructure.repository_helpers import (
    isoformat,
    jsonb_to_mapping,
)
from shared.db.repository_base import ModuleRepository


def _jsonb_to_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, tuple):
        return list(raw)
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else []
    return list(raw)


def _preview_images(raw: Any) -> tuple[RenderTemplatePreviewImage, ...]:
    items: list[RenderTemplatePreviewImage] = []
    for item in _jsonb_to_list(raw):
        if not isinstance(item, dict):
            continue
        image_url = str(item.get("image_url") or "").strip()
        if not image_url:
            continue
        items.append(
            RenderTemplatePreviewImage(
                kind=str(item.get("kind") or "").strip() or "preview",
                image_url=image_url,
                alt=str(item.get("alt") or "").strip(),
            )
        )
    return tuple(items)


def _row_to_template(row) -> RenderTemplate:
    return RenderTemplate(
        template_id=str(row.template_id or ""),
        display_name=str(row.display_name or ""),
        description=str(row.description or ""),
        status=str(row.status or ""),
        sort_order=int(row.sort_order or 0),
        preview_images=_preview_images(row.preview_images),
        layout_variant=str(row.layout_variant or "classic"),
        reel_settings=jsonb_to_mapping(row.reel_settings),
        poster_settings=jsonb_to_mapping(row.poster_settings),
        created_at=isoformat(row.created_at) or "",
        updated_at=isoformat(row.updated_at) or "",
    )


_RENDER_TEMPLATE_COLUMNS = (
    "template_id, display_name, description, status, sort_order, "
    "preview_images, layout_variant, reel_settings, poster_settings, "
    "created_at, updated_at"
)


class RenderTemplateRepository(ModuleRepository):
    def get(self, template_id: str) -> RenderTemplate | None:
        row = self.session.execute(
            text(
                f"SELECT {_RENDER_TEMPLATE_COLUMNS} FROM render_templates "
                "WHERE template_id = :template_id"
            ),
            {"template_id": str(template_id or "").strip()},
        ).first()
        return _row_to_template(row) if row is not None else None

    def list_all(self) -> tuple[RenderTemplate, ...]:
        rows = self.session.execute(
            text(
                f"SELECT {_RENDER_TEMPLATE_COLUMNS} FROM render_templates "
                "ORDER BY sort_order ASC, display_name ASC, template_id ASC"
            )
        ).all()
        return tuple(_row_to_template(row) for row in rows)

    def get_selectable(self, template_id: str) -> RenderTemplate | None:
        template = self.get(template_id)
        if template is None or not template.is_selectable:
            return None
        return template


__all__ = ["RenderTemplateRepository"]
