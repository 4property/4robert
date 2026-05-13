from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Final

from shared.observability.logging import (
    PlainTextFormatter,
    RICH_AVAILABLE,
    RichHandler,
)

_AUDIT_LOGGER_NAME: Final[str] = "cpihed.audit"
_PERSISTENT_LOG_FORMAT: Final[str] = (
    "%(asctime)s | %(levelname)-7s | %(process_role)s | %(threadName)s | %(name)s | %(message)s"
)
_PERSISTENT_LOG_DATE_FORMAT: Final[str] = "%d/%m/%Y %H:%M:%S"


class ProcessRoleFilter(logging.Filter):
    def __init__(self, process_role: str) -> None:
        super().__init__()
        self._process_role = str(process_role or "app").strip() or "app"

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "process_role"):
            record.process_role = self._process_role
        return True


class PersistentLogFormatter(PlainTextFormatter):
    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        *,
        current_date_provider: Callable[[], date] | None = None,
    ) -> None:
        super().__init__(fmt, datefmt)
        self._current_date_provider = current_date_provider or _current_log_date

    def formatTime(
        self,
        record: logging.LogRecord,
        datefmt: str | None = None,
    ) -> str:
        record_time = datetime.fromtimestamp(record.created).time()
        active_date = self._current_date_provider()
        rendered_at = datetime.combine(active_date, record_time)
        if datefmt:
            return rendered_at.strftime(datefmt)
        return rendered_at.isoformat(sep=" ", timespec="seconds")


class DailyDirectoryRotatingFileHandler(RotatingFileHandler):
    def __init__(
        self,
        log_root_dir: Path,
        filename: str,
        *,
        maxBytes: int,
        backupCount: int,
        encoding: str = "utf-8",
        current_date_provider: Callable[[], date] | None = None,
    ) -> None:
        self._log_root_dir = Path(log_root_dir).expanduser().resolve()
        self._filename = filename
        self._current_date_provider = current_date_provider or _current_log_date
        self._current_log_date: date | None = None

        initial_path = self._resolve_current_log_path()
        initial_path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(
            initial_path,
            maxBytes=maxBytes,
            backupCount=backupCount,
            encoding=encoding,
        )
        self._current_log_date = self._current_date_provider()

    def emit(self, record: logging.LogRecord) -> None:
        self._ensure_current_stream()
        super().emit(record)

    def shouldRollover(self, record: logging.LogRecord) -> int:
        self._ensure_current_stream()
        return super().shouldRollover(record)

    def _ensure_current_stream(self) -> None:
        active_date = self._current_date_provider()
        if active_date == self._current_log_date:
            return

        if self.stream is not None:
            self.stream.flush()
            self.stream.close()
            self.stream = None

        next_path = self._resolve_log_path_for_date(active_date)
        next_path.parent.mkdir(parents=True, exist_ok=True)
        self.baseFilename = os.fspath(next_path)
        if not self.delay:
            self.stream = self._open()
        self._current_log_date = active_date

    def _resolve_current_log_path(self) -> Path:
        return self._resolve_log_path_for_date(self._current_date_provider())

    def _resolve_log_path_for_date(self, log_date: date) -> Path:
        return resolve_dated_log_directory(self._log_root_dir, log_date=log_date) / self._filename


def resolve_log_directory(
    workspace_dir: str | Path,
    *,
    persistent_log_directory: str = "logs",
) -> Path:
    return Path(workspace_dir).expanduser().resolve() / persistent_log_directory


def resolve_dated_log_directory(
    log_root_dir: str | Path,
    *,
    log_date: date | None = None,
) -> Path:
    resolved_date = log_date or _current_log_date()
    root_dir = Path(log_root_dir).expanduser().resolve()
    month_dir = resolved_date.strftime("%m-%Y")
    day_dir = resolved_date.strftime("%d-%m-%Y")
    return root_dir / month_dir / day_dir


def _current_log_date() -> date:
    return datetime.now().astimezone().date()


def configure_logging(
    level: str,
    *,
    workspace_dir: str | Path | None = None,
    persistent_logging_enabled: bool = True,
    persistent_log_directory: str = "logs",
    persistent_log_max_bytes: int = 25_000_000,
    persistent_log_backup_count: int = 20,
    process_role: str = "app",
) -> None:
    level_value = getattr(logging, level.upper(), logging.INFO)
    logging.captureWarnings(True)

    handlers: list[logging.Handler] = []
    if RICH_AVAILABLE and RichHandler is not None:
        handler = RichHandler(
            show_time=True,
            show_level=True,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
            omit_repeated_times=False,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-7s | %(message)s",
                "%H:%M:%S",
            )
        )
    handler.setLevel(level_value)
    handlers.append(handler)

    log_dir: Path | None = None
    if persistent_logging_enabled and workspace_dir is not None:
        log_dir = resolve_log_directory(
            workspace_dir,
            persistent_log_directory=persistent_log_directory,
        )
        log_dir.mkdir(parents=True, exist_ok=True)

        application_handler = DailyDirectoryRotatingFileHandler(
            log_dir,
            "application.log",
            maxBytes=persistent_log_max_bytes,
            backupCount=persistent_log_backup_count,
            encoding="utf-8",
        )
        application_handler.setLevel(logging.DEBUG)
        application_handler.addFilter(ProcessRoleFilter(process_role))
        application_handler.setFormatter(
            PersistentLogFormatter(
                _PERSISTENT_LOG_FORMAT,
                _PERSISTENT_LOG_DATE_FORMAT,
            )
        )
        handlers.append(application_handler)

        error_handler = DailyDirectoryRotatingFileHandler(
            log_dir,
            "errors.log",
            maxBytes=persistent_log_max_bytes,
            backupCount=persistent_log_backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.addFilter(ProcessRoleFilter(process_role))
        error_handler.setFormatter(
            PersistentLogFormatter(
                _PERSISTENT_LOG_FORMAT,
                _PERSISTENT_LOG_DATE_FORMAT,
            )
        )
        handlers.append(error_handler)

        warning_error_daily_handler = DailyDirectoryRotatingFileHandler(
            log_dir,
            "warnings-errors.log",
            maxBytes=persistent_log_max_bytes,
            backupCount=persistent_log_backup_count,
            encoding="utf-8",
        )
        warning_error_daily_handler.setLevel(logging.WARNING)
        warning_error_daily_handler.addFilter(ProcessRoleFilter(process_role))
        warning_error_daily_handler.setFormatter(
            PersistentLogFormatter(
                _PERSISTENT_LOG_FORMAT,
                _PERSISTENT_LOG_DATE_FORMAT,
            )
        )
        handlers.append(warning_error_daily_handler)

    logging.basicConfig(
        level=logging.DEBUG if log_dir is not None else level_value,
        handlers=handlers,
        force=True,
    )
    _configure_audit_logger(
        log_dir,
        persistent_log_max_bytes=persistent_log_max_bytes,
        persistent_log_backup_count=persistent_log_backup_count,
    )

    for logger_name in (
        "httpx",
        "httpcore",
        "uvicorn.access",
        "uvicorn.error",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def log_persistent_event(event_type: str, **fields: object) -> None:
    logger = logging.getLogger(_AUDIT_LOGGER_NAME)
    if not logger.handlers:
        return

    payload: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
    }
    payload.update(fields)
    logger.info(json.dumps(_json_safe_value(payload), ensure_ascii=False, sort_keys=True))


def _configure_audit_logger(
    log_dir: Path | None,
    *,
    persistent_log_max_bytes: int,
    persistent_log_backup_count: int,
) -> None:
    audit_logger = logging.getLogger(_AUDIT_LOGGER_NAME)
    _clear_logger_handlers(audit_logger)
    audit_logger.propagate = False
    audit_logger.setLevel(logging.INFO)
    if log_dir is None:
        return

    audit_handler = DailyDirectoryRotatingFileHandler(
        log_dir,
        "audit.jsonl",
        maxBytes=persistent_log_max_bytes,
        backupCount=persistent_log_backup_count,
        encoding="utf-8",
    )
    audit_handler.setLevel(logging.INFO)
    audit_handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(audit_handler)


def _clear_logger_handlers(target_logger: logging.Logger) -> None:
    for handler in list(target_logger.handlers):
        target_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            continue


def _json_safe_value(value: object) -> object:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        return str(value)


__all__ = [
    "DailyDirectoryRotatingFileHandler",
    "PersistentLogFormatter",
    "ProcessRoleFilter",
    "configure_logging",
    "log_persistent_event",
    "resolve_dated_log_directory",
    "resolve_log_directory",
]
