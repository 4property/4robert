from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[2]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from application.dispatch.database_dispatcher import DatabaseJobDispatcher
from repositories.postgres.uow import DatabaseUnitOfWork
from repositories.stores.pipeline_state_store import PipelineStateStore
from repositories.stores.property_store import PropertyStore
from settings import DATABASE_URL
from tests.support.postgres import temporary_postgres_schema, temporary_workspace

LEGACY_PATTERNS = (
    re.compile(r"\bDATABASE_FILENAME\b"),
    re.compile(r"\bsqlite_master\b"),
    re.compile(r"\bPRAGMA table_info\b"),
    re.compile(r"\bensure_site_context\b"),
    re.compile(r"^\s*from\s+config\s+import\s+", re.MULTILINE),
    re.compile(r"^\s*import\s+config\b", re.MULTILINE),
    re.compile(r"\brepositories\.sqlite_work_unit\b"),
    re.compile(r"\brepositories\.sqlite_connection\b"),
    re.compile(r"\bPropertyPipelineRepository\b"),
)


class ArchitectureCleanupTests(unittest.TestCase):
    def test_canonical_runtime_symbol_names_are_active(self) -> None:
        self.assertEqual(DatabaseJobDispatcher.__name__, "DatabaseJobDispatcher")
        self.assertEqual(DatabaseUnitOfWork.__name__, "DatabaseUnitOfWork")

    def test_database_unit_of_work_uses_split_stores(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                with DatabaseUnitOfWork(database.url, workspace_dir) as unit_of_work:
                    self.assertIsInstance(unit_of_work.property_repository, PropertyStore)
                    self.assertIsInstance(unit_of_work.pipeline_state_repository, PipelineStateStore)
                    self.assertIsNot(
                        unit_of_work.property_repository,
                        unit_of_work.pipeline_state_repository,
                    )

    def test_source_tree_contains_no_sqlite_or_config_legacy_symbols(self) -> None:
        source_roots = (
            APPLICATION_ROOT / "application",
            APPLICATION_ROOT / "domain",
            APPLICATION_ROOT / "repositories",
            APPLICATION_ROOT / "services",
            APPLICATION_ROOT / "settings",
            APPLICATION_ROOT / "main.py",
        )
        python_files: list[Path] = []
        for source_root in source_roots:
            if source_root.is_file():
                python_files.append(source_root)
                continue
            python_files.extend(source_root.rglob("*.py"))

        violations: list[str] = []
        for path in python_files:
            text = path.read_text(encoding="utf-8")
            for pattern in LEGACY_PATTERNS:
                if pattern.search(text):
                    violations.append(
                        f"{path.relative_to(APPLICATION_ROOT)} -> {pattern.pattern}"
                    )

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
