from __future__ import annotations

from pathlib import Path

from application.persistence import UnitOfWork
from repositories.media_revision_repository import MediaRevisionRepository
from repositories.outbox_event_repository import OutboxEventRepository
from repositories.property_job_repository import PropertyJobRepository
from repositories.property_pipeline_repository import PropertyPipelineRepository
from repositories.scripted_video_artifact_repository import ScriptedVideoArtifactRepository
from repositories.webhook_delivery_repository import WebhookDeliveryRepository
from repositories.postgres.session import CompatConnection, create_session


class PostgresWorkUnit:
    def __init__(self, database_locator: str | Path | None, base_dir: str | Path) -> None:
        self.database_locator = database_locator
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.session = None
        self.connection = None
        self.property_repository = None
        self.pipeline_state_repository = None
        self.media_revision_store = None
        self.outbox_event_store = None
        self.webhook_event_store = None
        self.job_queue_store = None
        self.scripted_video_store = None

    def begin_immediate(self) -> None:
        if self.session is None:
            raise RuntimeError("The unit of work is not active.")
        if not self.session.in_transaction():
            self.session.begin()

    def __enter__(self) -> UnitOfWork:
        self.session = create_session(self.database_locator)
        self.connection = CompatConnection(self.session)
        self.property_repository = PropertyPipelineRepository(
            self.database_locator,
            self.base_dir,
            connection=self.connection,
        )
        self.pipeline_state_repository = self.property_repository
        self.media_revision_store = MediaRevisionRepository(
            self.database_locator,
            connection=self.connection,
        )
        self.outbox_event_store = OutboxEventRepository(
            self.database_locator,
            connection=self.connection,
        )
        self.webhook_event_store = WebhookDeliveryRepository(
            self.database_locator,
            connection=self.connection,
        )
        self.job_queue_store = PropertyJobRepository(
            self.database_locator,
            connection=self.connection,
        )
        self.scripted_video_store = ScriptedVideoArtifactRepository(
            self.database_locator,
            connection=self.connection,
        )
        self.property_repository.__enter__()
        self.media_revision_store.__enter__()
        self.outbox_event_store.__enter__()
        self.webhook_event_store.__enter__()
        self.job_queue_store.__enter__()
        self.scripted_video_store.__enter__()
        self.session.commit()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if self.scripted_video_store is not None:
            self.scripted_video_store.__exit__(exc_type, exc, exc_tb)
        if self.job_queue_store is not None:
            self.job_queue_store.__exit__(exc_type, exc, exc_tb)
        if self.webhook_event_store is not None:
            self.webhook_event_store.__exit__(exc_type, exc, exc_tb)
        if self.outbox_event_store is not None:
            self.outbox_event_store.__exit__(exc_type, exc, exc_tb)
        if self.media_revision_store is not None:
            self.media_revision_store.__exit__(exc_type, exc, exc_tb)
        if self.property_repository is not None:
            self.property_repository.__exit__(exc_type, exc, exc_tb)
        if self.session is not None:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
            self.session.close()
        self.session = None
        self.connection = None


__all__ = ["PostgresWorkUnit"]
