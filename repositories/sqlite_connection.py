from __future__ import annotations

import sqlite3
from pathlib import Path

from config import SQLITE_BUSY_TIMEOUT_MS
from core.errors import ApplicationError


def create_sqlite_connection(database_path: str | Path) -> sqlite3.Connection:
    resolved_path = Path(database_path).expanduser().resolve()
    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ApplicationError(
            "Failed to create the SQLite database directory.",
            context={"database_path": str(resolved_path)},
            hint="Ensure the service user can create and write to the database parent directory.",
            cause=exc,
        ) from exc

    try:
        connection = sqlite3.connect(resolved_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    except sqlite3.Error as exc:
        raise ApplicationError(
            "Failed to open or initialize the SQLite database.",
            context={
                "database_path": str(resolved_path),
                "busy_timeout_ms": SQLITE_BUSY_TIMEOUT_MS,
            },
            hint=(
                "Check filesystem permissions, free disk space, and whether the database directory "
                "is mounted read-only on the deployed host."
            ),
            cause=exc,
        ) from exc
    return connection


__all__ = ["create_sqlite_connection"]
