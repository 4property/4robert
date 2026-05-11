"""Pydantic payloads for the scripted render router."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ScriptedRenderResponse(BaseModel):
    """Response body for `POST /v1/videos/scripted/render`.

    The endpoint accepts the manifest and enqueues a `scripted_render` job;
    the actual ffmpeg rendering happens asynchronously in the worker. Clients
    that need the resolved artifact paths poll a separate endpoint (not
    exposed in this feature) once the worker completes.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["accepted"]
    job_id: str
    event_id: str
    site_id: str
    source_property_id: int | None = None


__all__ = ["ScriptedRenderResponse"]
