"""FastAPI app factory for the API process.

This module builds and returns the ``FastAPI`` application directly.
Feature 9 retired the legacy ``WordPressWebhookServer`` god-class and
moved its remaining responsibilities here:

- TrustedHost / CORS / logging / error-handler middleware composition.
- ``AdminAccessPolicy`` construction via
  :func:`apps.api.admin_auth.build_admin_access_policy`.
- The 7 endpoints that previously lived inline in
  ``services/transport/http/server.py``: ``/health/live``, ``/health``,
  ``/health/ready``, the global ``/v1/admin/wordpress-sources*``,
  ``/v1/admin/agencies/{id}/reel-profile`` and
  ``/v1/admin/agencies/{id}/social-accounts``. They now live in their
  bounded-context routers under ``modules/`` (and ``apps/api/`` for the
  health router).

The API process does not run the worker dispatcher loop — that is
``apps.worker``'s job. The ``dispatcher_accepting_jobs`` field surfaced
by ``/health/ready`` and the WordPress webhook router is therefore
hardcoded to ``True`` for the lifetime of the process: the API itself
has no visibility on the worker, and the field is preserved on the
HTTP contract for backwards compatibility with existing clients.

``build_api_app`` accepts kwargs that override the corresponding settings
constants. They are documented below; the test suite uses them to
configure the application without mutating module-level state.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.api.admin_auth import AdminAccessPolicy, build_admin_access_policy
from apps.api.error_handlers import register_error_handlers
from apps.api.health_router import create_health_router
from apps.api.host_filter import resolve_allowed_hosts, should_enable_docs
from apps.api.logging_middleware import register_logging_middleware
from modules.configuration.transport.http.automation_router import (
    create_automation_router,
)
from modules.configuration.transport.http.brand_router import create_brand_router
from modules.configuration.transport.http.defaults_router import create_defaults_router
from modules.configuration.transport.http.music_router import create_music_router
from modules.configuration.transport.http.reel_profile_router import (
    create_reel_profile_router,
)
from modules.configuration.transport.http.social_templates_router import (
    create_social_templates_router,
)
from modules.ingestion.transport.http.sources_router import create_sources_router
from modules.ingestion.transport.http.wordpress_sources_router import (
    create_wordpress_sources_router,
)
from modules.ingestion.transport.http.wordpress_webhook_router import (
    WordPressWebhookSettings,
    create_wordpress_webhook_router,
)
from modules.publishing.transport.http.connections_router import (
    create_connections_router,
)
from modules.publishing.transport.http.sessions_router import create_sessions_router
from modules.publishing.transport.http.social_accounts_router import (
    create_social_accounts_router,
)
from modules.reels.transport.http.admin_reels_router import (
    create_admin_reels_router,
)
from modules.rendering.transport.http.scripted_router import (
    create_scripted_router,
)
from modules.tenancy.transport.http.admin_agencies_router import (
    create_admin_agencies_router,
)
from settings import (
    ADMIN_AGENCY_TOKEN_SECRET,
    ADMIN_AGENCY_TOKEN_TTL_SECONDS,
    ADMIN_API_BASE_PATH,
    ADMIN_API_DISABLE_AUTH_FOR_TESTING,
    ADMIN_API_ENABLED,
    ADMIN_API_TOKEN,
    DATABASE_URL,
    GO_HIGH_LEVEL_APP_SHARED_SECRET,
    SOCIAL_PUBLISHING_DEFAULT_PLATFORMS,
    WEBHOOK_ALLOWED_HOSTS,
    WEBHOOK_DISABLE_SECURITY,
    WEBHOOK_ENABLE_DOCS,
    WEBHOOK_HOST,
    WEBHOOK_MAX_PAYLOAD_BYTES,
    WEBHOOK_PATH,
    WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_SITE_ID_HEADER,
    WEBHOOK_SITE_SECRETS,
    WEBHOOK_TIMESTAMP_HEADER,
    WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
    WORKER_COUNT,
    WORKER_JOB_MAX_ATTEMPTS,
)
from shared.db import DatabaseUnitOfWork

logger = logging.getLogger(__name__)


def build_api_app(
    *,
    workspace_dir: str | Path | None = None,
    database_locator: str | Path | None = None,
    admin_api_enabled: bool | None = None,
    admin_api_base_path: str | None = None,
    admin_api_token: str | None = None,
    admin_api_disable_auth_for_testing: bool | None = None,
    admin_agency_token_secret: str | None = None,
    admin_agency_token_ttl_seconds: int | None = None,
    gohighlevel_app_shared_secret: str | None = None,
    webhook_auto_provision_unknown_sites_for_testing: bool | None = None,
    site_secrets: Mapping[str, str] | None = None,
    enable_docs: bool | None = None,
    security_disabled: bool | None = None,
    worker_count: int | None = None,
    job_max_attempts: int | None = None,
    dispatcher_accepting_jobs: Callable[[], bool] | None = None,
    readiness_provider: Callable[[], dict[str, object]] | None = None,
) -> FastAPI:
    """Build the FastAPI application without starting the worker dispatcher.

    Test code uses the keyword overrides to configure the application
    deterministically without mutating settings module state. ``None``
    values fall back to the corresponding ``settings`` constant.

    The ``dispatcher_accepting_jobs`` callable feeds the
    ``dispatcher_accepting_jobs`` field of the readiness payload and the
    webhook router's stamp. When omitted the field is hardcoded to
    ``True`` for the lifetime of the API process: the dispatcher loop
    runs out-of-process in ``apps.worker``, so the API has no local
    visibility on it. Tests usually pass a closure directly so the
    dispatcher state is observable without running the lifespan
    context.

    The ``site_secrets`` mapping is shallow-copied so the caller can
    hand in immutable values without affecting the runtime.
    """
    resolved_workspace = (
        Path(workspace_dir).expanduser().resolve()
        if workspace_dir
        else Path(__file__).resolve().parents[2]
    )
    resolved_database = database_locator or DATABASE_URL
    unit_of_work_factory = lambda: DatabaseUnitOfWork(  # noqa: E731
        resolved_database,
        resolved_workspace,
    )

    resolved_admin_enabled = (
        ADMIN_API_ENABLED if admin_api_enabled is None else admin_api_enabled
    )
    resolved_admin_base_path = (
        ADMIN_API_BASE_PATH if admin_api_base_path is None else admin_api_base_path
    )
    resolved_admin_token = (
        ADMIN_API_TOKEN if admin_api_token is None else admin_api_token
    )
    resolved_admin_disable_auth = (
        ADMIN_API_DISABLE_AUTH_FOR_TESTING
        if admin_api_disable_auth_for_testing is None
        else admin_api_disable_auth_for_testing
    )
    resolved_agency_token_secret = (
        ADMIN_AGENCY_TOKEN_SECRET
        if admin_agency_token_secret is None
        else admin_agency_token_secret
    )
    resolved_agency_token_ttl_seconds = int(
        ADMIN_AGENCY_TOKEN_TTL_SECONDS
        if admin_agency_token_ttl_seconds is None
        else admin_agency_token_ttl_seconds
    )
    resolved_shared_secret = (
        GO_HIGH_LEVEL_APP_SHARED_SECRET
        if gohighlevel_app_shared_secret is None
        else gohighlevel_app_shared_secret
    )
    # ``webhook_auto_provision_unknown_sites_for_testing`` is preserved as
    # a kwarg for symmetry with the legacy admin contract and so test
    # builders can pass it through; the current webhook router consumes
    # the flag through ``WEBHOOK_AUTO_PROVISION_UNKNOWN_SITES_FOR_TESTING``
    # at module level.
    del webhook_auto_provision_unknown_sites_for_testing
    resolved_site_secrets: dict[str, str] = (
        dict(WEBHOOK_SITE_SECRETS) if site_secrets is None else dict(site_secrets)
    )
    resolved_security_disabled = bool(
        WEBHOOK_DISABLE_SECURITY if security_disabled is None else security_disabled
    )
    resolved_enable_docs = bool(
        WEBHOOK_ENABLE_DOCS if enable_docs is None else enable_docs
    )
    resolved_worker_count = int(WORKER_COUNT if worker_count is None else worker_count)
    resolved_job_max_attempts = int(
        WORKER_JOB_MAX_ATTEMPTS if job_max_attempts is None else job_max_attempts
    )

    admin_access_policy = build_admin_access_policy(
        enabled=bool(resolved_admin_enabled),
        base_path=resolved_admin_base_path,
        bearer_token=resolved_admin_token,
        disable_auth_for_testing=bool(resolved_admin_disable_auth),
        agency_token_secret=resolved_agency_token_secret,
        agency_token_ttl_seconds=resolved_agency_token_ttl_seconds,
    )

    dispatcher_state: Callable[[], bool] = (
        (lambda: True) if dispatcher_accepting_jobs is None else dispatcher_accepting_jobs
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ARG001
        yield

    docs_enabled = should_enable_docs(
        host=WEBHOOK_HOST,
        enable_docs=resolved_enable_docs,
    )
    app = FastAPI(
        title="CPIHED Webhook API",
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    allowed_hosts = resolve_allowed_hosts(
        allowed_hosts=WEBHOOK_ALLOWED_HOSTS,
        site_secrets=resolved_site_secrets,
    )
    if allowed_hosts:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=list(allowed_hosts),
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_logging_middleware(app)

    _include_module_routers(
        app,
        unit_of_work_factory=unit_of_work_factory,
        admin_access_policy=admin_access_policy,
        resolved_workspace=resolved_workspace,
        resolved_database=resolved_database,
        resolved_site_secrets=resolved_site_secrets,
        resolved_security_disabled=resolved_security_disabled,
        resolved_worker_count=resolved_worker_count,
        resolved_job_max_attempts=resolved_job_max_attempts,
        resolved_shared_secret=str(resolved_shared_secret or ""),
        resolved_agency_token_secret=str(resolved_agency_token_secret or ""),
        resolved_agency_token_ttl_seconds=resolved_agency_token_ttl_seconds,
        resolved_admin_disable_auth=bool(resolved_admin_disable_auth),
        dispatcher_state=dispatcher_state,
        readiness_provider=readiness_provider,
    )
    register_error_handlers(app)
    return app


def _include_module_routers(
    app: FastAPI,
    *,
    unit_of_work_factory,
    admin_access_policy: AdminAccessPolicy,
    resolved_workspace: Path,
    resolved_database: str | Path,
    resolved_site_secrets: dict[str, str],
    resolved_security_disabled: bool,
    resolved_worker_count: int,
    resolved_job_max_attempts: int,
    resolved_shared_secret: str,
    resolved_agency_token_secret: str,
    resolved_agency_token_ttl_seconds: int,
    resolved_admin_disable_auth: bool,
    dispatcher_state: Callable[[], bool],
    readiness_provider: Callable[[], dict[str, object]] | None,
) -> None:
    app.include_router(
        create_health_router(
            workspace_dir=resolved_workspace,
            database_locator=resolved_database,
            site_secrets=resolved_site_secrets,
            worker_count=resolved_worker_count,
            security_disabled=resolved_security_disabled,
            dispatcher_accepting_jobs=dispatcher_state,
            readiness_provider=readiness_provider,
        )
    )
    app.include_router(
        create_sessions_router(
            unit_of_work_factory=unit_of_work_factory,
            shared_secret=resolved_shared_secret,
            agency_token_secret=resolved_agency_token_secret,
            agency_token_ttl_seconds=resolved_agency_token_ttl_seconds,
            admin_disable_auth_for_testing=resolved_admin_disable_auth,
        )
    )
    app.include_router(
        create_admin_agencies_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_connections_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_sources_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_wordpress_sources_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_brand_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_defaults_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_automation_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_social_templates_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_music_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_reel_profile_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_admin_reels_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
            workspace_dir=resolved_workspace,
            job_max_attempts=resolved_job_max_attempts,
            default_platforms=tuple(SOCIAL_PUBLISHING_DEFAULT_PLATFORMS),
        )
    )
    app.include_router(
        create_social_accounts_router(
            unit_of_work_factory=unit_of_work_factory,
            admin_access_policy=admin_access_policy,
        )
    )
    app.include_router(
        create_scripted_router(
            unit_of_work_factory=unit_of_work_factory,
            job_max_attempts=resolved_job_max_attempts,
            max_payload_bytes=WEBHOOK_MAX_PAYLOAD_BYTES,
        )
    )
    app.include_router(
        create_wordpress_webhook_router(
            unit_of_work_factory=unit_of_work_factory,
            settings=WordPressWebhookSettings(
                path=WEBHOOK_PATH,
                site_id_header=WEBHOOK_SITE_ID_HEADER,
                timestamp_header=WEBHOOK_TIMESTAMP_HEADER,
                signature_header=WEBHOOK_SIGNATURE_HEADER,
                max_payload_bytes=WEBHOOK_MAX_PAYLOAD_BYTES,
                timestamp_tolerance_seconds=WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
                security_disabled=resolved_security_disabled,
                site_secrets=dict(resolved_site_secrets),
                default_platforms=tuple(SOCIAL_PUBLISHING_DEFAULT_PLATFORMS),
            ),
            job_max_attempts=resolved_job_max_attempts,
            dispatcher_state=dispatcher_state,
        )
    )


__all__ = ["build_api_app"]
