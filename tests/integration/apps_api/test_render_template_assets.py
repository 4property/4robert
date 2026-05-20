"""HTTP smoke tests for render-template static preview assets."""

from __future__ import annotations

import shutil

from fastapi.testclient import TestClient

from apps.api.app_factory import build_api_app
from tests.support.postgres import APPLICATION_ROOT, temporary_workspace


def test_api_serves_classic_render_template_preview_asset() -> None:
    with temporary_workspace() as workspace_dir:
        asset_dir = workspace_dir / "assets" / "render-templates"
        asset_dir.mkdir(parents=True)
        shutil.copyfile(
            APPLICATION_ROOT / "assets" / "render-templates" / "classic-template.png",
            asset_dir / "classic-template.png",
        )
        client = TestClient(
            build_api_app(
                workspace_dir=workspace_dir,
                database_locator="sqlite+pysqlite:///:memory:",
                admin_api_enabled=False,
                site_secrets={},
                enable_docs=False,
                security_disabled=True,
            )
        )

        response = client.get("/assets/render-templates/classic-template.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_api_serves_galaxy_render_template_preview_asset() -> None:
    """Feature 42: the galaxy preview PNG is served by the static mount."""
    with temporary_workspace() as workspace_dir:
        asset_dir = workspace_dir / "assets" / "render-templates"
        asset_dir.mkdir(parents=True)
        shutil.copyfile(
            APPLICATION_ROOT / "assets" / "render-templates" / "galaxy-template.png",
            asset_dir / "galaxy-template.png",
        )
        client = TestClient(
            build_api_app(
                workspace_dir=workspace_dir,
                database_locator="sqlite+pysqlite:///:memory:",
                admin_api_enabled=False,
                site_secrets={},
                enable_docs=False,
                security_disabled=True,
            )
        )

        response = client.get("/assets/render-templates/galaxy-template.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
