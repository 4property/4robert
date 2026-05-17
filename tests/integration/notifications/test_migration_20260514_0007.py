"""Migration smoke tests for ``email_notifications`` (revision 20260514_0007)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text

from settings import DATABASE_URL
from tests.support.postgres import (
    APPLICATION_ROOT,
    seed_tenant,
    temporary_postgres_schema,
)


def _alembic_run(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=APPLICATION_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_migration_creates_table_columns_and_indexes() -> None:
    with temporary_postgres_schema(DATABASE_URL) as database:
        engine = create_engine(database.url, future=True)
        try:
            inspector = inspect(engine)
            assert "email_notifications" in inspector.get_table_names(
                schema=database.schema
            )
            columns = {
                column["name"]: column
                for column in inspector.get_columns(
                    "email_notifications", schema=database.schema
                )
            }
            for expected in (
                "id",
                "agency_id",
                "event_kind",
                "site_id",
                "source_property_id",
                "recipient_email",
                "status",
                "provider_message_id",
                "error_message",
                "sent_at",
                "created_at",
                "updated_at",
            ):
                assert expected in columns, expected
            index_names = {
                index["name"]
                for index in inspector.get_indexes(
                    "email_notifications", schema=database.schema
                )
            }
            assert "idx_email_notifications_status" in index_names
            assert "idx_email_notifications_agency_created" in index_names
            unique_names = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "email_notifications", schema=database.schema
                )
            }
            assert "uq_email_notifications_dedup" in unique_names
        finally:
            engine.dispose()


def test_migration_unique_constraint_rejects_duplicates() -> None:
    with temporary_postgres_schema(DATABASE_URL) as database:
        seeded = seed_tenant(database.url, site_id="ckp.ie")
        engine = create_engine(database.url, future=True)
        try:
            timestamp = datetime.now(timezone.utc)
            params = {
                "agency_id": seeded.agency_id,
                "event_kind": "review_requested",
                "site_id": seeded.external_source_id,
                "source_property_id": 42,
                "recipient_email": "ops@example.com",
                "status": "queued",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO email_notifications ("
                        "id, agency_id, event_kind, site_id, source_property_id, "
                        "recipient_email, status, created_at, updated_at"
                        ") VALUES ("
                        ":id, :agency_id, :event_kind, :site_id, :source_property_id, "
                        ":recipient_email, :status, :created_at, :updated_at"
                        ")"
                    ),
                    {"id": str(uuid4()), **params},
                )
            with pytest.raises(Exception):
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO email_notifications ("
                            "id, agency_id, event_kind, site_id, source_property_id, "
                            "recipient_email, status, created_at, updated_at"
                            ") VALUES ("
                            ":id, :agency_id, :event_kind, :site_id, :source_property_id, "
                            ":recipient_email, :status, :created_at, :updated_at"
                            ")"
                        ),
                        {"id": str(uuid4()), **params},
                    )
        finally:
            engine.dispose()


def test_migration_downgrade_drops_table_and_upgrade_recreates_it() -> None:
    with temporary_postgres_schema(DATABASE_URL) as database:
        _alembic_run(database.url, "downgrade", "20260514_0006")
        engine = create_engine(database.url, future=True)
        try:
            inspector = inspect(engine)
            assert "email_notifications" not in inspector.get_table_names(
                schema=database.schema
            )
        finally:
            engine.dispose()

        _alembic_run(database.url, "upgrade", "head")
        engine = create_engine(database.url, future=True)
        try:
            inspector = inspect(engine)
            assert "email_notifications" in inspector.get_table_names(
                schema=database.schema
            )
        finally:
            engine.dispose()
