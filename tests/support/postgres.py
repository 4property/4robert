from __future__ import annotations

import json
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

from shared.db.security import encrypt_text

APPLICATION_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = APPLICATION_ROOT / ".tmp_test_cases"
ACTIVE_TABLES = frozenset(
    {
        "agencies",
        "ingestion_sources",
        "provider_connections",
        "agency_brand_settings",
        "agency_reel_defaults",
        "agency_automation_rules",
        "agency_social_templates",
        "agency_music_tracks",
        "properties",
        "property_images",
        "reels",
        "media_revisions",
        "webhook_events",
        "jobs",
        "outbox_events",
        "scripted_video_artifacts",
        "alembic_version",
    }
)


@dataclass(frozen=True, slots=True)
class SeededTenant:
    """One tenant + its WordPress ingestion source.

    `wordpress_source_id` and `site_id` are kept on this dataclass for
    backwards compatibility with the legacy tests; new tests should use
    `ingestion_source_id` and `external_source_id`.
    """

    agency_id: str
    ingestion_source_id: str
    external_source_id: str

    @property
    def wordpress_source_id(self) -> str:
        return self.ingestion_source_id

    @property
    def site_id(self) -> str:
        return self.external_source_id


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
    scoped_url: str | None = None
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
        # Dispose any engine the runtime cached against the scoped URL: the
        # schema is being dropped, so its pooled connections are about to be
        # invalidated. Without this disposal the cache accumulates one stale
        # engine per test, eventually starving the Postgres connection budget.
        if scoped_url is not None:
            try:
                from shared.db.engine import _ENGINE_CACHE  # type: ignore[attr-defined]

                cached_engine = _ENGINE_CACHE.pop(scoped_url, None)
                if cached_engine is not None:
                    cached_engine.dispose()
            except Exception:
                pass
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def seed_tenant(
    database_url: str,
    *,
    site_id: str = "site-a",
    source_status: str = "active",
) -> SeededTenant:
    """Seed an agency + a WordPress `ingestion_sources` row.

    `site_id` is kept as the parameter name for backwards compatibility; it
    becomes `ingestion_sources.external_id` (with `kind='wordpress'`).
    """
    timestamp = datetime.now(timezone.utc)
    agency_id = str(uuid4())
    ingestion_source_id = str(uuid4())
    external_source_id = site_id.strip().lower()
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agencies (id, name, slug, timezone, status, "
                    "created_at, updated_at) VALUES (:id, :name, :slug, "
                    ":timezone, :status, :created_at, :updated_at)"
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
                    "INSERT INTO ingestion_sources ("
                    "id, agency_id, kind, external_id, name, config_json, "
                    "secrets_encrypted, status, last_event_at, created_at, updated_at"
                    ") VALUES ("
                    ":id, :agency_id, 'wordpress', :external_id, :name, "
                    "CAST(:config_json AS jsonb), :secrets_encrypted, :status, "
                    "NULL, :created_at, :updated_at"
                    ")"
                ),
                {
                    "id": ingestion_source_id,
                    "agency_id": agency_id,
                    "external_id": external_source_id,
                    "name": "Test Source",
                    "config_json": json.dumps(
                        {
                            "site_url": f"https://{external_source_id}",
                            "normalized_host": external_source_id,
                        }
                    ),
                    "secrets_encrypted": encrypt_text("test-secret"),
                    "status": source_status,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
    finally:
        engine.dispose()
    return SeededTenant(
        agency_id=agency_id,
        ingestion_source_id=ingestion_source_id,
        external_source_id=external_source_id,
    )


def seed_provider_connection(
    database_url: str,
    *,
    agency_id: str,
    provider: str = "gohighlevel",
    external_id: str = "loc-test",
    config: dict | None = None,
    secrets: dict | None = None,
) -> str:
    """Seed a `provider_connections` row for an existing agency."""
    timestamp = datetime.now(timezone.utc)
    connection_id = str(uuid4())
    secrets_payload = json.dumps(
        secrets if secrets is not None else {"access_token": "token-test"},
        separators=(",", ":"),
    )
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO provider_connections ("
                    "id, agency_id, provider, external_id, config_json, "
                    "secrets_encrypted, status, created_at, updated_at"
                    ") VALUES ("
                    ":id, :agency_id, :provider, :external_id, "
                    "CAST(:config_json AS jsonb), :secrets_encrypted, "
                    "'active', :created_at, :updated_at"
                    ")"
                ),
                {
                    "id": connection_id,
                    "agency_id": agency_id,
                    "provider": provider,
                    "external_id": external_id,
                    "config_json": json.dumps(config or {"user_id": "user-test"}),
                    "secrets_encrypted": encrypt_text(secrets_payload),
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
    finally:
        engine.dispose()
    return connection_id

__all__ = [
    "ACTIVE_TABLES",
    "APPLICATION_ROOT",
    "PostgresTestSchema",
    "SeededTenant",
    "seed_provider_connection",
    "seed_tenant",
    "temporary_postgres_schema",
    "temporary_workspace",
]
