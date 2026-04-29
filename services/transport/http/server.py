from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from application.admin import UpsertWordPressSourceRequest, WordPressSourceAdminService
from application.scripted_render.service import ScriptedVideoRenderService
from application.bootstrap.runtime import (
    build_default_job_dispatcher,
    build_runtime_unit_of_work_factory,
)
from application.pipeline.interfaces import JobDispatcher
from application.tenancy.resolver import TenantResolver
from application.types import SocialPublishContext
from application.dispatch.webhook_acceptance import WebhookAcceptanceService
from settings import (
    ADMIN_API_BASE_PATH,
    ADMIN_API_DISABLE_AUTH_FOR_TESTING,
    ADMIN_API_ENABLED,
    ADMIN_API_TOKEN,
    DATABASE_URL,
    GO_HIGH_LEVEL_API_VERSION,
    GO_HIGH_LEVEL_APP_SHARED_SECRET,
    GO_HIGH_LEVEL_BASE_URL,
    LOG_LEVEL,
    OUTBOUND_HTTP_TIMEOUT_SECONDS,
    PERSISTENT_LOG_BACKUP_COUNT,
    PERSISTENT_LOG_DIRECTORY,
    PERSISTENT_LOG_MAX_BYTES,
    PERSISTENT_LOGGING_ENABLED,
    SOCIAL_PUBLISHING_DEFAULT_PLATFORMS,
    WEBHOOK_ALLOWED_HOSTS,
    WEBHOOK_AUTO_PROVISION_UNKNOWN_SITES_FOR_TESTING,
    WEBHOOK_DISABLE_SECURITY,
    WEBHOOK_ENABLE_DOCS,
    WEBHOOK_FORWARDED_ALLOW_IPS,
    WEBHOOK_GOHIGHLEVEL_ACCESS_TOKEN_HEADER,
    WEBHOOK_GOHIGHLEVEL_LOCATION_ID_HEADER,
    WEBHOOK_HOST,
    WEBHOOK_JOB_MAX_ATTEMPTS,
    WEBHOOK_LIMIT_CONCURRENCY,
    WEBHOOK_MAX_PAYLOAD_BYTES,
    WEBHOOK_PATH,
    WEBHOOK_PORT,
    WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS,
    WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_SITE_ID_HEADER,
    WEBHOOK_SITE_SECRETS,
    WEBHOOK_TIMESTAMP_HEADER,
    WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
    WEBHOOK_TRUST_PROXY_HEADERS,
    WEBHOOK_WORKER_COUNT,
)
from core.errors import (
    ApplicationError,
    DependencyNotInstalledError,
    ResourceNotFoundError,
    ValidationError,
    extract_error_details,
)
from core.logging import (
    configure_logging,
    format_console_block,
    format_context_line,
    format_detail_line,
    log_persistent_event,
    resolve_log_directory,
)
from services.transport.http.operations import build_readiness_report, run_startup_checks
from services.transport.http.openapi_docs import OpenApiDocsConfig, install_openapi_examples
from services.transport.http.uvicorn_protocols import VerboseAutoHTTPProtocol
from services.transport.http.security import build_raw_payload_hash, is_signature_valid, is_timestamp_fresh
from services.publishing.social_delivery.gohighlevel_client import GoHighLevelClient
from services.publishing.social_delivery.gohighlevel_social_service import GoHighLevelSocialService

logger = logging.getLogger(__name__)

_ALTERNATE_GOHIGHLEVEL_LOCATION_ID_HEADERS = ("X-GHL-Location-Id",)
_ALTERNATE_GOHIGHLEVEL_ACCESS_TOKEN_HEADERS = ("X-GHL-Token",)
_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "set-cookie",
        "x-ghl-token",
        "x-gohighlevel-access-token",
        "x-wordpress-signature",
    }
)
_SENSITIVE_BODY_FIELDS = frozenset(
    {
        "access_token",
        "refresh_token",
        "token",
        "encrypted_data",
        "encryptedData",
        "client_secret",
        "authorization",
    }
)


@dataclass(frozen=True, slots=True)
class _AdminAccessPolicy:
    enabled: bool
    base_path: str
    bearer_token: str
    disable_auth_for_testing: bool


class _AdminWordPressSourceUpsertPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_name: str = Field(min_length=1)
    agency_id: str | None = None
    agency_name: str | None = None
    agency_slug: str | None = None
    agency_timezone: str | None = None
    agency_status: str | None = None
    site_url: str | None = None
    normalized_host: str | None = None
    source_status: str | None = None
    webhook_secret: str | None = None


class _AdminAgencyCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1)
    slug: str | None = None
    timezone: str | None = None
    status: str | None = None


class _AdminAgencyUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = None
    slug: str | None = None
    timezone: str | None = None
    status: str | None = None


class _AdminAgencySourceUpsertPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    site_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    site_url: str | None = None
    normalized_host: str | None = None
    source_status: str | None = None
    webhook_secret: str | None = None


class _AdminGhlConnectionUpsertPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    location_id: str = Field(min_length=1)
    user_id: str | None = None
    access_token: str = Field(min_length=1)
    refresh_token: str | None = ""
    expires_at: str | None = ""
    status: str | None = None


class _AdminReelProfileUpsertPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = None
    platforms: list[str] | None = None
    duration_seconds: int | None = None
    music_id: str | None = None
    intro_enabled: bool | None = None
    logo_position: str | None = None
    brand_primary_color: str | None = None
    brand_secondary_color: str | None = None
    caption_template: str | None = None
    approval_required: bool | None = None
    extra_settings: dict | None = None


class _MvpGoHighLevelSessionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    location_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class _MvpGoHighLevelLocationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    location_id: str = Field(min_length=1)


class _MvpGoHighLevelContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    encrypted_data: str = Field(
        min_length=1,
        validation_alias=AliasChoices("encrypted_data", "encryptedData"),
    )


class WordPressWebhookApplication:
    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        dispatcher: JobDispatcher,
        database_locator: str | Path | None = None,
        host: str = WEBHOOK_HOST,
        path: str = WEBHOOK_PATH,
        site_id_header: str = WEBHOOK_SITE_ID_HEADER,
        gohighlevel_location_id_header: str = WEBHOOK_GOHIGHLEVEL_LOCATION_ID_HEADER,
        gohighlevel_access_token_header: str = WEBHOOK_GOHIGHLEVEL_ACCESS_TOKEN_HEADER,
        timestamp_header: str = WEBHOOK_TIMESTAMP_HEADER,
        signature_header: str = WEBHOOK_SIGNATURE_HEADER,
        site_secrets: dict[str, str] | None = None,
        allowed_hosts: tuple[str, ...] = WEBHOOK_ALLOWED_HOSTS,
        security_disabled: bool = WEBHOOK_DISABLE_SECURITY,
        webhook_auto_provision_unknown_sites_for_testing: bool = WEBHOOK_AUTO_PROVISION_UNKNOWN_SITES_FOR_TESTING,
        enable_docs: bool = WEBHOOK_ENABLE_DOCS,
        admin_api_enabled: bool = ADMIN_API_ENABLED,
        admin_api_base_path: str = ADMIN_API_BASE_PATH,
        admin_api_token: str = ADMIN_API_TOKEN,
        admin_api_disable_auth_for_testing: bool = ADMIN_API_DISABLE_AUTH_FOR_TESTING,
        gohighlevel_app_shared_secret: str = GO_HIGH_LEVEL_APP_SHARED_SECRET,
        shutdown_timeout_seconds: int = WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS,
        timestamp_tolerance_seconds: int = WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
        max_payload_bytes: int = WEBHOOK_MAX_PAYLOAD_BYTES,
        worker_count: int = WEBHOOK_WORKER_COUNT,
        job_max_attempts: int = WEBHOOK_JOB_MAX_ATTEMPTS,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.database_locator = DATABASE_URL if database_locator is None else database_locator
        self.dispatcher = dispatcher
        self.unit_of_work_factory = build_runtime_unit_of_work_factory(
            self.workspace_dir,
            database_locator=self.database_locator,
        )
        self.wordpress_source_admin_service = WordPressSourceAdminService(
            unit_of_work_factory=self.unit_of_work_factory,
        )
        self.allow_unknown_sites_for_testing = bool(
            security_disabled and webhook_auto_provision_unknown_sites_for_testing
        )
        self.acceptance_service = WebhookAcceptanceService(
            tenant_resolver=TenantResolver(
                unit_of_work_factory=self.unit_of_work_factory,
                allow_unknown_sites_for_testing=self.allow_unknown_sites_for_testing,
                unsafe_test_source_provisioner=self.wordpress_source_admin_service.ensure_source_for_testing,
            ),
            unit_of_work_factory=self.unit_of_work_factory,
            job_max_attempts=job_max_attempts,
        )
        self.scripted_video_service = ScriptedVideoRenderService(
            self.workspace_dir,
            unit_of_work_factory=self.unit_of_work_factory,
        )
        self.path = path
        self.host = host
        self.site_id_header = site_id_header
        self.gohighlevel_location_id_header = gohighlevel_location_id_header
        self.gohighlevel_access_token_header = gohighlevel_access_token_header
        self.timestamp_header = timestamp_header
        self.signature_header = signature_header
        self.site_secrets = dict(site_secrets or WEBHOOK_SITE_SECRETS)
        self.allowed_hosts = tuple(allowed_hosts)
        self.security_disabled = security_disabled
        self.enable_docs = bool(enable_docs)
        self.admin_access_policy = _AdminAccessPolicy(
            enabled=bool(admin_api_enabled),
            base_path=admin_api_base_path,
            bearer_token=str(admin_api_token or ""),
            disable_auth_for_testing=bool(admin_api_disable_auth_for_testing),
        )
        self.gohighlevel_app_shared_secret = str(gohighlevel_app_shared_secret or "")
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.timestamp_tolerance_seconds = timestamp_tolerance_seconds
        self.max_payload_bytes = max_payload_bytes
        self.worker_count = worker_count

    def start(self) -> None:
        configure_logging(
            LOG_LEVEL,
            workspace_dir=self.workspace_dir,
            persistent_logging_enabled=PERSISTENT_LOGGING_ENABLED,
            persistent_log_directory=PERSISTENT_LOG_DIRECTORY,
            persistent_log_max_bytes=PERSISTENT_LOG_MAX_BYTES,
            persistent_log_backup_count=PERSISTENT_LOG_BACKUP_COUNT,
        )
        readiness = run_startup_checks(
            self.workspace_dir,
            database_locator=self.database_locator,
            site_secrets=self.site_secrets,
            worker_count=self.worker_count,
            security_disabled=self.security_disabled,
        )
        effective_allowed_hosts = _resolve_allowed_hosts(self)
        log_dir = resolve_log_directory(
            self.workspace_dir,
            persistent_log_directory=PERSISTENT_LOG_DIRECTORY,
        )
        self.dispatcher.start()
        logger.info(
            format_console_block(
                "Webhook Runtime Started",
                format_detail_line("Webhook path", self.path),
                format_detail_line("Worker count", self.worker_count),
                format_detail_line("Queue backend", "PostgreSQL durable queue"),
                format_detail_line("Workspace", self.workspace_dir),
                format_detail_line(
                    "Database",
                    readiness.get("environment", {}).get("database_url"),
                ),
                format_detail_line(
                    "Database schema",
                    readiness.get("environment", {}).get("database_schema"),
                ),
                format_detail_line(
                    "FFmpeg",
                    readiness.get("environment", {}).get("ffmpeg_binary"),
                ),
                format_detail_line("Security disabled", "Yes" if self.security_disabled else "No"),
                format_detail_line(
                    "Unknown sites auto-provisioned for testing",
                    "Yes" if self.allow_unknown_sites_for_testing else "No",
                ),
                format_detail_line(
                    "Allowed hosts",
                    ", ".join(effective_allowed_hosts) if effective_allowed_hosts else "Disabled",
                ),
                format_detail_line(
                    "Admin API",
                    (
                        f"{self.admin_access_policy.base_path} "
                        f"(enabled={'yes' if self.admin_access_policy.enabled else 'no'}, "
                        f"token_configured={'yes' if bool(self.admin_access_policy.bearer_token) else 'no'}, "
                        f"auth_disabled_for_testing={'yes' if self.admin_access_policy.disable_auth_for_testing else 'no'})"
                    ),
                ),
                format_detail_line("Log directory", log_dir),
            )
        )
        log_persistent_event(
            "runtime.started",
            workspace_dir=str(self.workspace_dir),
            webhook_path=self.path,
            worker_count=self.worker_count,
            security_disabled=self.security_disabled,
            webhook_auto_provision_unknown_sites_for_testing=self.allow_unknown_sites_for_testing,
            allowed_hosts=list(effective_allowed_hosts),
            admin_api_enabled=self.admin_access_policy.enabled,
            admin_api_base_path=self.admin_access_policy.base_path,
            admin_api_token_configured=bool(self.admin_access_policy.bearer_token),
            admin_api_disable_auth_for_testing=self.admin_access_policy.disable_auth_for_testing,
            log_directory=str(log_dir),
        )
        if self.security_disabled:
            logger.warning(
                format_console_block(
                    "Webhook Security Disabled",
                    "Incoming requests are accepted without signature validation.",
                    "Use this mode only for local testing.",
                )
            )
        if self.allow_unknown_sites_for_testing:
            logger.warning(
                format_console_block(
                    "Unknown WordPress Sites Auto-Provisioned For Testing",
                    "Unregistered site_id values will create placeholder tenant rows automatically.",
                    "Use this mode only for disposable local or staging test data.",
                )
            )
        if self.admin_access_policy.disable_auth_for_testing:
            logger.warning(
                format_console_block(
                    "Admin API Authentication Disabled For Testing",
                    "Admin endpoints will allow requests without Authorization: Bearer.",
                    "Use this mode only in an isolated test environment.",
                )
            )

    def stop(self) -> None:
        self.dispatcher.stop(timeout=float(self.shutdown_timeout_seconds))
        logger.info(
            format_console_block(
                "Webhook Runtime Stopped",
                "The webhook application shut down cleanly.",
            )
        )
        log_persistent_event(
            "runtime.stopped",
            workspace_dir=str(self.workspace_dir),
            shutdown_timeout_seconds=self.shutdown_timeout_seconds,
        )

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        return self.dispatcher.wait_for_idle(timeout=timeout)

    def build_readiness_report(self) -> dict[str, object]:
        readiness = build_readiness_report(
            self.workspace_dir,
            database_locator=self.database_locator,
            site_secrets=self.site_secrets,
            worker_count=self.worker_count,
            security_disabled=self.security_disabled,
        )
        readiness["dispatcher_accepting_jobs"] = self.dispatcher.is_accepting_jobs()
        return readiness

    def authenticate(
        self,
        *,
        site_id: str,
        location_id: str,
        access_token: str,
        timestamp: str,
        signature: str,
        raw_body: bytes,
    ) -> bool:
        return self.authenticate_with_details(
            site_id=site_id,
            location_id=location_id,
            access_token=access_token,
            timestamp=timestamp,
            signature=signature,
            raw_body=raw_body,
        )[0]

    def authenticate_with_details(
        self,
        *,
        site_id: str,
        location_id: str,
        access_token: str,
        timestamp: str,
        signature: str,
        raw_body: bytes,
    ) -> tuple[bool, str | None, str | None]:
        if self.security_disabled:
            if not site_id:
                return (
                    False,
                    "The webhook site_id could not be resolved while security is disabled.",
                    "Send the configured site header or include a property link/guid that contains the site domain.",
                )
            return True, None, None
        expected_secret = self.site_secrets.get(site_id)
        if expected_secret is None:
            return (
                False,
                f"No webhook secret is configured for site_id '{site_id}'.",
                "Add the site to WEBHOOK_SITE_SECRETS on the deployed service and restart it.",
            )
        if not is_timestamp_fresh(
            timestamp,
            tolerance_seconds=self.timestamp_tolerance_seconds,
        ):
            return (
                False,
                "The webhook timestamp is outside the accepted tolerance window.",
                "Check clock drift between WordPress and the API host or increase WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS if needed.",
            )
        signature_valid = is_signature_valid(
            secret=expected_secret,
            timestamp=timestamp,
            site_id=site_id,
            location_id=location_id,
            access_token=access_token,
            raw_body=raw_body,
            signature=signature,
        )
        if not signature_valid:
            return (
                False,
                "The webhook signature does not match the configured site secret.",
                "Ensure WordPress signs the raw JSON body with the same secret and the same header values received by this service.",
            )
        return True, None, None

    def accept_webhook_delivery(
        self,
        *,
        site_id: str,
        property_id: int | None,
        raw_payload_hash: str,
        payload: dict[str, Any],
        publish_context: SocialPublishContext | None,
    ):
        return self.acceptance_service.accept_delivery(
            site_id=site_id,
            property_id=property_id,
            raw_payload_hash=raw_payload_hash,
            payload=payload,
            publish_context=publish_context,
        )

    def upsert_ghl_connection(
        self,
        *,
        agency_id: str,
        location_id: str,
        user_id: str,
        access_token: str,
        refresh_token: str = "",
        expires_at: str = "",
        status: str = "active",
    ):
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            return unit_of_work.ghl_connection_store.upsert_for_agency(
                agency_id=agency_id,
                location_id=location_id,
                user_id=user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                status=status,
            )

    def get_ghl_connection_by_agency(self, *, agency_id: str):
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.ghl_connection_store.get_by_agency_id(agency_id)

    def get_ghl_connection_by_location(self, *, location_id: str):
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.ghl_connection_store.get_by_location_id(location_id)

    def list_ghl_connections(self):
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.ghl_connection_store.list_connections()

    def delete_ghl_connection(self, *, agency_id: str) -> bool:
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            return unit_of_work.ghl_connection_store.delete_by_agency_id(agency_id)

    def require_ghl_connection_for_agency(self, *, agency_id: str):
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.ghl_connection_store.require_for_agency(agency_id)

    def get_reel_profile(self, *, agency_id: str):
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.reel_profile_store.get_by_agency_id(agency_id)

    def upsert_reel_profile(self, **kwargs):
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            return unit_of_work.reel_profile_store.upsert_for_agency(**kwargs)

    def delete_reel_profile(self, *, agency_id: str) -> bool:
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            return unit_of_work.reel_profile_store.delete_by_agency_id(agency_id)

    def list_agencies(self):
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.agency_store.list_agencies()

    def get_agency(self, *, agency_id: str):
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.agency_store.get_by_id(agency_id)

    def create_agency(self, **kwargs) -> str:
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            unit_of_work.agency_store.create_agency(**kwargs)
        return kwargs["agency_id"]

    def update_agency(self, **kwargs) -> None:
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            unit_of_work.agency_store.update_agency(**kwargs)

    def delete_agency(self, *, agency_id: str) -> bool:
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            return unit_of_work.agency_store.delete_agency(agency_id)

    def list_sources_for_agency(self, *, agency_id: str):
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.wordpress_source_store.list_sources_for_agency(agency_id)

    def list_agency_reels(self, *, agency_id: str, limit: int = 50):
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.property_repository.list_recent_for_agency(
                agency_id=agency_id,
                limit=limit,
            )

    def delete_wordpress_source(self, *, wordpress_source_id: str) -> bool:
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            return unit_of_work.wordpress_source_store.delete_source(wordpress_source_id)

    def test_gohighlevel_connection(self, *, location_id: str, access_token: str):
        client = GoHighLevelClient(
            base_url=GO_HIGH_LEVEL_BASE_URL,
            api_version=GO_HIGH_LEVEL_API_VERSION,
            timeout_seconds=OUTBOUND_HTTP_TIMEOUT_SECONDS,
        )
        try:
            social_service = GoHighLevelSocialService(client=client)
            return social_service.list_accounts(
                location_id=location_id,
                access_token=access_token,
            )
        finally:
            client.close()

    def decrypt_gohighlevel_user_context(self, *, encrypted_data: str) -> dict[str, Any]:
        return _decrypt_gohighlevel_user_context(
            encrypted_data=encrypted_data,
            shared_secret=self.gohighlevel_app_shared_secret,
        )

    def render_scripted_video(
        self,
        *,
        payload: dict[str, Any],
    ):
        return self.scripted_video_service.render_from_manifest(payload)


class WordPressWebhookServer:
    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        dispatcher: JobDispatcher | None = None,
        database_locator: str | Path | None = DATABASE_URL,
        host: str = WEBHOOK_HOST,
        path: str = WEBHOOK_PATH,
        site_id_header: str = WEBHOOK_SITE_ID_HEADER,
        gohighlevel_location_id_header: str = WEBHOOK_GOHIGHLEVEL_LOCATION_ID_HEADER,
        gohighlevel_access_token_header: str = WEBHOOK_GOHIGHLEVEL_ACCESS_TOKEN_HEADER,
        timestamp_header: str = WEBHOOK_TIMESTAMP_HEADER,
        signature_header: str = WEBHOOK_SIGNATURE_HEADER,
        site_secrets: dict[str, str] | None = None,
        allowed_hosts: tuple[str, ...] = WEBHOOK_ALLOWED_HOSTS,
        security_disabled: bool = WEBHOOK_DISABLE_SECURITY,
        webhook_auto_provision_unknown_sites_for_testing: bool = WEBHOOK_AUTO_PROVISION_UNKNOWN_SITES_FOR_TESTING,
        enable_docs: bool = WEBHOOK_ENABLE_DOCS,
        admin_api_enabled: bool = ADMIN_API_ENABLED,
        admin_api_base_path: str = ADMIN_API_BASE_PATH,
        admin_api_token: str = ADMIN_API_TOKEN,
        admin_api_disable_auth_for_testing: bool = ADMIN_API_DISABLE_AUTH_FOR_TESTING,
        gohighlevel_app_shared_secret: str = GO_HIGH_LEVEL_APP_SHARED_SECRET,
        shutdown_timeout_seconds: int = WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS,
        timestamp_tolerance_seconds: int = WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
        max_payload_bytes: int = WEBHOOK_MAX_PAYLOAD_BYTES,
        worker_count: int = WEBHOOK_WORKER_COUNT,
    ) -> None:
        active_dispatcher = dispatcher or build_default_job_dispatcher(
            workspace_dir,
            database_locator=database_locator,
            worker_count=worker_count,
        )
        self.runtime = WordPressWebhookApplication(
            workspace_dir,
            dispatcher=active_dispatcher,
            database_locator=database_locator,
            host=host,
            path=path,
            site_id_header=site_id_header,
            gohighlevel_location_id_header=gohighlevel_location_id_header,
            gohighlevel_access_token_header=gohighlevel_access_token_header,
            timestamp_header=timestamp_header,
            signature_header=signature_header,
            site_secrets=site_secrets,
            allowed_hosts=allowed_hosts,
            security_disabled=security_disabled,
            webhook_auto_provision_unknown_sites_for_testing=webhook_auto_provision_unknown_sites_for_testing,
            enable_docs=enable_docs,
            admin_api_enabled=admin_api_enabled,
            admin_api_base_path=admin_api_base_path,
            admin_api_token=admin_api_token,
            admin_api_disable_auth_for_testing=admin_api_disable_auth_for_testing,
            gohighlevel_app_shared_secret=gohighlevel_app_shared_secret,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
            timestamp_tolerance_seconds=timestamp_tolerance_seconds,
            max_payload_bytes=max_payload_bytes,
            worker_count=worker_count,
        )
        self.app = create_fastapi_app(application=self.runtime)

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        return self.runtime.wait_for_idle(timeout=timeout)


def create_fastapi_app(
    *,
    application: WordPressWebhookApplication,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        application.start()
        try:
            yield
        finally:
            application.stop()

    docs_enabled = _should_enable_docs(
        host=application.host,
        enable_docs=application.enable_docs,
    )
    app = FastAPI(
        title="CPIHED Webhook API",
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    allowed_hosts = _resolve_allowed_hosts(application)
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
    app.state.runtime = application
    install_openapi_examples(
        app,
        config=OpenApiDocsConfig(
            workspace_dir=application.workspace_dir,
            webhook_path=application.path,
            site_id_header=application.site_id_header,
            gohighlevel_location_id_header=application.gohighlevel_location_id_header,
            gohighlevel_access_token_header=application.gohighlevel_access_token_header,
            timestamp_header=application.timestamp_header,
            signature_header=application.signature_header,
        ),
    )

    @app.middleware("http")
    async def persist_http_traffic(request: Request, call_next):
        started_at = time.perf_counter()
        request_id = str(time.time_ns())
        raw_body = b""
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            raw_body = await request.body()
            request = _rebuild_request_with_body(request, raw_body)
        request.state.request_id = request_id

        log_persistent_event(
            "http.request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            client=_format_client(request),
            headers=_sanitize_headers_for_logging(request.headers),
            body=_decode_body_for_logging(raw_body),
            body_size_bytes=len(raw_body),
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            log_persistent_event(
                "http.exception",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                query=request.url.query,
                client=_format_client(request),
                duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise

        response_body = _extract_response_body(response)
        log_persistent_event(
            "http.response",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
            headers=_sanitize_headers_for_logging(response.headers),
            body=_decode_body_for_logging(response_body),
            body_size_bytes=(len(response_body) if response_body is not None else None),
        )
        return response

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    async def _health_ready_response(request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        readiness = runtime.build_readiness_report()
        status_code = 200 if readiness["ready"] else 503
        return JSONResponse(
            status_code=status_code,
            content=_build_minimal_readiness_payload(readiness),
        )

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        return await _health_ready_response(request)

    @app.get("/health/ready")
    async def health_ready(request: Request) -> JSONResponse:
        return await _health_ready_response(request)

    @app.get("/mvp/gohighlevel/tokens", tags=["MVP"])
    async def list_mvp_gohighlevel_connections(request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        records = runtime.list_ghl_connections()
        items = [record.to_public_dict() for record in records]
        return JSONResponse(
            status_code=200,
            content={"count": len(items), "items": items},
        )

    @app.post("/mvp/gohighlevel/context", tags=["MVP"])
    async def resolve_mvp_gohighlevel_context(
        payload: _MvpGoHighLevelContextPayload,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        try:
            user_data = runtime.decrypt_gohighlevel_user_context(
                encrypted_data=payload.encrypted_data,
            )
        except ValidationError as error:
            return _json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return _json_error(
                503,
                str(error),
                code=getattr(error, "code", "GHL_CONTEXT_DECRYPT_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        resolved_context = _extract_gohighlevel_user_context_fields(user_data)
        if not resolved_context["location_id"]:
            return _json_error(
                400,
                "The decrypted GoHighLevel context does not include activeLocation.",
                code="GHL_CONTEXT_LOCATION_MISSING",
                hint=(
                    "Open the app from a sub-account/location custom page. Agency context "
                    "does not include activeLocation."
                ),
                details={
                    "context_type": resolved_context["type"],
                    "has_user_id": bool(resolved_context["user_id"]),
                },
            )

        log_persistent_event(
            "mvp.gohighlevel_context_resolved",
            request_id=_get_request_id(request),
            client=_format_client(request),
            location_id=resolved_context["location_id"],
            user_id=resolved_context["user_id"],
            context_type=resolved_context["type"],
        )
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "source": "ghl-sso-decrypted",
                **resolved_context,
                "user_data": user_data,
            },
        )

    @app.post("/mvp/gohighlevel/session", tags=["MVP"])
    async def create_mvp_gohighlevel_session(
        payload: _MvpGoHighLevelSessionPayload,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        record = runtime.get_ghl_connection_by_location(location_id=payload.location_id)
        connected = record is not None and bool(record.access_token.strip())
        log_persistent_event(
            "mvp.gohighlevel_session_checked",
            request_id=_get_request_id(request),
            client=_format_client(request),
            location_id=payload.location_id,
            user_id=payload.user_id,
            connected=connected,
        )
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "location_id": payload.location_id,
                "user_id": payload.user_id,
                "connected": connected,
                "has_token": connected,
                "agency_id": record.agency_id if record is not None else None,
            },
        )

    @app.post("/mvp/gohighlevel/test", tags=["MVP"])
    async def test_mvp_gohighlevel_connection(
        payload: _MvpGoHighLevelLocationPayload,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        record = runtime.get_ghl_connection_by_location(location_id=payload.location_id)
        if record is None or not record.access_token.strip():
            return _json_error(
                404,
                "No GoHighLevel connection is saved for this location.",
                code="GHL_CONNECTION_NOT_FOUND",
                hint="Configure a GoHighLevel connection for the agency that owns this location.",
                details={"location_id": payload.location_id},
            )
        try:
            accounts = runtime.test_gohighlevel_connection(
                location_id=record.location_id,
                access_token=record.access_token,
            )
        except ApplicationError as error:
            return _json_error(
                502,
                str(error),
                code=getattr(error, "code", "GHL_CONNECTION_TEST_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        account_payload = [
            {
                "id": account.id,
                "name": account.name,
                "platform": account.platform,
                "account_type": account.account_type,
                "is_expired": account.is_expired,
            }
            for account in accounts
        ]
        log_persistent_event(
            "mvp.gohighlevel_connection_tested",
            request_id=_get_request_id(request),
            client=_format_client(request),
            location_id=payload.location_id,
            account_count=len(account_payload),
        )
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "location_id": payload.location_id,
                "account_count": len(account_payload),
                "accounts": account_payload,
            },
        )

    @app.get(
        f"{application.admin_access_policy.base_path}/wordpress-sources",
        tags=["Admin"],
    )
    async def list_admin_wordpress_sources(request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error

        sources = runtime.wordpress_source_admin_service.list_sources()
        request_id = _get_request_id(request)
        log_persistent_event(
            "admin.wordpress_sources_listed",
            request_id=request_id,
            client=_format_client(request),
            source_count=len(sources),
        )
        return JSONResponse(
            status_code=200,
            content={
                "items": [_serialize_wordpress_source_details(source) for source in sources],
                "count": len(sources),
            },
        )

    @app.get(
        f"{application.admin_access_policy.base_path}/wordpress-sources/{{site_id}}",
        tags=["Admin"],
    )
    async def get_admin_wordpress_source(site_id: str, request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error

        try:
            source = runtime.wordpress_source_admin_service.get_source(site_id=site_id)
        except ValidationError as error:
            _log_admin_failure(
                request=request,
                action="wordpress_source.get",
                error=error,
                title="Admin WordPress Source Lookup Rejected",
                persistent_event_type="admin.wordpress_source_lookup_rejected",
                tone="warning",
                site_id=site_id,
            )
            return _json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )

        if source is None:
            return _json_error(
                404,
                "The wordpress source does not exist.",
                code="ADMIN_SOURCE_NOT_FOUND",
                hint="Create the site first with the admin provisioning endpoint.",
                details={"site_id": site_id},
            )

        log_persistent_event(
            "admin.wordpress_source_loaded",
            request_id=_get_request_id(request),
            client=_format_client(request),
            site_id=source.site_id,
            agency_id=source.agency_id,
            wordpress_source_id=source.wordpress_source_id,
        )
        return JSONResponse(
            status_code=200,
            content={"source": _serialize_wordpress_source_details(source)},
        )

    @app.put(
        f"{application.admin_access_policy.base_path}/wordpress-sources/{{site_id}}",
        tags=["Admin"],
    )
    async def upsert_admin_wordpress_source(
        site_id: str,
        payload: _AdminWordPressSourceUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error

        request_id = _get_request_id(request)
        try:
            result = runtime.wordpress_source_admin_service.upsert_source(
                UpsertWordPressSourceRequest(
                    site_id=site_id,
                    source_name=payload.source_name,
                    agency_id=payload.agency_id,
                    agency_name=payload.agency_name,
                    agency_slug=payload.agency_slug,
                    agency_timezone=payload.agency_timezone,
                    agency_status=payload.agency_status,
                    site_url=payload.site_url,
                    normalized_host=payload.normalized_host,
                    source_status=payload.source_status,
                    webhook_secret=payload.webhook_secret,
                    update_webhook_secret="webhook_secret" in payload.model_fields_set,
                )
            )
        except ResourceNotFoundError as error:
            _log_admin_failure(
                request=request,
                action="wordpress_source.upsert",
                error=error,
                title="Admin WordPress Source Upsert Failed",
                persistent_event_type="admin.wordpress_source_upsert_failed",
                tone="warning",
                site_id=site_id,
            )
            return _json_error(
                404,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ValidationError as error:
            _log_admin_failure(
                request=request,
                action="wordpress_source.upsert",
                error=error,
                title="Admin WordPress Source Upsert Rejected",
                persistent_event_type="admin.wordpress_source_upsert_rejected",
                tone="warning",
                site_id=site_id,
            )
            return _json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            _log_admin_failure(
                request=request,
                action="wordpress_source.upsert",
                error=error,
                title="Admin WordPress Source Upsert Failed",
                persistent_event_type="admin.wordpress_source_upsert_failed",
                tone="failure",
                site_id=site_id,
            )
            return _json_error(
                500,
                str(error),
                code=getattr(error, "code", "ADMIN_SOURCE_UPSERT_FAILED"),
                hint=error.hint,
                details={"context": error.context} if getattr(error, "context", None) else None,
            )
        except Exception as error:
            _log_admin_failure(
                request=request,
                action="wordpress_source.upsert",
                error=error,
                title="Admin WordPress Source Upsert Failed",
                persistent_event_type="admin.wordpress_source_upsert_failed",
                tone="failure",
                site_id=site_id,
            )
            return _json_error(
                500,
                "Failed to provision the wordpress source.",
                code="ADMIN_SOURCE_UPSERT_FAILED",
                hint="Check the admin request_id in the logs and retry after fixing the underlying error.",
                details={"request_id": request_id, "site_id": site_id},
            )

        status_code = 201 if result.created_source else 200
        log_persistent_event(
            "admin.wordpress_source_upserted",
            request_id=request_id,
            client=_format_client(request),
            site_id=result.source.site_id,
            agency_id=result.source.agency_id,
            wordpress_source_id=result.source.wordpress_source_id,
            created_agency=result.created_agency,
            updated_agency=result.updated_agency,
            created_source=result.created_source,
            updated_source=result.updated_source,
        )
        logger.info(
            format_console_block(
                "Admin WordPress Source Upserted",
                format_detail_line("Request ID", request_id or "<unknown>"),
                format_detail_line("Site ID", result.source.site_id),
                format_detail_line("Agency ID", result.source.agency_id),
                format_detail_line("WordPress source ID", result.source.wordpress_source_id),
                format_detail_line("Created agency", "Yes" if result.created_agency else "No"),
                format_detail_line("Updated agency", "Yes" if result.updated_agency else "No"),
                format_detail_line("Created source", "Yes" if result.created_source else "No"),
                format_detail_line("Updated source", "Yes" if result.updated_source else "No"),
            )
        )
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "created" if result.created_source else "updated",
                "created_agency": result.created_agency,
                "updated_agency": result.updated_agency,
                "created_source": result.created_source,
                "updated_source": result.updated_source,
                "source": _serialize_wordpress_source_details(result.source),
            },
        )

    # ── Admin: agencies ─────────────────────────────────────────────────
    @app.get(
        f"{application.admin_access_policy.base_path}/agencies",
        tags=["Admin"],
    )
    async def list_admin_agencies(request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error

        agencies = runtime.list_agencies()
        items = []
        for agency in agencies:
            sources = runtime.list_sources_for_agency(agency_id=agency.agency_id)
            ghl = runtime.get_ghl_connection_by_agency(agency_id=agency.agency_id)
            profile = runtime.get_reel_profile(agency_id=agency.agency_id)
            items.append(_serialize_agency_summary(agency, sources, ghl, profile))
        return JSONResponse(
            status_code=200,
            content={"items": items, "count": len(items)},
        )

    @app.post(
        f"{application.admin_access_policy.base_path}/agencies",
        tags=["Admin"],
    )
    async def create_admin_agency(
        payload: _AdminAgencyCreatePayload,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error

        from uuid import uuid4 as _uuid4

        slug = _slugify_admin(payload.slug or payload.name) or _slugify_admin(
            f"agency-{_uuid4().hex[:8]}"
        )
        try:
            agency_id = runtime.create_agency(
                agency_id=str(_uuid4()),
                name=payload.name,
                slug=slug,
                timezone=payload.timezone or "Europe/Dublin",
                status=(payload.status or "active").lower(),
            )
        except ApplicationError as error:
            return _json_error(
                500,
                str(error),
                code=getattr(error, "code", "ADMIN_AGENCY_CREATE_FAILED"),
                hint=error.hint,
            )

        agency = runtime.get_agency(agency_id=agency_id)
        return JSONResponse(
            status_code=201,
            content={"status": "created", "agency": _serialize_agency(agency)},
        )

    @app.get(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}",
        tags=["Admin"],
    )
    async def get_admin_agency(agency_id: str, request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error

        agency = runtime.get_agency(agency_id=agency_id)
        if agency is None:
            return _json_error(
                404,
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                details={"agency_id": agency_id},
            )
        sources = runtime.list_sources_for_agency(agency_id=agency_id)
        ghl = runtime.get_ghl_connection_by_agency(agency_id=agency_id)
        profile = runtime.get_reel_profile(agency_id=agency_id)
        return JSONResponse(
            status_code=200,
            content={
                "agency": _serialize_agency(agency),
                "sources": [_serialize_wordpress_source_details(source) for source in sources],
                "ghl_connection": ghl.to_public_dict() if ghl is not None else None,
                "reel_profile": profile.to_public_dict() if profile is not None else None,
            },
        )

    @app.patch(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}",
        tags=["Admin"],
    )
    async def update_admin_agency(
        agency_id: str,
        payload: _AdminAgencyUpdatePayload,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error

        agency = runtime.get_agency(agency_id=agency_id)
        if agency is None:
            return _json_error(
                404,
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                details={"agency_id": agency_id},
            )

        runtime.update_agency(
            agency_id=agency_id,
            name=payload.name if payload.name is not None else agency.name,
            slug=(
                _slugify_admin(payload.slug or payload.name or agency.slug)
                if (payload.slug is not None or payload.name is not None)
                else agency.slug
            ),
            timezone=payload.timezone if payload.timezone is not None else agency.timezone,
            status=(payload.status or agency.status).lower(),
        )
        updated = runtime.get_agency(agency_id=agency_id)
        return JSONResponse(
            status_code=200,
            content={"status": "updated", "agency": _serialize_agency(updated)},
        )

    @app.delete(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}",
        tags=["Admin"],
    )
    async def delete_admin_agency(agency_id: str, request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error
        deleted = runtime.delete_agency(agency_id=agency_id)
        if not deleted:
            return _json_error(
                404,
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                details={"agency_id": agency_id},
            )
        return JSONResponse(
            status_code=200,
            content={"status": "deleted", "agency_id": agency_id},
        )

    # ── Admin: sources for an agency ────────────────────────────────────
    @app.post(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/sources",
        tags=["Admin"],
    )
    async def upsert_admin_agency_source(
        agency_id: str,
        payload: _AdminAgencySourceUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error

        agency = runtime.get_agency(agency_id=agency_id)
        if agency is None:
            return _json_error(
                404,
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                details={"agency_id": agency_id},
            )

        try:
            result = runtime.wordpress_source_admin_service.upsert_source(
                UpsertWordPressSourceRequest(
                    site_id=payload.site_id,
                    source_name=payload.source_name,
                    agency_id=agency_id,
                    agency_name=agency.name,
                    agency_slug=agency.slug,
                    agency_timezone=agency.timezone,
                    agency_status=agency.status,
                    site_url=payload.site_url,
                    normalized_host=payload.normalized_host,
                    source_status=payload.source_status,
                    webhook_secret=payload.webhook_secret,
                    update_webhook_secret="webhook_secret"
                    in payload.model_fields_set,
                )
            )
        except ValidationError as error:
            return _json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return _json_error(
                500,
                str(error),
                code=getattr(error, "code", "ADMIN_SOURCE_UPSERT_FAILED"),
                hint=error.hint,
            )

        status_code = 201 if result.created_source else 200
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "created" if result.created_source else "updated",
                "source": _serialize_wordpress_source_details(result.source),
            },
        )

    @app.delete(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/sources/{{wordpress_source_id}}",
        tags=["Admin"],
    )
    async def delete_admin_agency_source(
        agency_id: str,
        wordpress_source_id: str,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error

        deleted = runtime.delete_wordpress_source(wordpress_source_id=wordpress_source_id)
        if not deleted:
            return _json_error(
                404,
                "The wordpress source does not exist.",
                code="ADMIN_SOURCE_NOT_FOUND",
                details={
                    "agency_id": agency_id,
                    "wordpress_source_id": wordpress_source_id,
                },
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "deleted",
                "agency_id": agency_id,
                "wordpress_source_id": wordpress_source_id,
            },
        )

    # ── Admin: GHL connection per agency ────────────────────────────────
    @app.put(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/ghl-connection",
        tags=["Admin"],
    )
    async def upsert_admin_agency_ghl_connection(
        agency_id: str,
        payload: _AdminGhlConnectionUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error

        agency = runtime.get_agency(agency_id=agency_id)
        if agency is None:
            return _json_error(
                404,
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                details={"agency_id": agency_id},
            )

        try:
            record = runtime.upsert_ghl_connection(
                agency_id=agency_id,
                location_id=payload.location_id,
                user_id=payload.user_id or "manual",
                access_token=payload.access_token,
                refresh_token=payload.refresh_token or "",
                expires_at=payload.expires_at or "",
                status=(payload.status or "active").lower(),
            )
        except ValidationError as error:
            return _json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return _json_error(
                500,
                str(error),
                code=getattr(error, "code", "GHL_CONNECTION_SAVE_FAILED"),
                hint=error.hint,
            )

        return JSONResponse(
            status_code=200,
            content={"status": "saved", "ghl_connection": record.to_public_dict()},
        )

    @app.delete(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/ghl-connection",
        tags=["Admin"],
    )
    async def delete_admin_agency_ghl_connection(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error
        deleted = runtime.delete_ghl_connection(agency_id=agency_id)
        if not deleted:
            return _json_error(
                404,
                "No GoHighLevel connection saved for this agency.",
                code="GHL_CONNECTION_NOT_FOUND",
                details={"agency_id": agency_id},
            )
        return JSONResponse(
            status_code=200,
            content={"status": "deleted", "agency_id": agency_id},
        )

    @app.post(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/ghl-connection/test",
        tags=["Admin"],
    )
    async def test_admin_agency_ghl_connection(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error
        record = runtime.get_ghl_connection_by_agency(agency_id=agency_id)
        if record is None or not record.access_token.strip():
            return _json_error(
                404,
                "No GoHighLevel connection saved for this agency.",
                code="GHL_CONNECTION_NOT_FOUND",
                details={"agency_id": agency_id},
            )
        try:
            accounts = runtime.test_gohighlevel_connection(
                location_id=record.location_id,
                access_token=record.access_token,
            )
        except ApplicationError as error:
            return _json_error(
                502,
                str(error),
                code=getattr(error, "code", "GHL_CONNECTION_TEST_FAILED"),
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        accounts_payload = [
            {
                "id": account.id,
                "name": account.name,
                "platform": account.platform,
                "account_type": account.account_type,
                "is_expired": account.is_expired,
            }
            for account in accounts
        ]
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "agency_id": agency_id,
                "location_id": record.location_id,
                "account_count": len(accounts_payload),
                "accounts": accounts_payload,
            },
        )

    # ── Admin: reel profile per agency ──────────────────────────────────
    @app.get(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/reel-profile",
        tags=["Admin"],
    )
    async def get_admin_agency_reel_profile(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error
        if runtime.get_agency(agency_id=agency_id) is None:
            return _json_error(
                404,
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                details={"agency_id": agency_id},
            )
        profile = runtime.get_reel_profile(agency_id=agency_id)
        return JSONResponse(
            status_code=200,
            content={"reel_profile": profile.to_public_dict() if profile else None},
        )

    @app.put(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/reel-profile",
        tags=["Admin"],
    )
    async def upsert_admin_agency_reel_profile(
        agency_id: str,
        payload: _AdminReelProfileUpsertPayload,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error
        if runtime.get_agency(agency_id=agency_id) is None:
            return _json_error(
                404,
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                details={"agency_id": agency_id},
            )

        try:
            record = runtime.upsert_reel_profile(
                agency_id=agency_id,
                name=payload.name,
                platforms=payload.platforms,
                duration_seconds=payload.duration_seconds,
                music_id=payload.music_id,
                intro_enabled=payload.intro_enabled,
                logo_position=payload.logo_position,
                brand_primary_color=payload.brand_primary_color,
                brand_secondary_color=payload.brand_secondary_color,
                caption_template=payload.caption_template,
                approval_required=payload.approval_required,
                extra_settings=payload.extra_settings,
            )
        except ValidationError as error:
            return _json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            return _json_error(
                500,
                str(error),
                code=getattr(error, "code", "REEL_PROFILE_SAVE_FAILED"),
                hint=error.hint,
            )
        return JSONResponse(
            status_code=200,
            content={"status": "saved", "reel_profile": record.to_public_dict()},
        )

    # ── Admin: agency content surfaces ──────────────────────────────────
    @app.get(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/reels",
        tags=["Admin"],
    )
    async def list_admin_agency_reels(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error
        agency = runtime.get_agency(agency_id=agency_id)
        if agency is None:
            return _json_error(
                404,
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                details={"agency_id": agency_id},
            )

        try:
            limit = int(request.query_params.get("limit") or 50)
        except ValueError:
            limit = 50
        items = runtime.list_agency_reels(agency_id=agency_id, limit=limit)
        return JSONResponse(
            status_code=200,
            content={
                "items": [_serialize_agency_reel(item) for item in items],
                "count": len(items),
            },
        )

    @app.get(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/social-accounts",
        tags=["Admin"],
    )
    async def list_admin_agency_social_accounts(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error
        record = runtime.get_ghl_connection_by_agency(agency_id=agency_id)
        if record is None or not record.access_token.strip():
            return JSONResponse(
                status_code=200,
                content={
                    "ok": False,
                    "agency_id": agency_id,
                    "connected": False,
                    "items": [],
                    "count": 0,
                    "reason": "GHL_CONNECTION_NOT_FOUND",
                },
            )
        try:
            accounts = runtime.test_gohighlevel_connection(
                location_id=record.location_id,
                access_token=record.access_token,
            )
        except ApplicationError as error:
            return JSONResponse(
                status_code=200,
                content={
                    "ok": False,
                    "agency_id": agency_id,
                    "connected": True,
                    "location_id": record.location_id,
                    "items": [],
                    "count": 0,
                    "reason": getattr(error, "code", "GHL_CONNECTION_TEST_FAILED"),
                    "error": str(error),
                },
            )
        items = [
            {
                "id": account.id,
                "name": account.name,
                "platform": account.platform,
                "account_type": account.account_type,
                "is_expired": account.is_expired,
            }
            for account in accounts
        ]
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "agency_id": agency_id,
                "connected": True,
                "location_id": record.location_id,
                "count": len(items),
                "items": items,
            },
        )

    @app.get(
        f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/music-tracks",
        tags=["Admin"],
    )
    async def list_admin_agency_music_tracks(
        agency_id: str,
        request: Request,
    ) -> JSONResponse:
        runtime = _get_runtime(request)
        authorization_error = _authorize_admin_request(request, runtime)
        if authorization_error is not None:
            return authorization_error
        if runtime.get_agency(agency_id=agency_id) is None:
            return _json_error(
                404,
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                details={"agency_id": agency_id},
            )
        # The music library backing table is not implemented yet; the API surface
        # is wired so the frontend can render an empty state instead of mock data.
        return JSONResponse(
            status_code=200,
            content={
                "items": [],
                "count": 0,
                "agency_id": agency_id,
                "implemented": False,
                "message": "Music library is not yet backed by a database table.",
            },
        )

    @app.post(application.path)
    async def receive_property_webhook(request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        site_id = _get_header_value(request, runtime.site_id_header)
        timestamp = request.headers.get(runtime.timestamp_header)
        signature = request.headers.get(runtime.signature_header)

        content_type = request.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            return _json_error(
                400,
                "Content-Type must be application/json.",
                code="INVALID_CONTENT_TYPE",
                hint="Configure the WordPress sender to post raw JSON with Content-Type: application/json.",
                details={"received_content_type": content_type or "<empty>"},
            )

        content_length = _parse_content_length(request.headers.get("Content-Length"))
        if content_length is None:
            return _json_error(
                400,
                "Invalid Content-Length header.",
                code="INVALID_CONTENT_LENGTH",
                hint="Send a numeric Content-Length header or let the HTTP client populate it automatically.",
            )
        if content_length > runtime.max_payload_bytes:
            return _json_error(
                413,
                "Request body is too large.",
                code="PAYLOAD_TOO_LARGE",
                hint="Reduce the payload size or increase WEBHOOK_MAX_PAYLOAD_BYTES on the API host.",
                details={"max_payload_bytes": runtime.max_payload_bytes},
            )

        raw_body = await request.body()
        if len(raw_body) > runtime.max_payload_bytes:
            return _json_error(
                413,
                "Request body is too large.",
                code="PAYLOAD_TOO_LARGE",
                hint="Reduce the payload size or increase WEBHOOK_MAX_PAYLOAD_BYTES on the API host.",
                details={"max_payload_bytes": runtime.max_payload_bytes},
            )

        payload, payload_error = _parse_webhook_payload(raw_body)
        if payload_error is not None:
            return _json_error(400, payload_error)

        if not site_id:
            site_id = _resolve_site_id(payload)

        if not site_id:
            return _json_error(
                400,
                "The webhook site_id could not be resolved.",
                code="SITE_ID_REQUIRED",
                hint=(
                    f"Send the {runtime.site_id_header} header or include a property link/guid "
                    "whose hostname matches the source site."
                ),
            )
        if not runtime.security_disabled and (not timestamp or not signature):
            missing_headers = []
            if not timestamp:
                missing_headers.append(runtime.timestamp_header)
            if not signature:
                missing_headers.append(runtime.signature_header)
            return _json_error(
                400,
                "Missing required webhook security headers.",
                code="MISSING_SECURITY_HEADERS",
                hint="Send both timestamp and signature headers when webhook security is enabled.",
                details={"missing_headers": missing_headers},
            )

        is_authenticated, auth_message, auth_hint = runtime.authenticate_with_details(
            site_id=site_id,
            location_id="",
            access_token="",
            timestamp=timestamp or "",
            signature=signature or "",
            raw_body=raw_body,
        )
        if not is_authenticated:
            logger.warning(
                format_console_block(
                    "Webhook Authentication Failed",
                    format_detail_line("Client", _format_client(request)),
                    format_detail_line("Site ID", site_id or "<unresolved>"),
                    format_detail_line("Reason", auth_message or "Invalid webhook credentials."),
                    format_detail_line("Hint", auth_hint),
                )
            )
            log_persistent_event(
                "webhook.authentication_failed",
                site_id=site_id,
                client=_format_client(request),
                reason=auth_message or "Invalid webhook credentials.",
            )
            return _json_error(
                401,
                "Invalid webhook credentials.",
                code="INVALID_WEBHOOK_CREDENTIALS",
                hint="Check the webhook signing secret, timestamp, and required security headers.",
                details={"site_id": site_id},
            )

        property_id = _extract_property_id(payload)
        raw_payload_hash = build_raw_payload_hash(raw_body)
        request_id = _get_request_id(request)
        dispatcher_accepting_jobs = runtime.dispatcher.is_accepting_jobs()

        if not dispatcher_accepting_jobs:
            logger.warning(
                format_console_block(
                    "Webhook Accepted While Dispatcher Paused",
                    format_detail_line("Request ID", request_id or "<unknown>"),
                    format_detail_line("Client", _format_client(request)),
                    format_detail_line("Site ID", site_id),
                    format_detail_line("Property ID", property_id),
                    "The webhook will still be enqueued in the durable PostgreSQL queue.",
                )
            )
            log_persistent_event(
                "webhook.dispatcher_paused",
                request_id=request_id,
                site_id=site_id,
                property_id=property_id,
                client=_format_client(request),
                dispatcher_accepting_jobs=dispatcher_accepting_jobs,
            )

        try:
            tenant_context = runtime.acceptance_service.tenant_resolver.resolve(site_id=site_id)
            ghl_connection = runtime.require_ghl_connection_for_agency(
                agency_id=tenant_context.agency_id,
            )
            reel_profile = runtime.get_reel_profile(agency_id=tenant_context.agency_id)
            resolved_platforms = tuple(
                reel_profile.platforms
                if reel_profile is not None and reel_profile.platforms
                else SOCIAL_PUBLISHING_DEFAULT_PLATFORMS
            )
            accepted_delivery = runtime.accept_webhook_delivery(
                site_id=site_id,
                property_id=property_id,
                raw_payload_hash=raw_payload_hash,
                payload=payload,
                publish_context=SocialPublishContext(
                    provider="gohighlevel",
                    location_id=ghl_connection.location_id,
                    access_token=ghl_connection.access_token,
                    platforms=resolved_platforms,
                ),
            )
        except ResourceNotFoundError as error:
            _log_webhook_acceptance_failure(
                request=request,
                request_id=request_id,
                site_id=site_id,
                property_id=property_id,
                dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                error=error,
                title="Webhook Acceptance Rejected",
                persistent_event_type="webhook.acceptance_rejected",
                tone="warning",
            )
            status_code = 404 if error.code in {"UNKNOWN_WORDPRESS_SITE", "GHL_TOKEN_NOT_FOUND"} else 400
            return _json_error(
                status_code,
                str(error),
                code=error.code,
                hint=error.hint,
                details=_build_acceptance_error_details(
                    request_id=request_id,
                    dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                    context=error.context,
                ),
            )
        except ValidationError as error:
            _log_webhook_acceptance_failure(
                request=request,
                request_id=request_id,
                site_id=site_id,
                property_id=property_id,
                dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                error=error,
                title="Webhook Acceptance Rejected",
                persistent_event_type="webhook.acceptance_rejected",
                tone="warning",
            )
            return _json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details=_build_acceptance_error_details(
                    request_id=request_id,
                    dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                    context=error.context,
                ),
            )
        except ApplicationError as error:
            _log_webhook_acceptance_failure(
                request=request,
                request_id=request_id,
                site_id=site_id,
                property_id=property_id,
                dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                error=error,
                title="Webhook Acceptance Failed",
                persistent_event_type="webhook.acceptance_failed",
                tone="failure",
            )
            return _json_error(
                500,
                str(error),
                code=getattr(error, "code", "WEBHOOK_ACCEPTANCE_FAILED"),
                hint=error.hint,
                details=_build_acceptance_error_details(
                    request_id=request_id,
                    dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                    context=error.context,
                ),
            )
        except Exception as error:
            _log_webhook_acceptance_failure(
                request=request,
                request_id=request_id,
                site_id=site_id,
                property_id=property_id,
                dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                error=error,
                title="Webhook Acceptance Failed",
                persistent_event_type="webhook.acceptance_failed",
                tone="failure",
            )
            return _json_error(
                500,
                "Failed to accept webhook delivery.",
                code="WEBHOOK_ACCEPTANCE_FAILED",
                hint=(
                    "Check the dated log folders under logs/MM-YYYY/DD-MM-YYYY for errors.log, "
                    "warnings-errors.log, and audit.jsonl with the request_id and underlying "
                    "acceptance failure."
                ),
                details=_build_acceptance_error_details(
                    request_id=request_id,
                    dispatcher_accepting_jobs=dispatcher_accepting_jobs,
                ),
            )

        if accepted_delivery.tenant_auto_provisioned:
            logger.warning(
                format_console_block(
                    "Webhook Site Auto-Provisioned For Testing",
                    format_detail_line("Request ID", request_id or "<unknown>"),
                    format_detail_line("Site ID", site_id),
                    format_detail_line("Event ID", accepted_delivery.event_id),
                    format_detail_line("Job ID", accepted_delivery.job_id),
                    "A placeholder tenant was created automatically so the webhook could be queued.",
                )
            )
            log_persistent_event(
                "webhook.site_auto_provisioned_for_testing",
                request_id=request_id,
                event_id=accepted_delivery.event_id,
                job_id=accepted_delivery.job_id,
                site_id=site_id,
                property_id=property_id,
            )

        logger.info(
            format_console_block(
                "Webhook Accepted",
                format_detail_line("Request ID", request_id or "<unknown>"),
                format_detail_line("Event ID", accepted_delivery.event_id),
                format_detail_line("Job ID", accepted_delivery.job_id),
                format_detail_line("Site ID", site_id),
                format_detail_line("Property ID", property_id),
                format_detail_line(
                    "Dispatcher accepting jobs",
                    "Yes" if dispatcher_accepting_jobs else "No",
                ),
                format_detail_line(
                    "Site auto-provisioned for testing",
                    "Yes" if accepted_delivery.tenant_auto_provisioned else "No",
                ),
                "The payload was queued for background processing.",
            )
        )
        log_persistent_event(
            "webhook.accepted",
            request_id=request_id,
            event_id=accepted_delivery.event_id,
            job_id=accepted_delivery.job_id,
            site_id=site_id,
            property_id=property_id,
            raw_payload_hash=raw_payload_hash,
            dispatcher_accepting_jobs=dispatcher_accepting_jobs,
            tenant_auto_provisioned=accepted_delivery.tenant_auto_provisioned,
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "event_id": accepted_delivery.event_id,
                "job_id": accepted_delivery.job_id,
                "site_id": site_id,
                "property_id": property_id,
                "site_auto_provisioned": accepted_delivery.tenant_auto_provisioned,
            },
        )

    @app.post("/videos/scripted/render")
    async def render_scripted_video(request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        content_type = request.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            return _json_error(
                400,
                "Content-Type must be application/json.",
                code="INVALID_CONTENT_TYPE",
                hint="Post the scripted render manifest as raw JSON with Content-Type: application/json.",
                details={"received_content_type": content_type or "<empty>"},
            )

        content_length = _parse_content_length(request.headers.get("Content-Length"))
        if content_length is None:
            return _json_error(
                400,
                "Invalid Content-Length header.",
                code="INVALID_CONTENT_LENGTH",
                hint="Send a numeric Content-Length header or let the HTTP client populate it automatically.",
            )
        if content_length > runtime.max_payload_bytes:
            return _json_error(
                413,
                "Request body is too large.",
                code="PAYLOAD_TOO_LARGE",
                hint="Reduce the payload size or increase WEBHOOK_MAX_PAYLOAD_BYTES on the API host.",
                details={"max_payload_bytes": runtime.max_payload_bytes},
            )

        raw_body = await request.body()
        if len(raw_body) > runtime.max_payload_bytes:
            return _json_error(
                413,
                "Request body is too large.",
                code="PAYLOAD_TOO_LARGE",
                hint="Reduce the payload size or increase WEBHOOK_MAX_PAYLOAD_BYTES on the API host.",
                details={"max_payload_bytes": runtime.max_payload_bytes},
            )

        payload, payload_error = _parse_json_object_payload(raw_body)
        if payload_error is not None:
            return _json_error(
                400,
                payload_error,
                code="INVALID_SCRIPTED_RENDER_PAYLOAD",
                hint="Send a single JSON object describing the scripted reel request.",
            )

        try:
            result = runtime.render_scripted_video(payload=payload)
        except ValidationError as error:
            return _json_error(
                400,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ResourceNotFoundError as error:
            status_code = 404 if error.code == "PROPERTY_NOT_FOUND" else 400
            return _json_error(
                status_code,
                str(error),
                code=error.code,
                hint=error.hint,
                details={"context": error.context} if error.context else None,
            )
        except ApplicationError as error:
            logger.exception(
                "Scripted video render failed for %s",
                _format_client(request),
            )
            return _json_error(
                500,
                str(error),
                code=getattr(error, "code", "SCRIPTED_RENDER_ERROR"),
                hint=error.hint,
                details={"context": error.context} if getattr(error, "context", None) else None,
            )

        logger.info(
            format_console_block(
                "Scripted Video Rendered",
                format_detail_line("Render ID", result.render_id),
                format_detail_line("Site ID", result.site_id),
                format_detail_line("Property ID", result.source_property_id),
                format_detail_line("Video path", result.video_path),
            )
        )
        log_persistent_event(
            "scripted_video.rendered",
            render_id=result.render_id,
            site_id=result.site_id,
            property_id=result.source_property_id,
            video_path=result.video_path,
            manifest_path=result.manifest_path,
        )
        return JSONResponse(
            status_code=201,
            content={
                "status": "rendered",
                "render_id": result.render_id,
                "site_id": result.site_id,
                "source_property_id": result.source_property_id,
                "video_path": result.video_path,
                "manifest_path": result.manifest_path,
                "request_manifest_path": result.request_manifest_path,
            },
        )

    return app


def run_wordpress_webhook_server(
    workspace_dir: str | Path,
    *,
    dispatcher: JobDispatcher | None = None,
    database_locator: str | Path | None = DATABASE_URL,
    host: str = WEBHOOK_HOST,
    port: int = WEBHOOK_PORT,
) -> None:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise DependencyNotInstalledError(
            module_name="uvicorn",
            package_name="uvicorn[standard]",
            display_name="uvicorn",
            feature="running the FastAPI webhook server",
        ) from exc

    server = WordPressWebhookServer(
        workspace_dir,
        dispatcher=dispatcher,
        database_locator=database_locator,
        host=host,
    )
    logger.info(
        format_console_block(
            "Starting FastAPI Webhook Server",
            format_detail_line("Host", host),
            format_detail_line("Port", port),
            format_detail_line("Webhook path", server.runtime.path),
        )
    )
    uvicorn.run(
        server.app,
        host=host,
        port=port,
        http=VerboseAutoHTTPProtocol,
        proxy_headers=WEBHOOK_TRUST_PROXY_HEADERS,
        forwarded_allow_ips=WEBHOOK_FORWARDED_ALLOW_IPS,
        limit_concurrency=WEBHOOK_LIMIT_CONCURRENCY,
        log_level=logging.getLevelName(logger.getEffectiveLevel()).lower(),
        access_log=False,
        log_config=None,
        server_header=False,
    )


def _decrypt_gohighlevel_user_context(
    *,
    encrypted_data: str,
    shared_secret: str,
) -> dict[str, Any]:
    normalized_secret = str(shared_secret or "").strip()
    if not normalized_secret:
        raise ApplicationError(
            "GoHighLevel app shared secret is not configured.",
            hint=(
                "Set GO_HIGH_LEVEL_APP_SHARED_SECRET to the Marketplace app Shared Secret "
                "from Advanced Settings > Auth, then restart the backend."
            ),
        )

    try:
        encrypted_bytes = base64.b64decode(str(encrypted_data).strip(), validate=True)
    except Exception as exc:
        raise ValidationError(
            "The GoHighLevel user context payload is not valid base64.",
            code="GHL_CONTEXT_INVALID_BASE64",
            hint="Send the raw payload returned by REQUEST_USER_DATA_RESPONSE as encryptedData.",
            cause=exc,
        ) from exc

    if len(encrypted_bytes) <= 16 or not encrypted_bytes.startswith(b"Salted__"):
        raise ValidationError(
            "The GoHighLevel user context payload is not in the expected encrypted format.",
            code="GHL_CONTEXT_INVALID_FORMAT",
            hint="Send the encrypted string returned by HighLevel postMessage, not a parsed object.",
        )

    salt = encrypted_bytes[8:16]
    ciphertext = encrypted_bytes[16:]
    key, iv = _derive_cryptojs_key_and_iv(
        password=normalized_secret.encode("utf-8"),
        salt=salt,
    )

    try:
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
        parsed = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise ValidationError(
            "Failed to decrypt the GoHighLevel user context payload.",
            code="GHL_CONTEXT_DECRYPT_FAILED",
            hint=(
                "Verify GO_HIGH_LEVEL_APP_SHARED_SECRET matches the Shared Secret on the "
                "same Marketplace app/version that renders the custom page."
            ),
            cause=exc,
        ) from exc

    if not isinstance(parsed, dict):
        raise ValidationError(
            "The decrypted GoHighLevel user context payload is not a JSON object.",
            code="GHL_CONTEXT_INVALID_JSON",
        )

    return parsed


def _derive_cryptojs_key_and_iv(*, password: bytes, salt: bytes) -> tuple[bytes, bytes]:
    derived = b""
    previous = b""
    while len(derived) < 48:
        previous = hashlib.md5(previous + password + salt).digest()  # noqa: S324
        derived += previous
    return derived[:32], derived[32:48]


def _extract_gohighlevel_user_context_fields(user_data: dict[str, Any]) -> dict[str, str]:
    return {
        "location_id": str(
            user_data.get("activeLocation")
            or user_data.get("locationId")
            or user_data.get("location_id")
            or ""
        ).strip(),
        "user_id": str(
            user_data.get("userId")
            or user_data.get("user_id")
            or user_data.get("id")
            or ""
        ).strip(),
        "user_name": str(user_data.get("userName") or user_data.get("user_name") or "").strip(),
        "email": str(user_data.get("email") or "").strip(),
        "company_id": str(user_data.get("companyId") or user_data.get("company_id") or "").strip(),
        "type": str(user_data.get("type") or "").strip(),
        "role": str(user_data.get("role") or "").strip(),
    }


def _get_runtime(request: Request) -> WordPressWebhookApplication:
    return request.app.state.runtime  # type: ignore[return-value]


def _sanitize_headers_for_logging(headers: dict[str, str] | Any) -> dict[str, str]:
    normalized_headers: dict[str, str] = {}
    for key, value in headers.items():
        normalized_key = str(key)
        lowered_key = normalized_key.lower()
        normalized_headers[normalized_key] = (
            "<redacted>" if lowered_key in _SENSITIVE_HEADER_NAMES else str(value)
        )
    return normalized_headers


def _decode_body_for_logging(raw_body: bytes | None) -> str | None:
    if not raw_body:
        return None
    raw_text = raw_body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text
    redacted = _redact_sensitive_json_values(parsed)
    return json.dumps(redacted, ensure_ascii=False)


def _redact_sensitive_json_values(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if str(key).strip().lower() in _SENSITIVE_BODY_FIELDS
                else _redact_sensitive_json_values(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_json_values(item) for item in value]
    return value


def _extract_response_body(response: object) -> bytes | None:
    body = getattr(response, "body", None)
    if body is None:
        return None
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, str):
        return body.encode("utf-8", errors="replace")
    return str(body).encode("utf-8", errors="replace")


def _rebuild_request_with_body(request: Request, raw_body: bytes) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": raw_body, "more_body": False}

    return Request(request.scope, receive)


def _json_error(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    hint: str | None = None,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    payload: dict[str, object] = {"error": message}
    if code:
        payload["code"] = code
    if hint:
        payload["hint"] = hint
    if details:
        payload["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


def _serialize_agency_reel(item: object) -> dict[str, object]:
    return {
        "site_id": getattr(item, "site_id", ""),
        "source_property_id": getattr(item, "source_property_id", 0),
        "slug": getattr(item, "slug", ""),
        "title": getattr(item, "title", None),
        "link": getattr(item, "link", None),
        "price": getattr(item, "price", None),
        "property_status": getattr(item, "property_status", None),
        "property_type_label": getattr(item, "property_type_label", None),
        "property_area_label": getattr(item, "property_area_label", None),
        "property_county_label": getattr(item, "property_county_label", None),
        "bedrooms": getattr(item, "bedrooms", None),
        "bathrooms": getattr(item, "bathrooms", None),
        "featured_image_url": getattr(item, "featured_image_url", None),
        "agent_name": getattr(item, "agent_name", None),
        "workflow_state": getattr(item, "workflow_state", ""),
        "publish_status": getattr(item, "publish_status", ""),
        "render_status": getattr(item, "render_status", ""),
        "last_published_location_id": getattr(item, "last_published_location_id", ""),
        "current_revision_id": getattr(item, "current_revision_id", ""),
        "pipeline_updated_at": getattr(item, "pipeline_updated_at", ""),
        "pipeline_created_at": getattr(item, "pipeline_created_at", ""),
        "fetched_at": getattr(item, "fetched_at", ""),
        "revision_media_path": getattr(item, "revision_media_path", ""),
        "revision_metadata_path": getattr(item, "revision_metadata_path", ""),
        "revision_artifact_kind": getattr(item, "revision_artifact_kind", ""),
        "revision_created_at": getattr(item, "revision_created_at", ""),
    }


def _serialize_agency(agency: object) -> dict[str, object]:
    if agency is None:
        return {}
    return {
        "agency_id": getattr(agency, "agency_id", ""),
        "name": getattr(agency, "name", ""),
        "slug": getattr(agency, "slug", ""),
        "timezone": getattr(agency, "timezone", ""),
        "status": getattr(agency, "status", ""),
        "created_at": getattr(agency, "created_at", None),
        "updated_at": getattr(agency, "updated_at", None),
    }


def _serialize_agency_summary(
    agency: object,
    sources: tuple,
    ghl_connection: object | None,
    reel_profile: object | None,
) -> dict[str, object]:
    return {
        **_serialize_agency(agency),
        "source_count": len(sources),
        "sources": [_serialize_wordpress_source_details(source) for source in sources],
        "ghl_connection": (
            ghl_connection.to_public_dict() if ghl_connection is not None else None
        ),
        "reel_profile": (
            reel_profile.to_public_dict() if reel_profile is not None else None
        ),
    }


_ADMIN_SLUG_PATTERN = __import__("re").compile(r"[^a-z0-9]+")


def _slugify_admin(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return _ADMIN_SLUG_PATTERN.sub("-", raw).strip("-")


def _serialize_wordpress_source_details(source: object) -> dict[str, object]:
    return {
        "wordpress_source_id": getattr(source, "wordpress_source_id"),
        "site_id": getattr(source, "site_id"),
        "name": getattr(source, "name"),
        "site_url": getattr(source, "site_url"),
        "normalized_host": getattr(source, "normalized_host"),
        "status": getattr(source, "status"),
        "has_webhook_secret": getattr(source, "has_webhook_secret"),
        "last_event_at": getattr(source, "last_event_at"),
        "created_at": getattr(source, "created_at"),
        "updated_at": getattr(source, "updated_at"),
        "agency": {
            "agency_id": getattr(source, "agency_id"),
            "name": getattr(source, "agency_name"),
            "slug": getattr(source, "agency_slug"),
            "timezone": getattr(source, "agency_timezone"),
            "status": getattr(source, "agency_status"),
        },
    }


def _authorize_admin_request(
    request: Request,
    runtime: WordPressWebhookApplication,
) -> JSONResponse | None:
    policy = runtime.admin_access_policy
    request_id = _get_request_id(request)
    if not policy.enabled:
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=_format_client(request),
            reason="disabled",
            path=request.url.path,
        )
        return _json_error(
            404,
            "The admin API is disabled.",
            code="ADMIN_API_DISABLED",
            hint="Enable ADMIN_API_ENABLED before using the admin management endpoints.",
            details={"request_id": request_id, "path": request.url.path},
        )

    if policy.disable_auth_for_testing:
        logger.warning(
            format_console_block(
                "Admin Authentication Bypassed For Testing",
                format_detail_line("Request ID", request_id or "<unknown>"),
                format_detail_line("Client", _format_client(request)),
                format_detail_line("Path", request.url.path),
                "The request was allowed without verifying an admin bearer token.",
            )
        )
        log_persistent_event(
            "admin.authorization_bypassed_for_testing",
            request_id=request_id,
            client=_format_client(request),
            path=request.url.path,
        )
        return None

    if not policy.bearer_token:
        logger.warning(
            format_console_block(
                "Admin API Not Configured",
                format_detail_line("Request ID", request_id or "<unknown>"),
                format_detail_line("Client", _format_client(request)),
                format_detail_line("Path", request.url.path),
                "Set ADMIN_API_TOKEN before exposing the admin endpoints.",
            )
        )
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=_format_client(request),
            reason="not_configured",
            path=request.url.path,
        )
        return _json_error(
            503,
            "The admin API is not configured.",
            code="ADMIN_API_NOT_CONFIGURED",
            hint="Set ADMIN_API_TOKEN in the environment and restart the service before using the admin endpoints.",
            details={"request_id": request_id, "path": request.url.path},
        )

    provided_token = _extract_bearer_token(request.headers.get("Authorization"))
    if not provided_token:
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=_format_client(request),
            reason="missing_bearer_token",
            path=request.url.path,
        )
        return _json_error(
            401,
            "Admin authentication is required.",
            code="ADMIN_AUTH_REQUIRED",
            hint="Send Authorization: Bearer <ADMIN_API_TOKEN> on admin requests.",
            details={"request_id": request_id, "path": request.url.path},
        )

    if not secrets.compare_digest(provided_token, policy.bearer_token):
        logger.warning(
            format_console_block(
                "Admin Authentication Failed",
                format_detail_line("Request ID", request_id or "<unknown>"),
                format_detail_line("Client", _format_client(request)),
                format_detail_line("Path", request.url.path),
                "The provided admin bearer token is invalid.",
            )
        )
        log_persistent_event(
            "admin.authorization_failed",
            request_id=request_id,
            client=_format_client(request),
            reason="invalid_bearer_token",
            path=request.url.path,
        )
        return _json_error(
            401,
            "The admin bearer token is invalid.",
            code="INVALID_ADMIN_TOKEN",
            hint="Send the token configured in ADMIN_API_TOKEN using the Authorization header.",
            details={"request_id": request_id, "path": request.url.path},
        )

    return None


def _build_minimal_readiness_payload(readiness: dict[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {"status": "ready" if readiness.get("ready") else "not_ready"}
    if isinstance(readiness.get("dispatcher_accepting_jobs"), bool):
        payload["dispatcher_accepting_jobs"] = readiness["dispatcher_accepting_jobs"]
    return payload


def _build_acceptance_error_details(
    *,
    request_id: str | None,
    dispatcher_accepting_jobs: bool,
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    details: dict[str, object] = {
        "dispatcher_accepting_jobs": dispatcher_accepting_jobs,
    }
    if request_id:
        details["request_id"] = request_id
    if context:
        details["context"] = context
    return details


def _get_request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    if value in (None, ""):
        return None
    return str(value)


def _log_webhook_acceptance_failure(
    *,
    request: Request,
    request_id: str | None,
    site_id: str | None,
    property_id: int | None,
    dispatcher_accepting_jobs: bool,
    error: Exception,
    title: str,
    persistent_event_type: str,
    tone: str,
) -> None:
    error_details = extract_error_details(error)
    log_lines = [
        format_detail_line("Request ID", request_id or "<unknown>"),
        format_detail_line("Client", _format_client(request)),
        format_detail_line("Site ID", site_id or "<unresolved>"),
        format_detail_line("Property ID", property_id),
        format_detail_line("Dispatcher accepting jobs", "Yes" if dispatcher_accepting_jobs else "No"),
        format_detail_line("Reason", error_details.get("message") or error, highlight=True),
        format_detail_line("Error type", error_details.get("type")),
        format_detail_line("Error code", error_details.get("code")),
        format_detail_line("Hint", error_details.get("hint")),
        format_context_line(
            error_details.get("context")
            if isinstance(error_details.get("context"), dict)
            else None
        ),
    ]
    if tone == "warning":
        logger.warning(format_console_block(title, *log_lines, tone=tone))
    else:
        logger.error(format_console_block(title, *log_lines, tone=tone), exc_info=error)

    log_persistent_event(
        persistent_event_type,
        request_id=request_id,
        client=_format_client(request),
        site_id=site_id,
        property_id=property_id,
        dispatcher_accepting_jobs=dispatcher_accepting_jobs,
        error_type=error_details.get("type"),
        error_code=error_details.get("code"),
        error_message=error_details.get("message") or str(error),
        hint=error_details.get("hint"),
        context=(
            error_details.get("context")
            if isinstance(error_details.get("context"), dict)
            else None
        ),
    )


def _log_admin_failure(
    *,
    request: Request,
    action: str,
    error: Exception,
    title: str,
    persistent_event_type: str,
    tone: str,
    site_id: str | None = None,
) -> None:
    request_id = _get_request_id(request)
    error_details = extract_error_details(error)
    log_lines = [
        format_detail_line("Request ID", request_id or "<unknown>"),
        format_detail_line("Client", _format_client(request)),
        format_detail_line("Path", request.url.path),
        format_detail_line("Action", action),
        format_detail_line("Site ID", site_id or "<unresolved>"),
        format_detail_line("Reason", error_details.get("message") or error, highlight=True),
        format_detail_line("Error type", error_details.get("type")),
        format_detail_line("Error code", error_details.get("code")),
        format_detail_line("Hint", error_details.get("hint")),
        format_context_line(
            error_details.get("context")
            if isinstance(error_details.get("context"), dict)
            else None
        ),
    ]
    if tone == "warning":
        logger.warning(format_console_block(title, *log_lines, tone=tone))
    else:
        logger.error(format_console_block(title, *log_lines, tone=tone), exc_info=error)

    log_persistent_event(
        persistent_event_type,
        request_id=request_id,
        client=_format_client(request),
        path=request.url.path,
        action=action,
        site_id=site_id,
        error_type=error_details.get("type"),
        error_code=error_details.get("code"),
        error_message=error_details.get("message") or str(error),
        hint=error_details.get("hint"),
        context=(
            error_details.get("context")
            if isinstance(error_details.get("context"), dict)
            else None
        ),
    )


def _resolve_allowed_hosts(application: WordPressWebhookApplication) -> tuple[str, ...]:
    candidates: list[str] = []
    candidates.extend(application.allowed_hosts)
    candidates.extend(
        site_id
        for site_id in application.site_secrets
        if _looks_like_hostname(site_id)
    )
    candidates.extend(("127.0.0.1", "localhost"))

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized_candidate = _normalise_allowed_host(candidate)
        if not normalized_candidate:
            continue
        lowered = normalized_candidate.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(normalized_candidate)
    return tuple(normalized)


def _should_enable_docs(*, host: str, enable_docs: bool) -> bool:
    if enable_docs:
        return True
    return _is_local_docs_host(host)


def _is_local_docs_host(host: str) -> bool:
    normalized_host = str(host or "").strip().lower()
    if not normalized_host:
        return False
    if "://" in normalized_host:
        parsed = urlparse(normalized_host)
        normalized_host = parsed.hostname or parsed.path or ""
    if normalized_host.startswith("[") and normalized_host.endswith("]"):
        normalized_host = normalized_host[1:-1]
    return normalized_host in {"127.0.0.1", "localhost", "::1"}


def _normalise_allowed_host(value: str) -> str | None:
    raw_value = str(value or "").strip().lower()
    if not raw_value:
        return None
    if raw_value == "*":
        return raw_value
    if "://" in raw_value:
        parsed = urlparse(raw_value)
        raw_value = parsed.hostname or parsed.path or ""
    else:
        raw_value = raw_value.split("/", 1)[0]
        if raw_value.count(":") == 1 and raw_value not in {"localhost", "127.0.0.1"}:
            raw_value = raw_value.split(":", 1)[0]
    return raw_value or None


def _looks_like_hostname(value: str) -> bool:
    normalized_value = _normalise_allowed_host(value)
    if not normalized_value:
        return False
    return (
        normalized_value in {"localhost", "127.0.0.1"}
        or normalized_value.startswith("*.")
        or "." in normalized_value
    )


def _format_client(request: Request) -> str:
    if request.client is None:
        return "<unknown>"
    return f"{request.client.host}:{request.client.port}"


def _parse_content_length(raw_value: str | None) -> int | None:
    if raw_value is None:
        return 0
    try:
        content_length = int(raw_value)
    except ValueError:
        return None
    return max(content_length, 0)


def _extract_property_id(payload: dict[str, Any]) -> int | None:
    value = payload.get("id")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _get_header_value(request: Request, *names: str) -> str | None:
    for name in names:
        value = request.headers.get(name)
        if value:
            return value
    return None


def _extract_bearer_token(header_value: str | None) -> str | None:
    normalized_value = str(header_value or "").strip()
    if not normalized_value:
        return None
    parts = normalized_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _parse_webhook_payload(raw_body: bytes) -> tuple[dict[str, Any] | None, str | None]:
    return _parse_json_object_payload(raw_body, allow_single_item_array=True)


def _parse_json_object_payload(
    raw_body: bytes,
    *,
    allow_single_item_array: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"Request body must be valid JSON. {exc.msg} at line {exc.lineno}, column {exc.colno}."

    if allow_single_item_array and isinstance(parsed, list):
        if len(parsed) != 1:
            return None, "Webhook payload array must contain exactly one JSON object."
        parsed = parsed[0]

    if not isinstance(parsed, dict):
        return None, "Request body must be a JSON object."

    return parsed, None


def _resolve_site_id(payload: dict[str, Any]) -> str | None:
    rest_domain = payload.get("rest_domain")
    if isinstance(rest_domain, str) and rest_domain.strip():
        return _hostname_from_value(rest_domain)

    direct_site_id = payload.get("site_id")
    if isinstance(direct_site_id, str) and direct_site_id.strip():
        return _hostname_from_value(direct_site_id)

    link_candidates: list[str] = []
    link = payload.get("link")
    if isinstance(link, str) and link.strip():
        link_candidates.append(link)

    guid = payload.get("guid")
    if isinstance(guid, dict):
        rendered = guid.get("rendered")
        if isinstance(rendered, str) and rendered.strip():
            link_candidates.append(rendered)

    for candidate in link_candidates:
        parsed = urlparse(candidate)
        if parsed.netloc:
            return parsed.netloc.strip().lower()

    return None


def _hostname_from_value(raw_value: str) -> str:
    value = str(raw_value or "").strip().lower()
    if "://" in value:
        parsed = urlparse(value)
        value = parsed.hostname or parsed.netloc or parsed.path or ""
    else:
        value = value.split("/", 1)[0]
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        if port.isdigit():
            value = host
    return value.strip().lower()


__all__ = [
    "WordPressWebhookApplication",
    "WordPressWebhookServer",
    "create_fastapi_app",
    "run_wordpress_webhook_server",
]

