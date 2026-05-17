"""Canonical list of default NCS music tracks seeded for every agency.

Feature 23 ships every agency with a pool of royalty-free NCS-released
background tracks so the reel render pipeline always has something to
play even when the agency has not curated a custom library yet.

The literal filenames and display names are mirrored by the seed
migration ``alembic/versions/20260514_0005_seed_existing_agencies_with_ncs_music_tracks.py``.
If the canonical defaults change in the future, ship a NEW migration
that diffs against this module — the old migration stays as a
historical record, the seed-on-create hook in
:class:`modules.tenancy.application.use_cases.register_agency.RegisterAgencyUseCase`
always reads the current module so freshly created agencies receive
the latest defaults.

The ``filename`` field is the basename inside ``assets/music/`` in the
repo (case- and space-sensitive); ``display_name`` is the
human-readable label persisted in ``agency_music_tracks.display_name``.
The ``destination_filename`` is a marker-prefixed name written under
``workspace/generated_media/_agency_music/<agency>/`` so the seed
migration's downgrade can ``LIKE`` against the marker and remove only
the rows + blobs it created (uploads by the agency never collide).
"""

from __future__ import annotations

from dataclasses import dataclass


SEED_FILENAME_PREFIX = "_seed_ncs_"


@dataclass(frozen=True, slots=True)
class DefaultMusicTrackSeed:
    source_filename: str
    display_name: str
    destination_filename: str


DEFAULT_NCS_MUSIC_TRACK_SEEDS: tuple[DefaultMusicTrackSeed, ...] = (
    DefaultMusicTrackSeed(
        source_filename="N3b, Extra Terra - Silence [NCS Release].mp3",
        display_name="Silence (N3b, Extra Terra)",
        destination_filename=f"{SEED_FILENAME_PREFIX}silence.mp3",
    ),
    DefaultMusicTrackSeed(
        source_filename="ncs-music.mp3",
        display_name="NCS Default",
        destination_filename=f"{SEED_FILENAME_PREFIX}ncs_default.mp3",
    ),
    DefaultMusicTrackSeed(
        source_filename="sumu - apart [NCS Release].mp3",
        display_name="Apart (sumu)",
        destination_filename=f"{SEED_FILENAME_PREFIX}apart.mp3",
    ),
    DefaultMusicTrackSeed(
        source_filename="Sunny Lukas, Zushi & Vanko - Underrated (Feat. Sunny Lukas) [NCS Release].mp3",
        display_name="Underrated (Sunny Lukas, Zushi & Vanko)",
        destination_filename=f"{SEED_FILENAME_PREFIX}underrated.mp3",
    ),
)


__all__ = [
    "DEFAULT_NCS_MUSIC_TRACK_SEEDS",
    "DefaultMusicTrackSeed",
    "SEED_FILENAME_PREFIX",
]
