from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any, Final

from core.errors import PipelineError, extract_error_details

try:
    from rich.console import Console
    from rich.logging import RichHandler
    from rich.markup import escape as escape_rich_markup
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TaskID,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )

    RICH_AVAILABLE = True
except ModuleNotFoundError:
    Console = None
    Progress = None
    RichHandler = None
    escape_rich_markup = None
    SpinnerColumn = None
    TextColumn = None
    BarColumn = None
    TaskProgressColumn = None
    MofNCompleteColumn = None
    TimeElapsedColumn = None
    TimeRemainingColumn = None
    TaskID = int
    RICH_AVAILABLE = False

_TITLE_COLORS: Final[dict[str, str]] = {
    "start": "bold bright_cyan",
    "progress": "bold bright_blue",
    "success": "bold bright_green",
    "warning": "bold bright_yellow",
    "failure": "bold bright_red",
    "info": "bold white",
}
_AUDIT_LOGGER_NAME: Final[str] = "cpihed.audit"
_RICH_TAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[/?[^\[\]]+\]")


@dataclass(slots=True)
class NullProgress:
    def add_task(self, description: str, *, total: float | None = None, **fields: Any) -> int:
        return 0

    def update(
        self,
        task_id: int,
        *,
        advance: float = 0.0,
        completed: float | None = None,
        total: float | None = None,
        description: str | None = None,
        visible: bool | None = None,
        **fields: Any,
    ) -> None:
        del task_id, advance, completed, total, description, visible, fields

    def advance(self, task_id: int, advance: float = 1.0) -> None:
        del task_id, advance


class PlainTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        sanitized_record = logging.makeLogRecord(record.__dict__.copy())
        sanitized_record.msg = _strip_rich_markup(record.getMessage())
        sanitized_record.args = ()
        return super().format(sanitized_record)


def get_rich_console() -> Console | None:
    if not RICH_AVAILABLE or RichHandler is None:
        return None

    for handler in logging.getLogger().handlers:
        if isinstance(handler, RichHandler):
            return handler.console
    return None


@contextmanager
def create_progress(*, transient: bool = False) -> Progress | NullProgress:
    console = get_rich_console()
    if console is None or Progress is None or not _console_supports_rich_progress(console):
        yield NullProgress()
        return

    progress = Progress(
        SpinnerColumn(style="bright_cyan"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TextColumn("ETA", style="bold cyan"),
        TimeRemainingColumn(),
        console=console,
        transient=transient,
        expand=True,
    )
    with progress:
        yield progress


def _console_supports_rich_progress_legacy(console: Console) -> bool:
    output = getattr(console, "file", None) or sys.stdout
    encoding = getattr(output, "encoding", None) or getattr(sys.stdout, "encoding", None)
    if not encoding:
        return True
    try:
        "⠋━█".encode(encoding)
    except UnicodeEncodeError:
        return False
    except LookupError:
        return False
    return True


def _console_supports_rich_progress(console: Console) -> bool:
    output = getattr(console, "file", None) or sys.stdout
    encoding = getattr(output, "encoding", None) or getattr(sys.stdout, "encoding", None)
    if not encoding:
        return True
    try:
        "⠋━█".encode(encoding)
    except UnicodeEncodeError:
        return False
    except LookupError:
        return False
    return True


def resolve_log_directory(
    workspace_dir: str | Path,
    *,
    persistent_log_directory: str = "logs",
) -> Path:
    return Path(workspace_dir).expanduser().resolve() / persistent_log_directory


def configure_logging(
    level: str,
    *,
    workspace_dir: str | Path | None = None,
    persistent_logging_enabled: bool = True,
    persistent_log_directory: str = "logs",
    persistent_log_max_bytes: int = 25_000_000,
    persistent_log_backup_count: int = 20,
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

        application_handler = RotatingFileHandler(
            log_dir / "application.log",
            maxBytes=persistent_log_max_bytes,
            backupCount=persistent_log_backup_count,
            encoding="utf-8",
        )
        application_handler.setLevel(logging.DEBUG)
        application_handler.setFormatter(
            PlainTextFormatter(
                "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )
        handlers.append(application_handler)

        error_handler = RotatingFileHandler(
            log_dir / "errors.log",
            maxBytes=persistent_log_max_bytes,
            backupCount=persistent_log_backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(
            PlainTextFormatter(
                "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )
        handlers.append(error_handler)

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

    audit_handler = RotatingFileHandler(
        log_dir / "audit.jsonl",
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


def _strip_rich_markup(value: str) -> str:
    return _RICH_TAG_PATTERN.sub("", value)


def format_duration(seconds: float) -> str:
    total_seconds = max(0.0, float(seconds))
    if total_seconds < 1.0:
        return f"{total_seconds:.3f}s"

    rounded_seconds = int(round(total_seconds))
    minutes, secs = divmod(rounded_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{rounded_seconds}s"


def format_console_block(
    title: str,
    *lines: str | None,
    tone: str | None = None,
) -> str:
    resolved_tone = tone or _infer_tone(title)
    rendered_lines = [line for line in lines if line not in (None, "")]
    header = _format_title(title.upper(), tone=resolved_tone)
    parts = ["", "", header]
    if rendered_lines:
        parts.append("")
        parts.extend(rendered_lines)
    parts.extend(["", ""])
    return "\n".join(parts)


def format_detail_line(
    label: str,
    value: object | None,
    *,
    highlight: bool = False,
) -> str:
    rendered_value = "-" if value in (None, "") else str(value)
    rendered_label = label.upper()
    if not _rich_markup_enabled():
        return f"{rendered_label}: {rendered_value}"

    value_style = "bold bright_white" if highlight else "white"
    return (
        f"[bold cyan]{_escape(rendered_label)}[/]: "
        f"[{value_style}]{_escape(rendered_value)}[/]"
    )


def format_message_line(message: str, *, tone: str = "info") -> str:
    if not _rich_markup_enabled():
        return message
    color = _TITLE_COLORS.get(tone, _TITLE_COLORS["info"])
    return f"[{color}]{_escape(message)}[/]"


def build_log_context(**values: object) -> dict[str, object]:
    context: dict[str, object] = {}
    for key, value in values.items():
        normalized_key = str(key).strip()
        if not normalized_key or value in (None, "", (), [], {}):
            continue
        context[normalized_key] = value
    return context


def format_context_line(context: Mapping[str, object] | None) -> str | None:
    if not context:
        return None
    normalized_items = [
        (str(key).strip(), value)
        for key, value in context.items()
        if str(key).strip() and value not in (None, "", (), [], {})
    ]
    if not normalized_items:
        return None
    rendered_pairs = [
        f"{key}={value}"
        for key, value in sorted(normalized_items, key=lambda item: item[0])
    ]
    return format_detail_line("Context", " | ".join(rendered_pairs))


@dataclass(slots=True)
class LoggedProcess:
    logger: logging.Logger
    title: str
    start_lines: tuple[str, ...] = ()
    total_label: str = "Duration"
    tone: str = "start"
    _started_at: float = field(default_factory=time.perf_counter, init=False)
    _closed: bool = field(default=False, init=False)

    def __enter__(self) -> "LoggedProcess":
        self.logger.info(
            format_console_block(
                f"{self.title} STARTED",
                *self.start_lines,
                tone=self.tone,
            )
        )
        return self

    def update(self, title_suffix: str, *lines: str) -> None:
        self.logger.info(
            format_console_block(
                f"{self.title} {title_suffix}",
                *lines,
                tone="progress",
            )
        )

    def complete(self, *lines: str, total_label: str | None = None) -> float:
        if self._closed:
            return time.perf_counter() - self._started_at
        self._closed = True
        duration = time.perf_counter() - self._started_at
        self.logger.info(
            format_console_block(
                f"{self.title} COMPLETED",
                *lines,
                format_detail_line(total_label or self.total_label, format_duration(duration), highlight=True),
                tone="success",
            )
        )
        return duration

    def fail(
        self,
        error: object,
        *lines: str,
        total_label: str | None = None,
    ) -> float:
        if self._closed:
            return time.perf_counter() - self._started_at
        self._closed = True
        duration = time.perf_counter() - self._started_at
        error_details = extract_error_details(error)
        error_lines = [
            format_detail_line("Error", error, highlight=True),
            format_detail_line("Error type", error_details.get("type")),
            format_detail_line("Error stage", error_details.get("stage")),
            format_detail_line("Error code", error_details.get("code")),
            format_detail_line("Retryable", "Yes" if error_details.get("retryable") else "No"),
            format_detail_line("External trace", error_details.get("external_trace_id")),
            format_detail_line("Hint", error_details.get("hint")),
            format_detail_line("Cause", error_details.get("cause")),
            format_context_line(error_details.get("context") if isinstance(error_details.get("context"), dict) else None),
        ]
        self.logger.error(
            format_console_block(
                f"{self.title} FAILED",
                *lines,
                *error_lines,
                format_detail_line(total_label or self.total_label, format_duration(duration), highlight=True),
                tone="failure",
            )
        )
        return duration

    def __exit__(self, exc_type, exc, exc_tb) -> bool:
        if exc is not None:
            self.fail(exc)
            return False
        if not self._closed:
            self.complete()
        return False


def _infer_tone(title: str) -> str:
    upper_title = title.upper()
    if any(keyword in upper_title for keyword in ("FAILED", "ERROR")):
        return "failure"
    if any(keyword in upper_title for keyword in ("WARNING", "RETRY")):
        return "warning"
    if any(keyword in upper_title for keyword in ("COMPLETED", "FINISHED", "STOPPED")):
        return "success"
    if "STARTED" in upper_title:
        return "start"
    if any(keyword in upper_title for keyword in ("RUNNING", "PROGRESS", "PROCESSING")):
        return "progress"
    return "info"


def _format_title(title: str, *, tone: str) -> str:
    if not _rich_markup_enabled():
        return title
    color = _TITLE_COLORS.get(tone, _TITLE_COLORS["info"])
    return f"[{color}]{_escape(title)}[/]"


def _escape(value: str) -> str:
    if not _rich_markup_enabled() or escape_rich_markup is None:
        return value
    return escape_rich_markup(value)


def _rich_markup_enabled() -> bool:
    if not RICH_AVAILABLE or RichHandler is None:
        return False
    return any(
        isinstance(handler, RichHandler)
        for handler in logging.getLogger().handlers
    )


__all__ = [
    "LoggedProcess",
    "create_progress",
    "configure_logging",
    "log_persistent_event",
    "format_console_block",
    "build_log_context",
    "format_context_line",
    "format_detail_line",
    "format_duration",
    "format_message_line",
    "get_rich_console",
    "resolve_log_directory",
]
