from __future__ import annotations

import hashlib
from importlib import import_module
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from config import (
    DATABASE_MAX_OVERFLOW,
    DATABASE_POOL_SIZE,
    DATABASE_POOL_TIMEOUT_SECONDS,
    DATABASE_URL,
)
from repositories.postgres.base import Base
from repositories.postgres import models as _models  # noqa: F401

_DATABASE_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_ENGINE_CACHE: dict[tuple[str, str | None], Engine] = {}
_AUTO_SCHEMA_CACHE: set[tuple[str, str]] = set()


@dataclass(frozen=True, slots=True)
class DatabaseBinding:
    url: str
    schema: str | None
    auto_create_schema: bool


def resolve_database_binding(database_locator: str | Path | None) -> DatabaseBinding:
    if database_locator is None:
        return DatabaseBinding(
            url=DATABASE_URL,
            schema=None,
            auto_create_schema=False,
        )

    raw_locator = str(database_locator).strip()
    if _DATABASE_URL_RE.match(raw_locator):
        return DatabaseBinding(
            url=raw_locator,
            schema=None,
            auto_create_schema=False,
        )

    resolved_locator = Path(raw_locator).expanduser().resolve()
    digest = hashlib.sha1(str(resolved_locator).encode("utf-8")).hexdigest()[:16]
    return DatabaseBinding(
        url=DATABASE_URL,
        schema=f"ws_{digest}",
        auto_create_schema=True,
    )


def get_engine(database_locator: str | Path | None = None) -> Engine:
    binding = resolve_database_binding(database_locator)
    cache_key = (binding.url, binding.schema)
    engine = _ENGINE_CACHE.get(cache_key)
    if engine is None:
        connect_args: dict[str, Any] = {}
        if binding.schema:
            connect_args["options"] = f"-csearch_path={binding.schema}"
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
    if binding.schema and binding.auto_create_schema:
        _ensure_auto_schema(engine, binding.schema)
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


def _ensure_auto_schema(engine: Engine, schema: str) -> None:
    cache_key = (str(engine.url), schema)
    import_module("repositories.postgres.models")
    required_tables = set(Base.metadata.tables)
    if cache_key in _AUTO_SCHEMA_CACHE:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names(schema=schema))
        if required_tables.issubset(existing_tables):
            return
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        Base.metadata.create_all(connection)
    _AUTO_SCHEMA_CACHE.add(cache_key)


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
