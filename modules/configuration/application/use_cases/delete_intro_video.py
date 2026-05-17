"""Reset an agency intro asset back to ``source='none'`` and delete blob.

Feature 34: behind ``DELETE /v1/admin/agencies/{agency_id}/intro``.
Symmetric to :mod:`delete_outro_video`. The row in
``agency_intro_outro_assets`` (``kind='intro'``) is reset (not removed)
so the read path always observes a deterministic shape
(``source='none'``, ``object_key=None``, ``duration_seconds=None``).
The on-disk blob is unlinked best-effort.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from modules.configuration.domain import IntroOutroAsset
from shared.db import DatabaseUnitOfWork
from shared.storage.site_layout import resolve_agency_intro_outro_local_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeleteIntroVideoInput:
    agency_id: str


class DeleteIntroVideoUseCase:
    def __init__(self, *, workspace_dir: Path) -> None:
        self._workspace_dir = Path(workspace_dir).expanduser().resolve()

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: DeleteIntroVideoInput,
    ) -> IntroOutroAsset:
        ensure_agency_exists(uow, data.agency_id)
        assert uow.configuration is not None
        previous = uow.configuration.intro_outro_assets.get(
            agency_id=data.agency_id, kind="intro"
        )
        asset = uow.configuration.intro_outro_assets.reset_to_none(
            agency_id=data.agency_id, kind="intro"
        )
        if previous is not None and previous.object_key:
            path = resolve_agency_intro_outro_local_path(
                workspace_dir=self._workspace_dir,
                object_key=previous.object_key,
            )
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:  # pragma: no cover — defensive only
                    logger.exception(
                        "Failed to delete intro blob for agency=%s path=%s",
                        data.agency_id,
                        path,
                    )
        return asset


__all__ = ["DeleteIntroVideoInput", "DeleteIntroVideoUseCase"]
