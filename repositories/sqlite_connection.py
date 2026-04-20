from __future__ import annotations

from pathlib import Path

from repositories.postgres.session import CompatConnection, create_session


def create_sqlite_connection(database_path: str | Path) -> CompatConnection:
    """Compatibility shim kept for code paths that still import the legacy helper."""
    return CompatConnection(create_session(database_path))


__all__ = ["create_sqlite_connection"]
