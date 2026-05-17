"""Integration tests for the configuration fonts router (feature 28)."""

from __future__ import annotations

from pathlib import Path

from settings import DATABASE_URL
from tests.integration.configuration._client import (
    ADMIN_BEARER,
    build_configuration_client,
)
from tests.support.postgres import temporary_postgres_schema, temporary_workspace


REPO_ROOT = Path(__file__).resolve().parents[3]


def _patch_workspace_with_fonts(workspace_dir: Path) -> None:
    """Symlink the repository's ``assets/fonts/`` into the temp workspace.

    The test client builder hands the per-test workspace to the fonts
    router as the ``workspace_dir``. The TTFs live in the repository's
    own ``assets/fonts/`` so we need the temporary workspace to expose
    them — a symlink is the cheapest option.
    """
    target = workspace_dir / "assets"
    target.mkdir(parents=True, exist_ok=True)
    fonts_link = target / "fonts"
    if not fonts_link.exists():
        fonts_link.symlink_to(REPO_ROOT / "assets" / "fonts")


def test_fonts_list_returns_six_catalogue_entries() -> None:
    with temporary_workspace() as workspace_dir:
        _patch_workspace_with_fonts(workspace_dir)
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get("/v1/admin/fonts", headers=ADMIN_BEARER)
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["count"] == 6
            assert len(payload["items"]) == 6
            families = [item["family"] for item in payload["items"]]
            assert families == [
                "Inter",
                "Manrope",
                "Plus Jakarta Sans",
                "Montserrat",
                "Poppins",
                "Roboto",
            ]
            for item in payload["items"]:
                assert item["family"] == item["display_name"]
                assert item["available"] is True


def test_fonts_list_requires_admin_bearer() -> None:
    with temporary_workspace() as workspace_dir:
        _patch_workspace_with_fonts(workspace_dir)
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get("/v1/admin/fonts")
            assert response.status_code == 401


def test_fonts_list_marks_missing_files_unavailable() -> None:
    """When the workspace lacks the TTFs the items report ``available=false``."""
    with temporary_workspace() as workspace_dir:
        # Deliberately do not symlink the fonts directory.
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get("/v1/admin/fonts", headers=ADMIN_BEARER)
            assert response.status_code == 200, response.text
            for item in response.json()["items"]:
                assert item["available"] is False
