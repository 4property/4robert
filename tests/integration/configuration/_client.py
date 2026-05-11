"""Shared test client builder for the configuration HTTP routers."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.admin_auth import AdminAccessPolicy
from apps.api.error_handlers import register_error_handlers
from modules.configuration.transport.http.automation_router import (
    create_automation_router,
)
from modules.configuration.transport.http.brand_router import create_brand_router
from modules.configuration.transport.http.defaults_router import create_defaults_router
from modules.configuration.transport.http.music_router import create_music_router
from modules.configuration.transport.http.social_templates_router import (
    create_social_templates_router,
)
from shared.db import DatabaseUnitOfWork

ADMIN_BEARER = {"Authorization": "Bearer test-admin-token"}


def build_configuration_client(
    *,
    database_url: str,
    workspace_dir: Path,
) -> TestClient:
    policy = AdminAccessPolicy(
        enabled=True,
        base_path="/v1/admin",
        bearer_token="test-admin-token",
        disable_auth_for_testing=False,
    )
    app = FastAPI()
    factory = lambda: DatabaseUnitOfWork(database_url, workspace_dir)  # noqa: E731
    app.include_router(
        create_brand_router(unit_of_work_factory=factory, admin_access_policy=policy)
    )
    app.include_router(
        create_defaults_router(
            unit_of_work_factory=factory, admin_access_policy=policy
        )
    )
    app.include_router(
        create_automation_router(
            unit_of_work_factory=factory, admin_access_policy=policy
        )
    )
    app.include_router(
        create_social_templates_router(
            unit_of_work_factory=factory, admin_access_policy=policy
        )
    )
    app.include_router(
        create_music_router(unit_of_work_factory=factory, admin_access_policy=policy)
    )
    register_error_handlers(app)
    return TestClient(app)


__all__ = ["ADMIN_BEARER", "build_configuration_client"]
