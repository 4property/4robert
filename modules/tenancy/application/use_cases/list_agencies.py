"""List every registered agency."""

from __future__ import annotations

from modules.tenancy.domain import Agency
from shared.db import DatabaseUnitOfWork


class ListAgenciesUseCase:
    def execute(self, *, uow: DatabaseUnitOfWork) -> tuple[Agency, ...]:
        if uow.tenancy is None:
            raise RuntimeError("The unit of work is not active.")
        return uow.tenancy.agencies.list_all()


__all__ = ["ListAgenciesUseCase"]
