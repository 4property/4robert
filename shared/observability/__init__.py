"""Observability: rich console + persistent logs + audit trail.

Implementation lives in `shared.observability.logging`,
`shared.observability.persistent_log` and `shared.observability.dependencies`.
"""

from shared.observability.dependencies import require_dependency
from shared.observability.logging import (
    LoggedProcess,
    build_log_context,
    create_progress,
    format_console_block,
    format_context_line,
    format_detail_line,
    format_duration,
    format_message_line,
    get_rich_console,
)
from shared.observability.persistent_log import (
    DailyDirectoryRotatingFileHandler,
    configure_logging,
    log_persistent_event,
    resolve_dated_log_directory,
    resolve_log_directory,
)

__all__ = [
    "DailyDirectoryRotatingFileHandler",
    "LoggedProcess",
    "build_log_context",
    "configure_logging",
    "create_progress",
    "format_console_block",
    "format_context_line",
    "format_detail_line",
    "format_duration",
    "format_message_line",
    "get_rich_console",
    "log_persistent_event",
    "require_dependency",
    "resolve_dated_log_directory",
    "resolve_log_directory",
]
