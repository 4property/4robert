from __future__ import annotations

import sqlite3
from pathlib import Path

from config import SQLITE_BUSY_TIMEOUT_MS


def create_sqlite_connection(database_path: str | Path) -> sqlite3.Connection:
    resolved_path = Path(database_path).expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return connection


__all__ = ["create_sqlite_connection"]
