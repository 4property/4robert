from __future__ import annotations

import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text

from repositories.postgres.security import encrypt_text

APPLICATION_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = APPLICATION_ROOT / ".tmp_test_cases"
ACTIVE_TABLES = frozenset(
    {
        "agencies",
        "wordpress_sources",
        "properties",
        "property_images",
        "property_pipeline_state",
        "webhook_events",
        "job_queue",
        "media_revisions",
        "outbox_events",
        "scripted_video_artifacts",
        "alembic_version",
    }
)


@dataclass(frozen=True, slots=True)
class SeededTenant:
    agency_id: str
    wordpress_source_id: str
    site_id: str


@dataclass(frozen=True, slots=True)
class PostgresTestSchema:
    admin_url: str
    url: str
    schema: str

    def list_tables(self) -> set[str]:
        engine = create_engine(self.admin_url, future=True)
        try:
            return set(inspect(engine).get_table_names(schema=self.schema))
        finally:
            engine.dispose()


def _with_search_path(database_url: str, schema: str) -> str:
    parsed = urlsplit(database_url)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_items["options"] = f"-csearch_path={schema}"
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query_items, doseq=True, quote_via=quote),
            parsed.fragment,
        )
    )


@contextmanager
def temporary_workspace():
    TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    workspace_dir = TEST_TEMP_ROOT / f"workspace_{uuid4().hex}"
    workspace_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield workspace_dir
    finally:
        shutil.rmtree(workspace_dir, ignore_errors=True)


@contextmanager
def temporary_postgres_schema(database_url: str):
    schema = f"test_{uuid4().hex}"
    admin_engine = create_engine(database_url, future=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped_url = _with_search_path(database_url, schema)
        env = os.environ.copy()
        env["DATABASE_URL"] = scoped_url
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=APPLICATION_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Alembic upgrade failed.\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        yield PostgresTestSchema(
            admin_url=database_url,
            url=scoped_url,
            schema=schema,
        )
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def seed_tenant(
    database_url: str,
    *,
    site_id: str = "site-a",
    source_status: str = "active",
) -> SeededTenant:
    timestamp = datetime.now(timezone.utc)
    agency_id = str(uuid4())
    wordpress_source_id = str(uuid4())
    normalized_site_id = site_id.strip().lower()
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO agencies (
                        id,
                        name,
                        slug,
                        timezone,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :id,
                        :name,
                        :slug,
                        :timezone,
                        :status,
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "id": agency_id,
                    "name": "Test Agency",
                    "slug": f"test-agency-{agency_id[:8]}",
                    "timezone": "Europe/Dublin",
                    "status": "active",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO wordpress_sources (
                        id,
                        agency_id,
                        site_id,
                        name,
                        site_url,
                        normalized_host,
                        webhook_secret_encrypted,
                        status,
                        last_event_at,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :id,
                        :agency_id,
                        :site_id,
                        :name,
                        :site_url,
                        :normalized_host,
                        :webhook_secret_encrypted,
                        :status,
                        NULL,
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "id": wordpress_source_id,
                    "agency_id": agency_id,
                    "site_id": normalized_site_id,
                    "name": "Test Source",
                    "site_url": f"https://{normalized_site_id}",
                    "normalized_host": normalized_site_id,
                    "webhook_secret_encrypted": encrypt_text("test-secret"),
                    "status": source_status,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
    finally:
        engine.dispose()
    return SeededTenant(
        agency_id=agency_id,
        wordpress_source_id=wordpress_source_id,
        site_id=normalized_site_id,
    )


__all__ = [
    "ACTIVE_TABLES",
    "APPLICATION_ROOT",
    "PostgresTestSchema",
    "SeededTenant",
    "seed_tenant",
    "temporary_postgres_schema",
    "temporary_workspace",
]
