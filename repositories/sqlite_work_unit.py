from __future__ import annotations

from repositories.postgres.uow import PostgresWorkUnit


class SqliteWorkUnit(PostgresWorkUnit):
    """Compatibility alias retained while the runtime finishes the Postgres cutover."""


__all__ = ["SqliteWorkUnit"]
