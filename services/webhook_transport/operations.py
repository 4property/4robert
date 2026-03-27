from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from config import (
    DATABASE_FILENAME,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    PROPERTY_MEDIA_RAW_ROOT_DIRNAME,
    PROPERTY_MEDIA_ROOT_DIRNAME,
    REELS_ROOT_DIRNAME,
)
from core.logging import format_console_block, format_detail_line
from core.errors import ApplicationError
from repositories.property_job_repository import PropertyJobRepository
from repositories.webhook_delivery_repository import WebhookDeliveryRepository
from repositories.property_pipeline_repository import PropertyPipelineRepository
from services.reel_rendering.runtime import resolve_ffmpeg_binary

logger = logging.getLogger(__name__)


def cleanup_stale_staging_directories(base_dir: str | Path) -> list[Path]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    removed_directories: list[Path] = []
    reels_root = workspace_dir / REELS_ROOT_DIRNAME
    if not reels_root.exists():
        return removed_directories

    for staging_dir in reels_root.glob("*/_staging"):
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
        raise ApplicationError("WEBHOOK_WORKER_COUNT must be greater than 0.")


def build_readiness_report(
    base_dir: str | Path,
    *,
    site_secrets: dict[str, str],
    worker_count: int,
    security_disabled: bool,
) -> dict[str, object]:
    workspace_dir = Path(base_dir).expanduser().resolve()
    database_path = workspace_dir / DATABASE_FILENAME
    checks = {
        "database_writable": False,
        "storage_writable": False,
        "ffmpeg_available": False,
        "gemini_configured": bool(GEMINI_API_KEY.strip()) and bool(GEMINI_MODEL.strip()),
        "site_secrets_configured": bool(site_secrets) or security_disabled,
        "worker_count_valid": worker_count >= 1,
        "webhook_security_disabled": security_disabled,
    }
    errors: list[str] = []

    try:
        _ensure_database_writable(database_path, workspace_dir)
        checks["database_writable"] = True
    except ApplicationError as exc:
        errors.append(str(exc))

    try:
        _ensure_storage_writable(workspace_dir)
        checks["storage_writable"] = True
    except ApplicationError as exc:
        errors.append(str(exc))

    try:
        resolve_ffmpeg_binary()
        checks["ffmpeg_available"] = True
    except ApplicationError as exc:
        errors.append(str(exc))

    if not checks["gemini_configured"]:
        errors.append("Gemini photo selection is not configured. Set GEMINI_API_KEY.")
    if not checks["site_secrets_configured"]:
        errors.append("At least one webhook site secret must be configured.")
    if not checks["worker_count_valid"]:
        errors.append("WEBHOOK_WORKER_COUNT must be greater than 0.")

    return {
        "ready": not errors,
        "checks": checks,
        "errors": errors,
    }


def run_startup_checks(
    base_dir: str | Path,
    *,
    site_secrets: dict[str, str],
    worker_count: int,
    security_disabled: bool,
) -> dict[str, object]:
    ensure_runtime_is_supported(worker_count=worker_count)
    readiness = build_readiness_report(
        base_dir,
        site_secrets=site_secrets,
        worker_count=worker_count,
        security_disabled=security_disabled,
    )
    if not readiness["ready"]:
        raise ApplicationError("; ".join(str(error) for error in readiness["errors"]))

    removed_directories = cleanup_stale_staging_directories(base_dir)
    if removed_directories:
        logger.info(
            format_console_block(
                "Startup Cleanup Completed",
                format_detail_line("Removed stale staging directories", len(removed_directories)),
            )
        )
    return readiness


def _ensure_database_writable(database_path: Path, workspace_dir: Path) -> None:
    with PropertyPipelineRepository(database_path, workspace_dir):
        pass
    with WebhookDeliveryRepository(database_path):
        pass
    with PropertyJobRepository(database_path):
        pass


def _ensure_storage_writable(workspace_dir: Path) -> None:
    for directory in (
        workspace_dir / PROPERTY_MEDIA_ROOT_DIRNAME,
        workspace_dir / PROPERTY_MEDIA_RAW_ROOT_DIRNAME,
        workspace_dir / REELS_ROOT_DIRNAME,
    ):
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, delete=True):
            pass


__all__ = [
    "build_readiness_report",
    "cleanup_stale_staging_directories",
    "ensure_runtime_is_supported",
    "run_startup_checks",
]

