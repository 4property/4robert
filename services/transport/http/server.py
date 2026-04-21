from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

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
    DATABASE_URL,
    LOG_LEVEL,
    PERSISTENT_LOG_BACKUP_COUNT,
    PERSISTENT_LOG_DIRECTORY,
    PERSISTENT_LOG_MAX_BYTES,
    PERSISTENT_LOGGING_ENABLED,
    SOCIAL_PUBLISHING_DEFAULT_PLATFORMS,
    WEBHOOK_ALLOWED_HOSTS,
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
from core.errors import ApplicationError, DependencyNotInstalledError, ResourceNotFoundError, ValidationError
from core.logging import configure_logging, format_console_block, format_detail_line, log_persistent_event, resolve_log_directory
from services.transport.http.operations import build_readiness_report, run_startup_checks
from services.transport.http.openapi_docs import OpenApiDocsConfig, install_openapi_examples
from services.transport.http.uvicorn_protocols import VerboseAutoHTTPProtocol
from services.transport.http.security import build_raw_payload_hash, is_signature_valid, is_timestamp_fresh

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
        enable_docs: bool = WEBHOOK_ENABLE_DOCS,
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
        self.acceptance_service = WebhookAcceptanceService(
            tenant_resolver=TenantResolver(
                unit_of_work_factory=self.unit_of_work_factory,
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
                    "Allowed hosts",
                    ", ".join(effective_allowed_hosts) if effective_allowed_hosts else "Disabled",
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
            allowed_hosts=list(effective_allowed_hosts),
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
        if not self.dispatcher.is_accepting_jobs():
            raise RuntimeError("Webhook dispatcher is not accepting new jobs.")
        return self.acceptance_service.accept_delivery(
            site_id=site_id,
            property_id=property_id,
            raw_payload_hash=raw_payload_hash,
            payload=payload,
            publish_context=publish_context,
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
        enable_docs: bool = WEBHOOK_ENABLE_DOCS,
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
            enable_docs=enable_docs,
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

    @app.post(application.path)
    async def receive_property_webhook(request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        site_id = _get_header_value(request, runtime.site_id_header)
        location_id = _get_header_value(
            request,
            runtime.gohighlevel_location_id_header,
            *_ALTERNATE_GOHIGHLEVEL_LOCATION_ID_HEADERS,
        )
        access_token = _get_header_value(
            request,
            runtime.gohighlevel_access_token_header,
            *_ALTERNATE_GOHIGHLEVEL_ACCESS_TOKEN_HEADERS,
        )
        timestamp = request.headers.get(runtime.timestamp_header)
        signature = request.headers.get(runtime.signature_header)
        if not location_id or not access_token:
            missing_headers = []
            if not location_id:
                missing_headers.append(runtime.gohighlevel_location_id_header)
            if not access_token:
                missing_headers.append(runtime.gohighlevel_access_token_header)
            return _json_error(
                400,
                "Missing required GoHighLevel webhook headers.",
                code="MISSING_GHL_HEADERS",
                hint="Send the GoHighLevel location and access token headers on every webhook request.",
                details={"missing_headers": missing_headers},
            )

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
            location_id=location_id,
            access_token=access_token,
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
                location_id=location_id,
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

        try:
            accepted_delivery = runtime.accept_webhook_delivery(
                site_id=site_id,
                property_id=property_id,
                raw_payload_hash=raw_payload_hash,
                payload=payload,
                publish_context=SocialPublishContext(
                    provider="gohighlevel",
                    location_id=location_id,
                    access_token=access_token,
                    platforms=tuple(SOCIAL_PUBLISHING_DEFAULT_PLATFORMS),
                ),
            )
        except RuntimeError:
            return _json_error(
                503,
                "Webhook dispatcher is not accepting new jobs.",
                code="DISPATCHER_UNAVAILABLE",
                hint="Check the service logs for startup or queue failures and verify the background dispatcher completed startup.",
            )

        logger.info(
            format_console_block(
                "Webhook Accepted",
                format_detail_line("Event ID", accepted_delivery.event_id),
                format_detail_line("Job ID", accepted_delivery.job_id),
                format_detail_line("Site ID", site_id),
                format_detail_line("Property ID", property_id),
                "The payload was queued for background processing.",
            )
        )
        log_persistent_event(
            "webhook.accepted",
            event_id=accepted_delivery.event_id,
            job_id=accepted_delivery.job_id,
            site_id=site_id,
            property_id=property_id,
            raw_payload_hash=raw_payload_hash,
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "event_id": accepted_delivery.event_id,
                "job_id": accepted_delivery.job_id,
                "site_id": site_id,
                "property_id": property_id,
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
    return raw_body.decode("utf-8", errors="replace")


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


def _build_minimal_readiness_payload(readiness: dict[str, object]) -> dict[str, str]:
    return {"status": "ready" if readiness.get("ready") else "not_ready"}


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
    direct_site_id = payload.get("site_id")
    if isinstance(direct_site_id, str) and direct_site_id.strip():
        return direct_site_id.strip().lower()

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


__all__ = [
    "WordPressWebhookApplication",
    "WordPressWebhookServer",
    "create_fastapi_app",
    "run_wordpress_webhook_server",
]

