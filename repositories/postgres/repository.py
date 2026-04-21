from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from repositories.postgres.session import CompatConnection, create_session


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresRepositoryBase:
    def __init__(
        self,
        database_locator: str | Path | None,
        *,
        connection: CompatConnection | None = None,
    ) -> None:
        self.database_locator = database_locator
        self._owns_connection = connection is None
        self.connection = connection or CompatConnection(create_session(database_locator))

    def __enter__(self):
        self.initialise()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if not self._owns_connection:
            return
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()

    def initialise(self) -> None:
        return None


__all__ = ["PostgresRepositoryBase", "now_iso"]
