from __future__ import annotations

import sys
import unittest
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[2]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from application.tenancy.resolver import TenantResolver
from core.errors import ResourceNotFoundError
from repositories.postgres.uow import DatabaseUnitOfWork
from settings import DATABASE_URL
from tests.support.postgres import seed_tenant, temporary_postgres_schema, temporary_workspace


class TenantResolverTests(unittest.TestCase):
    def test_resolve_returns_tenant_context_for_active_site(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="site-a")
                resolver = TenantResolver(
                    unit_of_work_factory=lambda: DatabaseUnitOfWork(database.url, workspace_dir)
                )

                context = resolver.resolve(site_id="SITE-A")

                self.assertEqual(context.site_id, seeded.site_id)
                self.assertEqual(context.agency_id, seeded.agency_id)
                self.assertEqual(context.wordpress_source_id, seeded.wordpress_source_id)

    def test_resolve_rejects_unknown_or_inactive_sites(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seed_tenant(database.url, site_id="inactive.example", source_status="inactive")
                resolver = TenantResolver(
                    unit_of_work_factory=lambda: DatabaseUnitOfWork(database.url, workspace_dir)
                )

                with self.assertRaises(ResourceNotFoundError):
                    resolver.resolve(site_id="missing.example")

                with self.assertRaises(ResourceNotFoundError):
                    resolver.resolve(site_id="inactive.example")


if __name__ == "__main__":
    unittest.main()
