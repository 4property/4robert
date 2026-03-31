from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from application.bootstrap import build_default_job_dispatcher, build_default_unit_of_work_factory
from application.interfaces import JobDispatcher
from application.types import SocialPublishContext
from application.webhook_acceptance import WebhookAcceptanceService
from config import (
    SOCIAL_PUBLISHING_DEFAULT_PLATFORMS,
    WEBHOOK_DISABLE_SECURITY,
    WEBHOOK_GOHIGHLEVEL_ACCESS_TOKEN_HEADER,
    WEBHOOK_GOHIGHLEVEL_LOCATION_ID_HEADER,
    WEBHOOK_HOST,
    WEBHOOK_JOB_MAX_ATTEMPTS,
    WEBHOOK_MAX_PAYLOAD_BYTES,
    WEBHOOK_PATH,
    WEBHOOK_PORT,
    WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS,
    WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_SITE_ID_HEADER,
    WEBHOOK_SITE_SECRETS,
    WEBHOOK_TIMESTAMP_HEADER,
    WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
    WEBHOOK_WORKER_COUNT,
)
from core.errors import DependencyNotInstalledError
from core.logging import format_console_block, format_detail_line
from services.webhook_transport.operations import build_readiness_report, run_startup_checks
from services.webhook_transport.security import build_raw_payload_hash, is_signature_valid, is_timestamp_fresh

logger = logging.getLogger(__name__)

_ALTERNATE_GOHIGHLEVEL_LOCATION_ID_HEADERS = ("X-GHL-Location-Id",)
_ALTERNATE_GOHIGHLEVEL_ACCESS_TOKEN_HEADERS = ("X-GHL-Token",)


class WordPressWebhookApplication:
    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        dispatcher: JobDispatcher,
        path: str = WEBHOOK_PATH,
        site_id_header: str = WEBHOOK_SITE_ID_HEADER,
        gohighlevel_location_id_header: str = WEBHOOK_GOHIGHLEVEL_LOCATION_ID_HEADER,
        gohighlevel_access_token_header: str = WEBHOOK_GOHIGHLEVEL_ACCESS_TOKEN_HEADER,
        timestamp_header: str = WEBHOOK_TIMESTAMP_HEADER,
        signature_header: str = WEBHOOK_SIGNATURE_HEADER,
        site_secrets: dict[str, str] | None = None,
        security_disabled: bool = WEBHOOK_DISABLE_SECURITY,
        shutdown_timeout_seconds: int = WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS,
        timestamp_tolerance_seconds: int = WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
        max_payload_bytes: int = WEBHOOK_MAX_PAYLOAD_BYTES,
        worker_count: int = WEBHOOK_WORKER_COUNT,
        job_max_attempts: int = WEBHOOK_JOB_MAX_ATTEMPTS,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.dispatcher = dispatcher
        self.unit_of_work_factory = build_default_unit_of_work_factory(self.workspace_dir)
        self.acceptance_service = WebhookAcceptanceService(
            unit_of_work_factory=self.unit_of_work_factory,
            job_max_attempts=job_max_attempts,
        )
        self.path = path
        self.site_id_header = site_id_header
        self.gohighlevel_location_id_header = gohighlevel_location_id_header
        self.gohighlevel_access_token_header = gohighlevel_access_token_header
        self.timestamp_header = timestamp_header
        self.signature_header = signature_header
        self.site_secrets = dict(site_secrets or WEBHOOK_SITE_SECRETS)
        self.security_disabled = security_disabled
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.timestamp_tolerance_seconds = timestamp_tolerance_seconds
        self.max_payload_bytes = max_payload_bytes
        self.worker_count = worker_count

    def start(self) -> None:
        run_startup_checks(
            self.workspace_dir,
            site_secrets=self.site_secrets,
            worker_count=self.worker_count,
            security_disabled=self.security_disabled,
        )
        self.dispatcher.start()
        logger.info(
            format_console_block(
                "Webhook Runtime Started",
                format_detail_line("Webhook path", self.path),
                format_detail_line("Worker count", self.worker_count),
                format_detail_line("Queue backend", "SQLite durable queue"),
                format_detail_line("Security disabled", "Yes" if self.security_disabled else "No"),
            )
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

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        return self.dispatcher.wait_for_idle(timeout=timeout)

    def build_readiness_report(self) -> dict[str, object]:
        readiness = build_readiness_report(
            self.workspace_dir,
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
        if self.security_disabled:
            return bool(site_id)
        expected_secret = self.site_secrets.get(site_id)
        if expected_secret is None:
            return False
        if not is_timestamp_fresh(
            timestamp,
            tolerance_seconds=self.timestamp_tolerance_seconds,
        ):
            return False
        return is_signature_valid(
            secret=expected_secret,
            timestamp=timestamp,
            site_id=site_id,
            location_id=location_id,
            access_token=access_token,
            raw_body=raw_body,
            signature=signature,
        )

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


class WordPressWebhookServer:
    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        dispatcher: JobDispatcher | None = None,
        path: str = WEBHOOK_PATH,
        site_id_header: str = WEBHOOK_SITE_ID_HEADER,
        gohighlevel_location_id_header: str = WEBHOOK_GOHIGHLEVEL_LOCATION_ID_HEADER,
        gohighlevel_access_token_header: str = WEBHOOK_GOHIGHLEVEL_ACCESS_TOKEN_HEADER,
        timestamp_header: str = WEBHOOK_TIMESTAMP_HEADER,
        signature_header: str = WEBHOOK_SIGNATURE_HEADER,
        site_secrets: dict[str, str] | None = None,
        security_disabled: bool = WEBHOOK_DISABLE_SECURITY,
        shutdown_timeout_seconds: int = WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS,
        timestamp_tolerance_seconds: int = WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
        max_payload_bytes: int = WEBHOOK_MAX_PAYLOAD_BYTES,
        worker_count: int = WEBHOOK_WORKER_COUNT,
    ) -> None:
        active_dispatcher = dispatcher or build_default_job_dispatcher(
            workspace_dir,
            worker_count=worker_count,
        )
        self.runtime = WordPressWebhookApplication(
            workspace_dir,
            dispatcher=active_dispatcher,
            path=path,
            site_id_header=site_id_header,
            gohighlevel_location_id_header=gohighlevel_location_id_header,
            gohighlevel_access_token_header=gohighlevel_access_token_header,
            timestamp_header=timestamp_header,
            signature_header=signature_header,
            site_secrets=site_secrets,
            security_disabled=security_disabled,
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

    app = FastAPI(
        title="CPIHED Webhook API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.runtime = application

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready(request: Request) -> JSONResponse:
        runtime = _get_runtime(request)
        readiness = runtime.build_readiness_report()
        status_code = 200 if readiness["ready"] else 503
        return JSONResponse(status_code=status_code, content=readiness)

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
            return _json_error(400, "Missing required webhook headers.")

        content_type = request.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            return _json_error(400, "Content-Type must be application/json.")

        content_length = _parse_content_length(request.headers.get("Content-Length"))
        if content_length is None:
            return _json_error(400, "Invalid Content-Length header.")
        if content_length > runtime.max_payload_bytes:
            return _json_error(413, "Request body is too large.")

        raw_body = await request.body()
        if len(raw_body) > runtime.max_payload_bytes:
            return _json_error(413, "Request body is too large.")

        payload, payload_error = _parse_webhook_payload(raw_body)
        if payload_error is not None:
            return _json_error(400, payload_error)

        if not site_id:
            site_id = _resolve_site_id(payload)

        if not site_id:
            return _json_error(400, "Missing required webhook headers.")
        if not runtime.security_disabled and (not timestamp or not signature):
            return _json_error(400, "Missing required webhook headers.")

        if not runtime.authenticate(
            site_id=site_id,
            location_id=location_id,
            access_token=access_token,
            timestamp=timestamp or "",
            signature=signature or "",
            raw_body=raw_body,
        ):
            return _json_error(401, "Invalid webhook credentials.")

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
            return _json_error(503, "Webhook dispatcher is not accepting new jobs.")

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

    return app


def run_wordpress_webhook_server(
    workspace_dir: str | Path,
    *,
    dispatcher: JobDispatcher | None = None,
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
        log_level=logging.getLevelName(logger.getEffectiveLevel()).lower(),
        access_log=False,
        log_config=None,
    )


def _get_runtime(request: Request) -> WordPressWebhookApplication:
    return request.app.state.runtime  # type: ignore[return-value]


def _json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


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
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return None, "Request body must be valid JSON."

    if isinstance(parsed, list):
        if len(parsed) != 1:
            return None, "Webhook payload array must contain exactly one JSON object."
        parsed = parsed[0]

    if not isinstance(parsed, dict):
        return None, "Webhook payload must be a JSON object."

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

