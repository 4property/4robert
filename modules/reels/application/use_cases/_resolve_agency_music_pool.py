"""Resolve the agency-scoped pool of background audio tracks.

Feature 23 wires the per-agency ``agency_music_tracks`` rows into the
render pipeline. The reels ingest use case queries the pool here and
the renderer consumes the resulting tuple of :class:`pathlib.Path`
objects via :class:`modules.reels.domain.types.PropertyContext`
(``background_audio_candidates``).

Selection rule (Feature 24):

1. List every track for the agency.
2. If at least one track has ``is_default=True``, use only those.
3. Otherwise, branch on ``fallback_to_full_library``:
   * ``True`` — fall back to the full library so an agency that toggled
     every default off but still curated a library keeps rendering.
   * ``False`` — raise :class:`PropertyReelError` with code
     ``MUSIC_NO_DEFAULT_TRACKS`` so the reel fails loudly instead of
     silently using a non-default track.
4. If the library is empty (regardless of the flag), raise
   :class:`PropertyReelError` with code ``MUSIC_NO_TRACKS``.

The helper is intentionally a free function (no class state) so unit
tests can call it directly with a stub UoW and reels use cases can
import it without instantiating a service object.

Layer note: this module lives in ``modules/reels/application`` which is
allowed to read domain types from ``modules/configuration`` and the
``shared.storage`` site_layout. The rendering helper is invoked here
(not inside ``modules/rendering``) so the rendering bounded context
never imports from configuration application/infrastructure.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from modules.rendering.infrastructure.runtime.assets import (
    resolve_agency_music_local_paths,
)
from shared.errors import PropertyReelError

if TYPE_CHECKING:  # pragma: no cover - import only for type hints
    from shared.db import DatabaseUnitOfWork


def resolve_agency_background_audio_candidates(
    *,
    uow: "DatabaseUnitOfWork",
    agency_id: str,
    workspace_dir: Path,
    fallback_to_full_library: bool = True,
) -> tuple[Path, ...]:
    """Return the agency background audio Paths for the next render.

    The lookup is best-effort against unit-test UoWs that omit the
    ``configuration`` namespace: when the music repo is missing the
    function returns an empty tuple so the renderer falls back to the
    legacy ``assets/music/`` scan via ``music_tracks=None``. Real prod
    UoWs always carry ``configuration.music`` and never hit the
    fallback.

    ``fallback_to_full_library`` is the persisted Feature 24 flag — the
    caller reads it from
    ``agency_reel_defaults.settings.music.selection_rules.fallback_to_full_library``
    (with a default of ``True`` when absent) and forwards the resolved
    value here. The flag only affects the "no default tracks" branch:
    when at least one default track exists the pool is built from those
    tracks regardless of the flag.
    """
    normalized_agency_id = str(agency_id or "").strip()
    if not normalized_agency_id:
        return ()
    configuration = getattr(uow, "configuration", None)
    if configuration is None:
        return ()
    music_repo = getattr(configuration, "music", None)
    if music_repo is None:
        return ()

    all_tracks = music_repo.list_for_agency(normalized_agency_id)
    if not all_tracks:
        raise PropertyReelError(
            "The agency has no music tracks available for the reel render.",
            stage="prepare",
            code="MUSIC_NO_TRACKS",
            context={"agency_id": normalized_agency_id},
            hint=(
                "Upload at least one music track via "
                "POST /v1/admin/agencies/{id}/music/upload, or run the "
                "seed migration to repopulate the default NCS tracks."
            ),
        )

    default_tracks = tuple(track for track in all_tracks if bool(track.is_default))
    if default_tracks:
        selected_tracks = default_tracks
    elif fallback_to_full_library:
        selected_tracks = tuple(all_tracks)
    else:
        # Feature 24: the agency disabled the library fallback. The
        # default pool is empty so the reel must fail loudly instead of
        # silently picking a non-default track.
        raise PropertyReelError(
            "The agency has no default music tracks and the library "
            "fallback is disabled.",
            stage="prepare",
            code="MUSIC_NO_DEFAULT_TRACKS",
            context={"agency_id": normalized_agency_id},
            hint=(
                "Mark at least one music track as default via "
                "PUT /v1/admin/agencies/{id}/music/{music_id} "
                "(`is_default=true`), or enable the library fallback "
                "via PUT /v1/admin/agencies/{id}/defaults with "
                "settings.music.selection_rules.fallback_to_full_library=true."
            ),
        )

    return resolve_agency_music_local_paths(
        workspace_dir=workspace_dir,
        music_tracks=selected_tracks,
    )


__all__ = ["resolve_agency_background_audio_candidates"]
