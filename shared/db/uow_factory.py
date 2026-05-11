"""Unit-of-work factory builders.

Moved from ``application/bootstrap/runtime.py`` during sub-feature 18b. These
helpers keep the worker bootstrap call sites short by binding the workspace
directory and database locator into a zero-argument factory.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from settings import DATABASE_URL
from shared.db.uow import DatabaseUnitOfWork


def build_default_unit_of_work_factory(
    workspace_dir: str | Path,
) -> Callable[[], DatabaseUnitOfWork]:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    return lambda: DatabaseUnitOfWork(DATABASE_URL, workspace_path)


def build_runtime_unit_of_work_factory(
    workspace_dir: str | Path,
    *,
    database_locator: str | Path | None = None,
) -> Callable[[], DatabaseUnitOfWork]:
    workspace_path = Path(workspace_dir).expanduser().resolve()
    resolved_database_locator = DATABASE_URL if database_locator is None else database_locator
    return lambda: DatabaseUnitOfWork(resolved_database_locator, workspace_path)


__all__ = [
    "build_default_unit_of_work_factory",
    "build_runtime_unit_of_work_factory",
]
