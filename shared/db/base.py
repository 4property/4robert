"""Declarative base for every SQLAlchemy model in the project.

Lives in `shared/db` (cross-cutting). Modules contribute their ORM
mappings via `shared/db/orm.py` (and, longer term, per-module
`infrastructure/orm.py` files imported there).

The directory is named `shared/` rather than `platform/` to avoid
shadowing Python's stdlib `platform` module, which third-party packages
(numpy, imageio_ffmpeg, etc.) `import` at runtime.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Single declarative base shared by every module."""


__all__ = ["Base"]
