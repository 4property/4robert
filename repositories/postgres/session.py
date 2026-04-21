from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Result
from sqlalchemy.orm import Session, sessionmaker

from repositories.postgres.engine import get_engine

import re

_POSITIONAL_PLACEHOLDER_RE = re.compile(r"\?")


def create_session_factory(database_locator: str | Path | None = None) -> sessionmaker[Session]:
    engine = get_engine(database_locator)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def create_session(database_locator: str | Path | None = None) -> Session:
    return create_session_factory(database_locator)()


@dataclass(slots=True)
class CompatConnection:
    session: Session

    def execute(self, statement: Any, params: dict[str, object] | list[object] | tuple[object, ...] | None = None):
        if isinstance(statement, str):
            translated_statement, translated_params = _translate_sqlite_compat(statement, params)
            return CompatResult(self.session.execute(text(translated_statement), translated_params))
        return CompatResult(self.session.execute(statement, params))

    def executescript(self, script: str) -> None:
        for segment in (part.strip() for part in script.split(";")):
            if not segment:
                continue
            self.session.execute(text(segment))

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()


@dataclass(slots=True)
class CompatRow:
    row: Any

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, (int, slice)):
            return self.row[key]
        return self.row._mapping[key]

    def __iter__(self):
        return iter(self.row)

    def __len__(self) -> int:
        return len(self.row)

    def get(self, key: str, default: Any = None) -> Any:
        return self.row._mapping.get(key, default)


@dataclass(slots=True)
class CompatResult:
    result: Result[Any]

    @property
    def rowcount(self) -> int:
        return self.result.rowcount

    def fetchone(self) -> CompatRow | None:
        row = self.result.fetchone()
        if row is None:
            return None
        return CompatRow(row)

    def fetchall(self) -> list[CompatRow]:
        return [CompatRow(row) for row in self.result.fetchall()]

    def first(self) -> CompatRow | None:
        row = self.result.first()
        if row is None:
            return None
        return CompatRow(row)

    def __iter__(self):
        for row in self.result:
            yield CompatRow(row)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.result, name)


def _translate_sqlite_compat(
    statement: str,
    params: dict[str, object] | list[object] | tuple[object, ...] | None,
) -> tuple[str, dict[str, object]]:
    if isinstance(params, (list, tuple)):
        translated_params = {
            f"p{index}": value
            for index, value in enumerate(params)
        }
        next_index = 0

        def replace_placeholder(_: re.Match[str]) -> str:
            nonlocal next_index
            placeholder = f":p{next_index}"
            next_index += 1
            return placeholder

        translated_statement = _POSITIONAL_PLACEHOLDER_RE.sub(
            replace_placeholder,
            statement,
            count=len(params),
        )
        return translated_statement, translated_params

    return statement, params or {}


__all__ = ["CompatConnection", "CompatResult", "CompatRow", "create_session", "create_session_factory"]
