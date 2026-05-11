"""Agency aggregate.

Plain Python value objects so the application layer never imports SQLAlchemy
models. The infrastructure repository converts between these and the ORM rows.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Agency:
    agency_id: str
    name: str
    slug: str
    timezone: str
    status: str
    created_at: str | None
    updated_at: str | None


__all__ = ["Agency"]
