"""Readiness report builder for the API process.

Replaces the legacy chain ``apps.api → services.transport.http.operations →
repositories/`` with a modern implementation that opens a
``shared.db.uow.DatabaseUnitOfWork`` as a smoke test instead of constructing
half a dozen legacy stores. The returned dict shape is preserved so
``apps.api.main`` and ``apps.api.health_router`` keep working without any
contract change.
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
from pathlib import Path

from settings import (
    AI_COPY_ENABLED,
    AI_NARRATION_ENABLED,
    DATABASE_URL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    NOTIFICATIONS_ENABLED,
    PROPERTY_MEDIA_RAW_ROOT_DIRNAME,
    PROPERTY_MEDIA_ROOT_DIRNAME,
    REEL_SUBTITLE_FONT_PATH,
    REVIEW_WORKFLOW_ENABLED,
)
from shared.db.engine import describe_database_binding, verify_required_tables
from shared.db.uow import DatabaseUnitOfWork
from shared.errors import ApplicationError

logger = logging.getLogger(__name__)


REQUIRED_POSTGRES_TABLES: tuple[str, ...] = (
    "agencies",
    "ingestion_sources",
    "provider_connections",
    "render_templates",
    "agency_brand_settings",
    "agency_reel_defaults",
    "agency_automation_rules",
    "agency_social_templates",
    "agency_music_tracks",
    "properties",
    "property_images",
    "reels",
    "media_revisions",
    "webhook_events",
    "jobs",
    "outbox_events",
    "scripted_video_artifacts",
    "alembic_version",
)


_PLACEHOLDER_SECRET_TOKENS = frozenset(
    {
        "changeme",
        "change-me",
        "replace-me",
        "replaceme",
        "example",
        "example-secret",
        "secret",
        "test",
        "todo",
    }
)


def cleanup_stale_staging_directories(base_dir: str | Path) -> list[Path]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    removed_directories: list[Path] = []
    generated_media_root = workspace_dir / "generated_media"
    if not generated_media_root.exists():
        return removed_directories

    for staging_dir in generated_media_root.glob("*/reels/_staging"):
        if not staging_dir.is_dir():
            continue
        for stale_path in staging_dir.iterdir():
            if stale_path.is_dir():
                shutil.rmtree(stale_path, ignore_errors=True)
            else:
                stale_path.unlink(missing_ok=True)
            removed_directories.append(stale_path)
    return removed_directories


def ensure_runtime_is_supported(*, worker_count: int) -> None:
    if worker_count < 1:
        raise ApplicationError(
            "WORKER_COUNT must be greater than 0.",
            context={"worker_count": worker_count},
            hint="Set WORKER_COUNT to at least 1 before starting the worker process.",
        )


def build_readiness_report(
    base_dir: str | Path,
    *,
    database_locator: str | Path | None = None,
    site_secrets: dict[str, str],
    worker_count: int,
    security_disabled: bool,
) -> dict[str, object]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    resolved_database_locator = DATABASE_URL if database_locator is None else database_locator
    database_binding = describe_database_binding(resolved_database_locator)
    effective_site_secrets = _has_effective_site_secrets(site_secrets)
    gemini_configured = _has_effective_gemini_credentials(
        api_key=GEMINI_API_KEY,
        model=GEMINI_MODEL,
    )
    checks: dict[str, object] = {
        "database_writable": False,
        "storage_writable": False,
        "ffmpeg_available": False,
        "reel_font_available": False,
        "background_audio_available": False,
        "site_secrets_configured": effective_site_secrets or security_disabled,
        "site_secrets_effective": effective_site_secrets,
        "worker_count_valid": worker_count >= 1,
        "webhook_security_disabled": security_disabled,
    }
    capabilities: dict[str, dict[str, object]] = {
        "core": {"enabled": True, "ready": False, "reason": ""},
        "social": {"enabled": True, "ready": False, "reason": ""},
        "ai_photo_selection": {"enabled": True, "ready": False, "reason": ""},
        "ai_copy": {"enabled": AI_COPY_ENABLED, "ready": not AI_COPY_ENABLED, "reason": ""},
        "ai_narration": {
            "enabled": AI_NARRATION_ENABLED,
            "ready": not AI_NARRATION_ENABLED,
            "reason": "",
        },
        "review_workflow": {
            "enabled": REVIEW_WORKFLOW_ENABLED,
            "ready": not REVIEW_WORKFLOW_ENABLED,
            "reason": "",
        },
        "notifications": {
            "enabled": NOTIFICATIONS_ENABLED,
            "ready": not NOTIFICATIONS_ENABLED,
            "reason": "",
        },
    }
    errors: list[str] = []
    warnings: list[str] = []
    failures: list[dict[str, object]] = []
    environment: dict[str, object] = {
        "workspace_dir": str(workspace_dir),
        "database_url": database_binding["database_url"],
        "database_schema": database_binding["database_schema"],
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "required_directories": [
            str(workspace_dir / PROPERTY_MEDIA_ROOT_DIRNAME),
            str(workspace_dir / PROPERTY_MEDIA_RAW_ROOT_DIRNAME),
            str(workspace_dir / "generated_media"),
        ],
    }

    try:
        _ensure_database_writable(
            workspace_dir,
            database_locator=resolved_database_locator,
        )
        checks["database_writable"] = True
    except ApplicationError as exc:
        errors.append(str(exc))
        failures.append(_build_failure_payload("database_writable", exc))

    try:
        _ensure_storage_writable(workspace_dir)
        checks["storage_writable"] = True
    except ApplicationError as exc:
        errors.append(str(exc))
        failures.append(_build_failure_payload("storage_writable", exc))

    try:
        environment["ffmpeg_binary"] = _resolve_ffmpeg_binary()
        checks["ffmpeg_available"] = True
    except ApplicationError as exc:
        errors.append(str(exc))
        failures.append(_build_failure_payload("ffmpeg_available", exc))

    try:
        environment["reel_font_path"] = str(_resolve_font_path(REEL_SUBTITLE_FONT_PATH))
        checks["reel_font_available"] = True
    except ApplicationError as exc:
        errors.append(str(exc))
        failures.append(_build_failure_payload("reel_font_available", exc))

    try:
        background_audio_paths = _resolve_background_audio_paths(workspace_dir)
        environment["background_audio_path"] = str(background_audio_paths[0])
        environment["background_audio_track_count"] = len(background_audio_paths)
        checks["background_audio_available"] = True
    except ApplicationError as exc:
        errors.append(str(exc))
        failures.append(_build_failure_payload("background_audio_available", exc))

    if not checks["site_secrets_configured"]:
        error = ApplicationError(
            "At least one webhook site secret must be configured.",
            hint=(
                "Set WEBHOOK_SITE_SECRETS with comma-separated site_id=secret pairs. "
                "Only use WEBHOOK_DISABLE_SECURITY=true for local development."
            ),
        )
        errors.append(str(error))
        failures.append(_build_failure_payload("site_secrets_configured", error))

    if not checks["worker_count_valid"]:
        error = ApplicationError(
            "WORKER_COUNT must be greater than 0.",
            context={"worker_count": worker_count},
            hint="Set WORKER_COUNT to at least 1 before starting the worker process.",
        )
        errors.append(str(error))
        failures.append(_build_failure_payload("worker_count_valid", error))

    if security_disabled:
        warnings.append(
            "Webhook signature validation is disabled. This should stay false in production."
        )
    elif site_secrets and not effective_site_secrets:
        warnings.append(
            "Webhook site secrets appear to use placeholder values. Replace them before production."
        )

    capabilities["core"]["ready"] = bool(
        checks["database_writable"]
        and checks["storage_writable"]
        and checks["ffmpeg_available"]
        and checks["reel_font_available"]
        and checks["background_audio_available"]
        and checks["worker_count_valid"]
        and checks["site_secrets_configured"]
    )
    if not capabilities["core"]["ready"]:
        capabilities["core"]["reason"] = "; ".join(errors) or "Core runtime checks failed."

    capabilities["social"]["ready"] = True

    capabilities["ai_photo_selection"]["ready"] = gemini_configured
    if not capabilities["ai_photo_selection"]["ready"]:
        capabilities["ai_photo_selection"]["reason"] = (
            "Gemini photo selection is not configured. Set GEMINI_API_KEY and GEMINI_MODEL to enable it."
        )

    if AI_COPY_ENABLED and not capabilities["ai_photo_selection"]["ready"]:
        capabilities["ai_copy"]["ready"] = False
        capabilities["ai_copy"]["reason"] = (
            "AI copy is enabled but Gemini credentials are not configured."
        )

    if AI_NARRATION_ENABLED:
        capabilities["ai_narration"]["ready"] = False
        capabilities["ai_narration"]["reason"] = (
            "AI narration is enabled but no narration provider is configured."
        )

    if REVIEW_WORKFLOW_ENABLED:
        capabilities["review_workflow"]["ready"] = True
        capabilities["review_workflow"]["reason"] = (
            "Review workflow is enabled in domain state, awaiting approval transport."
        )

    if NOTIFICATIONS_ENABLED:
        capabilities["notifications"]["ready"] = False
        capabilities["notifications"]["reason"] = (
            "Notifications are enabled but no delivery transport is configured."
        )

    production_ready = bool(
        capabilities["core"]["ready"]
        and not security_disabled
        and checks["site_secrets_effective"]
    )

    return {
        "ready": capabilities["core"]["ready"],
        "production_ready": production_ready,
        "checks": checks,
        "capabilities": capabilities,
        "errors": errors,
        "warnings": warnings,
        "failures": failures,
        "environment": environment,
    }


def _has_effective_site_secrets(site_secrets: dict[str, str]) -> bool:
    for site_id, secret in site_secrets.items():
        normalized_site_id = str(site_id or "").strip()
        normalized_secret = str(secret or "").strip()
        if not normalized_site_id or not normalized_secret:
            continue
        if _looks_like_placeholder_secret(normalized_secret):
            continue
        return True
    return False


def _has_effective_gemini_credentials(*, api_key: str, model: str) -> bool:
    normalized_model = str(model or "").strip()
    normalized_api_key = str(api_key or "").strip()
    return bool(
        normalized_model
        and normalized_api_key
        and not _looks_like_placeholder_secret(normalized_api_key)
    )


def _looks_like_placeholder_secret(value: str) -> bool:
    normalized_value = str(value or "").strip().lower()
    if not normalized_value:
        return True
    collapsed = "".join(character for character in normalized_value if character.isalnum())
    return normalized_value in _PLACEHOLDER_SECRET_TOKENS or collapsed in {
        token.replace("-", "") for token in _PLACEHOLDER_SECRET_TOKENS
    }


def _ensure_database_writable(
    workspace_dir: Path,
    *,
    database_locator: str | Path | None,
) -> None:
    try:
        missing_tables = verify_required_tables(
            database_locator,
            required_tables=REQUIRED_POSTGRES_TABLES,
        )
        if missing_tables:
            raise ApplicationError(
                "PostgreSQL is reachable but the schema is incomplete.",
                context={
                    "database_url": describe_database_binding(database_locator)["database_url"],
                    "missing_tables": ", ".join(missing_tables),
                },
                hint=(
                    "Run `.\\.venv\\Scripts\\python.exe -m alembic upgrade head` against this DATABASE_URL "
                    "before starting the service."
                ),
            )

        with DatabaseUnitOfWork(database_locator, workspace_dir):
            pass
    except ApplicationError:
        raise
    except Exception as exc:
        raise ApplicationError(
            "Failed to open or initialize the PostgreSQL repositories.",
            context={
                "database_url": describe_database_binding(database_locator)["database_url"],
                "workspace_dir": str(workspace_dir),
            },
            hint=(
                "Ensure DATABASE_URL points to a reachable PostgreSQL instance, run the Alembic migrations, "
                "and confirm the service user can still write the workspace storage directories."
            ),
            cause=exc,
        ) from exc


def _ensure_storage_writable(workspace_dir: Path) -> None:
    for directory in (
        workspace_dir / PROPERTY_MEDIA_ROOT_DIRNAME,
        workspace_dir / PROPERTY_MEDIA_RAW_ROOT_DIRNAME,
        workspace_dir / "generated_media",
    ):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=directory, delete=True):
                pass
        except OSError as exc:
            raise ApplicationError(
                "Failed to create or write to a runtime storage directory.",
                context={"directory": str(directory)},
                hint=(
                    "Ensure the deployed service user owns the workspace and can write to "
                    "property_media, property_media_raw, and generated_media."
                ),
                cause=exc,
            ) from exc


def _resolve_ffmpeg_binary() -> str:
    # Lazy import keeps the rendering runtime unloaded for tests that patch it.
    from modules.rendering.infrastructure.runtime import resolve_ffmpeg_binary

    return resolve_ffmpeg_binary()


def _resolve_font_path(font_path: str | Path) -> Path:
    from modules.rendering.infrastructure.runtime import resolve_font_path

    return resolve_font_path(font_path)


def _resolve_background_audio_paths(workspace_dir: Path) -> tuple[Path, ...]:
    from modules.rendering.infrastructure.models import PropertyReelTemplate
    from modules.rendering.infrastructure.runtime import resolve_background_audio_paths

    return resolve_background_audio_paths(
        workspace_dir,
        PropertyReelTemplate(),
        shuffle_candidates=False,
        music_tracks=None,
    )


def _build_failure_payload(check: str, error: ApplicationError) -> dict[str, object]:
    details = error.to_dict()
    payload: dict[str, object] = {
        "check": check,
        "message": details["message"],
    }
    if "hint" in details:
        payload["hint"] = details["hint"]
    if "context" in details:
        payload["context"] = details["context"]
    if "cause" in details:
        payload["cause"] = details["cause"]
    return payload


__all__ = [
    "REQUIRED_POSTGRES_TABLES",
    "build_readiness_report",
    "cleanup_stale_staging_directories",
    "ensure_runtime_is_supported",
]
