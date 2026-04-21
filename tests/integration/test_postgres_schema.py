from __future__ import annotations

import sys
import unittest
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[2]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from settings import DATABASE_URL
from tests.support.postgres import ACTIVE_TABLES, temporary_postgres_schema


class PostgresSchemaIntegrationTests(unittest.TestCase):
    def test_alembic_upgrade_creates_only_active_tables(self) -> None:
        with temporary_postgres_schema(DATABASE_URL) as database:
            self.assertEqual(database.list_tables(), ACTIVE_TABLES)


if __name__ == "__main__":
    unittest.main()
