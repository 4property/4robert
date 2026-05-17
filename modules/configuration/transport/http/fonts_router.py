"""FastAPI router for the global font-catalogue endpoint.

``GET /v1/admin/fonts`` — global (no per-agency segment) read-only
listing of the fonts available to the brand selector. The endpoint
sits under the admin scope so the frontend dropdown is populated with
the exact same catalogue the backend validates against on PUT /brand
(feature 28).

Layer rule: this router lives in ``modules/configuration/transport``
and imports only from ``application`` + ``domain``. The catalogue
itself is in :mod:`modules.configuration.domain.font_catalog`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from apps.api.admin_auth import AdminAccessPolicy, authorize_admin_request
from modules.configuration.application.use_cases.list_available_fonts import (
    ListAvailableFontsUseCase,
)
from modules.configuration.domain.font_catalog import FontDescriptor


def create_fonts_router(
    *,
    admin_access_policy: AdminAccessPolicy,
    workspace_dir: str | Path | None = None,
    list_available_fonts: ListAvailableFontsUseCase | None = None,
) -> APIRouter:
    """Build the fonts router.

    ``workspace_dir`` is the repository root used to resolve the
    workspace-relative TTF paths from the catalogue. The default
    matches the rest of the admin routers (the API process runs with
    the repository as CWD), so the kwarg is exposed mostly for the
    test client builder.
    """
    router = APIRouter(
        prefix=admin_access_policy.base_path,
        tags=["Admin · Fonts"],
    )
    list_available_fonts = list_available_fonts or ListAvailableFontsUseCase()
    resolved_workspace = (
        Path(workspace_dir).expanduser().resolve() if workspace_dir else None
    )

    @router.get(
        "/fonts",
        summary="List the font catalogue available to the brand selector",
        description=(
            "Returns the immutable catalogue of fonts shipped with the "
            "backend. The frontend `/brand` dropdown should populate from "
            "this endpoint so the selector and the `PUT /brand` validator "
            "stay in lockstep. The `available` flag is `false` when the "
            "TTF is missing on disk — useful for diagnosing a broken "
            "deploy without reading worker logs."
        ),
    )
    async def list_admin_fonts(request: Request) -> JSONResponse:
        authorization_error = authorize_admin_request(request, admin_access_policy)
        if authorization_error is not None:
            return authorization_error
        fonts = list_available_fonts.execute()
        items = [
            _serialize_descriptor(descriptor, workspace_dir=resolved_workspace)
            for descriptor in fonts
        ]
        return JSONResponse(
            status_code=200,
            content={
                "items": items,
                "count": len(items),
            },
        )

    return router


def _serialize_descriptor(
    descriptor: FontDescriptor,
    *,
    workspace_dir: Path | None,
) -> dict[str, object]:
    return {
        "family": descriptor.family,
        "display_name": descriptor.display_name,
        "available": descriptor.available(workspace_dir=workspace_dir),
    }


__all__ = ["create_fonts_router"]
