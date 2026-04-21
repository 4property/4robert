from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from settings import (
    DATABASE_MAX_OVERFLOW,
    DATABASE_POOL_SIZE,
    DATABASE_POOL_TIMEOUT_SECONDS,
    DATABASE_URL,
)
from repositories.postgres import models as _models  # noqa: F401

_DATABASE_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_ENGINE_CACHE: dict[str, Engine] = {}


@dataclass(frozen=True, slots=True)
class DatabaseBinding:
    url: str
    schema: str | None


def resolve_database_binding(database_locator: str | Path | None) -> DatabaseBinding:
    raw_locator = DATABASE_URL if database_locator is None else str(database_locator).strip()
    if not _DATABASE_URL_RE.match(raw_locator):
        raise ValueError("database_locator must be a PostgreSQL database URL.")
    return DatabaseBinding(url=raw_locator, schema=None)


def get_engine(database_locator: str | Path | None = None) -> Engine:
    binding = resolve_database_binding(database_locator)
    cache_key = binding.url
    engine = _ENGINE_CACHE.get(cache_key)
    if engine is None:
        connect_args: dict[str, Any] = {}
        connect_args.setdefault("connect_timeout", 5)
        engine = create_engine(
            binding.url,
            future=True,
            pool_pre_ping=True,
            pool_size=DATABASE_POOL_SIZE,
            max_overflow=DATABASE_MAX_OVERFLOW,
            pool_timeout=DATABASE_POOL_TIMEOUT_SECONDS,
            connect_args=connect_args,
        )
        _ENGINE_CACHE[cache_key] = engine
    return engine


def verify_required_tables(
    database_locator: str | Path | None,
    *,
    required_tables: tuple[str, ...],
) -> list[str]:
    binding = resolve_database_binding(database_locator)
    engine = get_engine(database_locator)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names(schema=binding.schema))
    return sorted(table for table in required_tables if table not in existing_tables)


def describe_database_binding(database_locator: str | Path | None) -> dict[str, str]:
    binding = resolve_database_binding(database_locator)
    return {
        "database_url": _mask_database_url(binding.url),
        "database_schema": binding.schema or "public",
    }


def _mask_database_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.netloc or "@" not in parsed.netloc:
        return url

    credentials, host = parsed.netloc.rsplit("@", 1)
    if ":" in credentials:
        username, _password = credentials.split(":", 1)
        masked_credentials = f"{username}:***"
    else:
        masked_credentials = credentials
    return urlunsplit((parsed.scheme, f"{masked_credentials}@{host}", parsed.path, parsed.query, parsed.fragment))


__all__ = [
    "describe_database_binding",
    "DatabaseBinding",
    "get_engine",
    "resolve_database_binding",
    "verify_required_tables",
]
