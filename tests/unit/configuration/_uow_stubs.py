"""Lightweight UoW stubs used across configuration use-case unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class StubAgencies:
    def __init__(self, *, present: bool = True) -> None:
        self.present = present
        self.last_lookup: str | None = None

    def get_by_id(self, agency_id: str) -> Any:
        self.last_lookup = agency_id
        if not self.present:
            return None
        return SimpleNamespace(agency_id=agency_id)


class StubBrand:
    def __init__(self, *, existing: Any = None) -> None:
        self.existing = existing
        self.upsert_calls: list[dict[str, Any]] = []

    def get(self, agency_id: str) -> Any:
        del agency_id
        return self.existing

    def upsert(self, **kwargs: Any) -> Any:
        self.upsert_calls.append(kwargs)
        return SimpleNamespace(**kwargs)


class StubDefaults:
    def __init__(self, *, existing: Any = None) -> None:
        self.existing = existing
        self.upsert_calls: list[dict[str, Any]] = []

    def get(self, agency_id: str) -> Any:
        del agency_id
        return self.existing

    def upsert(self, **kwargs: Any) -> Any:
        self.upsert_calls.append(kwargs)
        return SimpleNamespace(**kwargs)


class StubAutomation:
    def __init__(self, *, existing: Any = None) -> None:
        self.existing = existing
        self.upsert_calls: list[dict[str, Any]] = []

    def get(self, agency_id: str) -> Any:
        del agency_id
        return self.existing

    def upsert(self, **kwargs: Any) -> Any:
        self.upsert_calls.append(kwargs)
        return SimpleNamespace(**kwargs)


class StubSocialTemplates:
    def __init__(self, *, existing: tuple = ()) -> None:
        self.existing = existing
        self.replace_calls: list[dict[str, Any]] = []

    def list_for_agency(self, agency_id: str) -> tuple:
        del agency_id
        return self.existing

    def replace_all_for_agency(self, *, agency_id: str, templates: dict) -> tuple:
        self.replace_calls.append({"agency_id": agency_id, "templates": templates})
        return tuple(
            SimpleNamespace(
                agency_id=agency_id,
                platform=platform,
                description_template=getattr(upsert, "description_template", ""),
                title_template=getattr(upsert, "title_template", ""),
                hashtags=tuple(getattr(upsert, "hashtags", ()) or ()),
                created_at="",
                updated_at="",
            )
            for platform, upsert in templates.items()
        )


class StubMusic:
    def __init__(self, *, tracks: dict | None = None) -> None:
        self.tracks: dict[str, Any] = dict(tracks or {})
        self.add_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.delete_calls: list[str] = []

    def list_for_agency(self, agency_id: str) -> tuple:
        return tuple(
            track for track in self.tracks.values()
            if getattr(track, "agency_id", None) == agency_id
        )

    def get(self, *, music_id: str) -> Any:
        return self.tracks.get(music_id)

    def add_track(self, **kwargs: Any) -> Any:
        self.add_calls.append(kwargs)
        track = SimpleNamespace(**kwargs, created_at="now")
        self.tracks[kwargs["music_id"]] = track
        return track

    def update(self, *, music_id: str, **kwargs: Any) -> Any:
        existing = self.tracks.get(music_id)
        if existing is None:
            return None
        merged = {
            "music_id": music_id,
            "agency_id": existing.agency_id,
            "display_name": kwargs.get("display_name") or existing.display_name,
            "object_key": kwargs.get("object_key") or existing.object_key,
            "duration_seconds": kwargs.get("duration_seconds")
            or existing.duration_seconds,
            "is_default": (
                kwargs.get("is_default")
                if kwargs.get("is_default") is not None
                else existing.is_default
            ),
            "created_at": existing.created_at,
        }
        self.update_calls.append(merged)
        track = SimpleNamespace(**merged)
        self.tracks[music_id] = track
        return track

    def delete(self, *, music_id: str) -> bool:
        self.delete_calls.append(music_id)
        return self.tracks.pop(music_id, None) is not None


class StubRenderTemplates:
    def __init__(self, *, templates: dict[str, Any] | None = None) -> None:
        self.templates: dict[str, Any] = dict(templates or {})
        self.list_calls = 0
        self.get_calls: list[str] = []

    def get(self, template_id: str) -> Any:
        self.get_calls.append(template_id)
        return self.templates.get(template_id)

    def list_all(self) -> tuple:
        self.list_calls += 1
        return tuple(self.templates.values())


def build_uow(
    *,
    agency_present: bool = True,
    brand: StubBrand | None = None,
    defaults: StubDefaults | None = None,
    automation: StubAutomation | None = None,
    social_templates: StubSocialTemplates | None = None,
    music: StubMusic | None = None,
    render_templates: StubRenderTemplates | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        tenancy=SimpleNamespace(agencies=StubAgencies(present=agency_present)),
        configuration=SimpleNamespace(
            brand=brand or StubBrand(),
            defaults=defaults or StubDefaults(),
            automation=automation or StubAutomation(),
            social_templates=social_templates or StubSocialTemplates(),
            music=music or StubMusic(),
            render_templates=render_templates or StubRenderTemplates(),
        ),
    )


__all__ = [
    "StubAgencies",
    "StubAutomation",
    "StubBrand",
    "StubDefaults",
    "StubMusic",
    "StubRenderTemplates",
    "StubSocialTemplates",
    "build_uow",
]
