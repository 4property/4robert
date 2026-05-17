"""Persistence for agency intro / outro video assets (feature 33, 34).

Each agency has at most one row per ``(agency_id, kind)`` tuple in
``agency_intro_outro_assets`` (UNIQUE constraint). Today only ``kind =
'outro'`` is exercised — feature 34 will reuse the same table with
``kind = 'intro'``.

``source`` is the discriminator the renderer reads:

* ``'uploaded'`` — concat the binary at ``object_key``.
* ``'brand_card'`` — reserved for a future auto-generated card; the
  renderer must treat this as a no-op today and log a warning.
* ``'none'`` — no asset configured; no concat.

When ``DELETE /v1/admin/agencies/{id}/outro`` is invoked the row is
*reset* rather than deleted: ``object_key`` becomes ``NULL``,
``duration_seconds`` becomes ``NULL`` and ``source`` becomes
``'none'``. The repository's :meth:`reset` method materialises that
transition (it inserts the row when no prior asset existed so the
caller can always read a deterministic shape afterwards).
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from modules.configuration.domain import IntroOutroAsset
from modules.configuration.infrastructure.repository_helpers import isoformat
from shared.db.repository_base import ModuleRepository, utcnow

_ALLOWED_KINDS = frozenset({"intro", "outro"})
_ALLOWED_SOURCES = frozenset({"uploaded", "brand_card", "none"})


def _validate_kind(kind: str) -> str:
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"Unsupported intro/outro kind: {kind!r}")
    return kind


def _validate_source(source: str) -> str:
    if source not in _ALLOWED_SOURCES:
        raise ValueError(f"Unsupported intro/outro source: {source!r}")
    return source


class IntroOutroAssetRepository(ModuleRepository):
    """CRUD for ``agency_intro_outro_assets`` rows."""

    def get(self, *, agency_id: str, kind: str) -> IntroOutroAsset | None:
        _validate_kind(kind)
        row = self.session.execute(
            text(
                "SELECT agency_id, kind, object_key, duration_seconds, source, "
                "created_at, updated_at "
                "FROM agency_intro_outro_assets "
                "WHERE agency_id = :agency_id AND kind = :kind"
            ),
            {"agency_id": agency_id, "kind": kind},
        ).first()
        if row is None:
            return None
        return IntroOutroAsset(
            agency_id=str(row.agency_id),
            kind=str(row.kind),
            object_key=str(row.object_key or ""),
            duration_seconds=int(row.duration_seconds or 0),
            source=str(row.source or "none"),
            created_at=isoformat(row.created_at) or "",
            updated_at=isoformat(row.updated_at) or "",
        )

    def upsert_uploaded(
        self,
        *,
        agency_id: str,
        kind: str,
        object_key: str,
        duration_seconds: int,
    ) -> IntroOutroAsset:
        """Persist (or replace) an uploaded asset for ``(agency_id, kind)``.

        Returns the new row hydrated into an :class:`IntroOutroAsset`.
        The unique constraint ``(agency_id, kind)`` makes ``ON
        CONFLICT`` deterministic: a re-upload overwrites the previous
        ``object_key``/``duration_seconds`` while preserving
        ``created_at`` (so the original onboarding timestamp survives).
        """
        _validate_kind(kind)
        timestamp = utcnow()
        existing = self.get(agency_id=agency_id, kind=kind)
        new_id = str(uuid4())
        params = {
            "id": new_id,
            "agency_id": agency_id,
            "kind": kind,
            "object_key": object_key,
            "duration_seconds": int(duration_seconds),
            "source": "uploaded",
            "created_at": existing.created_at if existing else timestamp,
            "updated_at": timestamp,
        }
        self.session.execute(
            text(
                "INSERT INTO agency_intro_outro_assets ("
                "id, agency_id, kind, object_key, duration_seconds, source, "
                "created_at, updated_at"
                ") VALUES ("
                ":id, :agency_id, :kind, :object_key, :duration_seconds, "
                ":source, :created_at, :updated_at"
                ") ON CONFLICT (agency_id, kind) DO UPDATE SET "
                "object_key = EXCLUDED.object_key, "
                "duration_seconds = EXCLUDED.duration_seconds, "
                "source = EXCLUDED.source, "
                "updated_at = EXCLUDED.updated_at"
            ),
            params,
        )
        result = self.get(agency_id=agency_id, kind=kind)
        assert result is not None
        return result

    def reset_to_none(
        self,
        *,
        agency_id: str,
        kind: str,
    ) -> IntroOutroAsset:
        """Reset the asset for ``(agency_id, kind)`` to source ``'none'``.

        Clears ``object_key`` and ``duration_seconds``. If no row exists
        yet, inserts a fresh ``'none'`` row so the caller can always
        read a deterministic shape after the operation.
        """
        _validate_kind(kind)
        timestamp = utcnow()
        existing = self.get(agency_id=agency_id, kind=kind)
        params = {
            "id": str(uuid4()),
            "agency_id": agency_id,
            "kind": kind,
            "object_key": None,
            "duration_seconds": None,
            "source": "none",
            "created_at": existing.created_at if existing else timestamp,
            "updated_at": timestamp,
        }
        self.session.execute(
            text(
                "INSERT INTO agency_intro_outro_assets ("
                "id, agency_id, kind, object_key, duration_seconds, source, "
                "created_at, updated_at"
                ") VALUES ("
                ":id, :agency_id, :kind, :object_key, :duration_seconds, "
                ":source, :created_at, :updated_at"
                ") ON CONFLICT (agency_id, kind) DO UPDATE SET "
                "object_key = EXCLUDED.object_key, "
                "duration_seconds = EXCLUDED.duration_seconds, "
                "source = EXCLUDED.source, "
                "updated_at = EXCLUDED.updated_at"
            ),
            params,
        )
        result = self.get(agency_id=agency_id, kind=kind)
        assert result is not None
        return result


__all__ = ["IntroOutroAssetRepository"]
