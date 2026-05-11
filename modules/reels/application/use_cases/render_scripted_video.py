"""Render scripted video use case."""

from __future__ import annotations

from pathlib import Path

from modules.delivery.domain import Job


class RenderScriptedVideoUseCase:
    def __init__(
        self,
        *,
        workspace_dir: str | Path,
        database_locator: str | Path | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.database_locator = database_locator
        self._service: object | None = None

    def execute(self, job: Job) -> object | None:
        if self._service is None:
            from modules.rendering.application.scripted_video.render_service import (
                ScriptedVideoRenderService,
            )
            from shared.db.uow_factory import build_runtime_unit_of_work_factory

            self._service = ScriptedVideoRenderService(
                self.workspace_dir,
                unit_of_work_factory=build_runtime_unit_of_work_factory(
                    self.workspace_dir,
                    database_locator=self.database_locator,
                ),
            )

        payload = dict(job.payload)
        payload.setdefault("site_id", job.external_source_id)
        if job.property_id is not None:
            payload.setdefault("source_property_id", job.property_id)
        render_from_manifest = getattr(self._service, "render_from_manifest")
        return render_from_manifest(payload)


__all__ = ["RenderScriptedVideoUseCase"]
