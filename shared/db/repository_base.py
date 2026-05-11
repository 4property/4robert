"""Tiny base class shared by every `<Aggregate>Repository`.

Holds the SQLAlchemy `Session` and a cached current-time helper. Each repository
focuses on one aggregate (`AgencyRepository`, `IngestionSourceRepository`, ...).
The Unit of Work in `shared/db/uow.py` instantiates them with a session it
controls; nothing here owns transaction boundaries.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


class ModuleRepository:
    """Base class for any module's per-aggregate repository.

    The `session` is supplied by the Unit of Work and remains valid for the
    duration of one logical request / job. Repositories never commit on their
    own; they only read, write, and let the UoW decide.
    """

    def __init__(self, session: Session) -> None:
        self.session = session


__all__ = ["ModuleRepository", "utcnow", "utcnow_iso"]
