"""Compatibility exports for agency configuration repositories."""

from __future__ import annotations

from modules.configuration.infrastructure.automation_repository import (
    AutomationRulesRepository,
)
from modules.configuration.infrastructure.brand_repository import BrandSettingsRepository
from modules.configuration.infrastructure.defaults_repository import ReelDefaultsRepository
from modules.configuration.infrastructure.music_track_repository import (
    MusicTracksRepository,
)
from modules.configuration.infrastructure.render_template_repository import (
    RenderTemplateRepository,
)
from modules.configuration.infrastructure.social_template_repository import (
    SocialTemplatesRepository,
)

__all__ = [
    "AutomationRulesRepository",
    "BrandSettingsRepository",
    "MusicTracksRepository",
    "ReelDefaultsRepository",
    "RenderTemplateRepository",
    "SocialTemplatesRepository",
]
