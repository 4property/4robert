"""DatabaseUnitOfWork — module-namespaced facade over per-aggregate repositories.

Use cases obtain the UoW from `apps/api/app_factory.py` or
`apps/worker/runtime.py` and reach repositories through their bounded-context
namespace:

    with DatabaseUnitOfWork() as uow:
        agency = uow.tenancy.agencies.get_by_slug("acme")
        source = uow.ingestion.sources.get_by_kind_external_id(
            kind="wordpress", external_id="acme.example.com"
        )
        job = uow.delivery.jobs.claim_next_ready_job(...)

The UoW owns the SQLAlchemy session and decides when to commit. Repositories
never commit on their own. New aggregates are imported from their concrete
repository modules and surfaced on the namespace below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from modules.catalog.infrastructure.property_repository import (
    PropertyImageRepository,
    PropertyRepository,
)
from modules.configuration.infrastructure.automation_repository import (
    AutomationRulesRepository,
)
from modules.configuration.infrastructure.brand_repository import (
    BrandSettingsRepository,
)
from modules.configuration.infrastructure.defaults_repository import (
    ReelDefaultsRepository,
)
from modules.configuration.infrastructure.music_track_repository import (
    MusicTracksRepository,
)
from modules.configuration.infrastructure.social_template_repository import (
    SocialTemplatesRepository,
)
from modules.delivery.infrastructure.job_repository import JobRepository
from modules.delivery.infrastructure.outbox_repository import OutboxRepository
from modules.delivery.infrastructure.webhook_event_repository import WebhookEventRepository
from modules.ingestion.infrastructure.ingestion_source_repository import IngestionSourceRepository
from modules.publishing.infrastructure.provider_connection_repository import (
    ProviderConnectionRepository,
)
from modules.reels.infrastructure.media_revision_repository import MediaRevisionRepository
from modules.reels.infrastructure.reel_query import ReelQuery
from modules.reels.infrastructure.reel_state_repository import ReelStateRepository
from modules.reels.infrastructure.scripted_video_artifact_repository import (
    ScriptedVideoArtifactRepository,
)
from modules.tenancy.infrastructure.agency_repository import AgencyRepository
from shared.db.session import create_session


@dataclass(slots=True)
class TenancyNamespace:
    agencies: AgencyRepository


@dataclass(slots=True)
class IngestionNamespace:
    sources: IngestionSourceRepository


@dataclass(slots=True)
class PublishingNamespace:
    connections: ProviderConnectionRepository


@dataclass(slots=True)
class CatalogNamespace:
    properties: PropertyRepository
    images: PropertyImageRepository


@dataclass(slots=True)
class ReelsNamespace:
    states: ReelStateRepository
    revisions: MediaRevisionRepository
    scripted_artifacts: ScriptedVideoArtifactRepository
    queries: ReelQuery


@dataclass(slots=True)
class ConfigurationNamespace:
    brand: BrandSettingsRepository
    defaults: ReelDefaultsRepository
    automation: AutomationRulesRepository
    social_templates: SocialTemplatesRepository
    music: MusicTracksRepository


@dataclass(slots=True)
class DeliveryNamespace:
    jobs: JobRepository
    outbox: OutboxRepository
    webhook_events: WebhookEventRepository


class DatabaseUnitOfWork:
    """Active session + per-module repository namespaces.

    Lifetime is one logical request or one job execution. A successful exit
    commits; an exception rolls back.

    The `base_dir` is the on-disk workspace (per-tenant media root) that
    repositories writing local artifacts (catalog images, reel renders) need
    when they materialise files. Repositories that don't touch disk ignore it.
    """

    def __init__(
        self,
        database_locator: str | Path | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        self.database_locator = database_locator
        self.base_dir = Path(base_dir).expanduser().resolve() if base_dir else None
        self.session: Session | None = None
        self.tenancy: TenancyNamespace | None = None
        self.ingestion: IngestionNamespace | None = None
        self.publishing: PublishingNamespace | None = None
        self.catalog: CatalogNamespace | None = None
        self.reels: ReelsNamespace | None = None
        self.configuration: ConfigurationNamespace | None = None
        self.delivery: DeliveryNamespace | None = None

    def __enter__(self) -> "DatabaseUnitOfWork":
        self.session = create_session(self.database_locator)
        self.tenancy = TenancyNamespace(agencies=AgencyRepository(self.session))
        self.ingestion = IngestionNamespace(
            sources=IngestionSourceRepository(self.session),
        )
        self.publishing = PublishingNamespace(
            connections=ProviderConnectionRepository(self.session),
        )
        self.catalog = CatalogNamespace(
            properties=PropertyRepository(self.session, base_dir=self.base_dir),
            images=PropertyImageRepository(self.session, base_dir=self.base_dir),
        )
        self.reels = ReelsNamespace(
            states=ReelStateRepository(self.session, base_dir=self.base_dir),
            revisions=MediaRevisionRepository(self.session),
            scripted_artifacts=ScriptedVideoArtifactRepository(self.session),
            queries=ReelQuery(self.session),
        )
        self.configuration = ConfigurationNamespace(
            brand=BrandSettingsRepository(self.session),
            defaults=ReelDefaultsRepository(self.session),
            automation=AutomationRulesRepository(self.session),
            social_templates=SocialTemplatesRepository(self.session),
            music=MusicTracksRepository(self.session),
        )
        self.delivery = DeliveryNamespace(
            jobs=JobRepository(self.session),
            outbox=OutboxRepository(self.session),
            webhook_events=WebhookEventRepository(self.session),
        )
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if self.session is None:
            return
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None
            self.tenancy = None
            self.ingestion = None
            self.publishing = None
            self.catalog = None
            self.reels = None
            self.configuration = None
            self.delivery = None

    def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("The unit of work is not active.")
        self.session.commit()


__all__ = ["DatabaseUnitOfWork"]
