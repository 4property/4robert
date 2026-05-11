"""SQLAlchemy session factory for the modular monolith.

Modules call `create_session(...)` once per Unit of Work and pass the bound
session to their `<Aggregate>Repository`. There is no SQLite compatibility
layer here — Postgres is the single supported backend.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from shared.db.engine import get_engine


def create_session_factory(database_locator: str | Path | None = None) -> sessionmaker[Session]:
    engine = get_engine(database_locator)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def create_session(database_locator: str | Path | None = None) -> Session:
    return create_session_factory(database_locator)()


__all__ = ["create_session", "create_session_factory"]
