from __future__ import annotations

from pathlib import Path

from application.persistence import UnitOfWork
from repositories.property_job_repository import PropertyJobRepository
from repositories.sqlite_connection import create_sqlite_connection
from repositories.webhook_delivery_repository import WebhookDeliveryRepository
from repositories.property_pipeline_repository import PropertyPipelineRepository


class SqliteWorkUnit:
    def __init__(self, database_path: str | Path, base_dir: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.connection = None
        self.property_repository = None
        self.pipeline_state_repository = None
        self.webhook_event_store = None
        self.job_queue_store = None

    def begin_immediate(self) -> None:
        if self.connection is None:
            raise RuntimeError("The unit of work is not active.")
        self.connection.execute("BEGIN IMMEDIATE")

    def __enter__(self) -> UnitOfWork:
        self.connection = create_sqlite_connection(self.database_path)
        self.property_repository = PropertyPipelineRepository(
            self.database_path,
            self.base_dir,
            connection=self.connection,
        )
        self.pipeline_state_repository = self.property_repository
        self.webhook_event_store = WebhookDeliveryRepository(
            self.database_path,
            connection=self.connection,
        )
        self.job_queue_store = PropertyJobRepository(
            self.database_path,
            connection=self.connection,
        )
        self.property_repository.__enter__()
        self.webhook_event_store.__enter__()
        self.job_queue_store.__enter__()
        self.connection.commit()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if self.job_queue_store is not None:
            self.job_queue_store.__exit__(exc_type, exc, exc_tb)
        if self.webhook_event_store is not None:
            self.webhook_event_store.__exit__(exc_type, exc, exc_tb)
        if self.property_repository is not None:
            self.property_repository.__exit__(exc_type, exc, exc_tb)
        if self.connection is not None:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
            self.connection.close()
        self.connection = None


__all__ = ["SqliteWorkUnit"]

