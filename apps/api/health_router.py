"""Health endpoints for the API process.

Exposes three endpoints:

- ``GET /health/live`` — liveness probe. Always returns ``{"status": "ok"}``.
- ``GET /health`` — readiness probe (alias of ``/health/ready``). Returns the
  minimal payload ``{"status": "ready"|"not_ready", "dispatcher_accepting_jobs": bool}``.
- ``GET /health/ready`` — same body as ``/health``.

The dispatcher state is supplied via the ``dispatcher_accepting_jobs``
callable injected by ``apps.api.app_factory.build_api_app``. The full
readiness report is delegated to
:func:`apps.api.readiness.build_readiness_report` which is the same routine
the ``--check`` CLI relies on.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Mapping

from fastapi import APIRouter
from fastapi.responses import JSONResponse


ReadinessProvider = Callable[[], dict[str, object]]


def create_health_router(
    *,
    workspace_dir: Path,
    database_locator: str | Path,
    site_secrets: Mapping[str, str],
    worker_count: int,
    security_disabled: bool,
    dispatcher_accepting_jobs: Callable[[], bool],
    readiness_provider: ReadinessProvider | None = None,
) -> APIRouter:
    """Build the health router using the runtime configuration of the API.

    The readiness report is rebuilt on each request because the underlying
    checks (database writable, ffmpeg available, …) depend on live
    filesystem and database state.

    Tests inject a deterministic ``readiness_provider`` to avoid bringing
    ffmpeg, fonts and webhook secrets into the test fixture; production
    callers leave it unset and the router runs the canonical
    :func:`apps.api.readiness.build_readiness_report`.
    """
    router = APIRouter(tags=["Health"])

    @router.get(
        "/health/live",
        summary="Liveness probe",
        description="Always returns 200 with `{\"status\": \"ok\"}` once the process is up.",
    )
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get(
        "/health",
        summary="Readiness probe",
        description=(
            "Returns 200 once the runtime can accept work, 503 otherwise. "
            "Body shape: `{status, dispatcher_accepting_jobs}`."
        ),
    )
    async def health() -> JSONResponse:
        return _build_readiness_response(
            workspace_dir=workspace_dir,
            database_locator=database_locator,
            site_secrets=site_secrets,
            worker_count=worker_count,
            security_disabled=security_disabled,
            dispatcher_accepting_jobs=dispatcher_accepting_jobs,
            readiness_provider=readiness_provider,
        )

    @router.get(
        "/health/ready",
        summary="Readiness probe (alias)",
        description="Same response as `/health`. Provided for orchestrator conventions.",
    )
    async def health_ready() -> JSONResponse:
        return _build_readiness_response(
            workspace_dir=workspace_dir,
            database_locator=database_locator,
            site_secrets=site_secrets,
            worker_count=worker_count,
            security_disabled=security_disabled,
            dispatcher_accepting_jobs=dispatcher_accepting_jobs,
            readiness_provider=readiness_provider,
        )

    return router


def _build_readiness_response(
    *,
    workspace_dir: Path,
    database_locator: str | Path,
    site_secrets: Mapping[str, str],
    worker_count: int,
    security_disabled: bool,
    dispatcher_accepting_jobs: Callable[[], bool],
    readiness_provider: ReadinessProvider | None = None,
) -> JSONResponse:
    if readiness_provider is not None:
        readiness = readiness_provider()
    else:
        from apps.api.readiness import build_readiness_report

        readiness = build_readiness_report(
            workspace_dir,
            database_locator=database_locator,
            site_secrets=dict(site_secrets),
            worker_count=worker_count,
            security_disabled=security_disabled,
        )
    accepting_jobs = bool(dispatcher_accepting_jobs())
    payload: dict[str, object] = {
        "status": "ready" if readiness.get("ready") else "not_ready",
        "dispatcher_accepting_jobs": accepting_jobs,
    }
    status_code = 200 if readiness.get("ready") else 503
    return JSONResponse(status_code=status_code, content=payload)


__all__ = ["create_health_router"]
