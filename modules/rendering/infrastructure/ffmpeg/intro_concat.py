"""Concatenate an uploaded intro video at the start of a rendered reel.

Feature 34: symmetric to :mod:`outro_concat` but the segment lands at
position 0 of the final reel. Both paths share the same normalisation
+ concat demuxer machinery via
:func:`modules.rendering.infrastructure.ffmpeg.video_segment_concat.concat_segment`.
This thin wrapper exists so the renderer call site reads symmetrically
to the outro one (``_prepend_intro_to_reel`` mirrors
``_append_outro_to_reel``) and the stage tag (``intro_concat``) is
emitted unchanged when raising :class:`shared.errors.PropertyReelError`.
"""

from __future__ import annotations

from pathlib import Path

from modules.rendering.infrastructure.ffmpeg.video_segment_concat import (
    concat_segment,
)


def concat_intro_to_reel(
    *,
    ffmpeg_binary: str,
    reel_path: Path,
    intro_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    audio_sample_rate: int = 44100,
    audio_channels: int = 2,
) -> Path:
    """Concatenate ``intro_path`` before ``reel_path`` into ``output_path``.

    Backward-symmetric wrapper over :func:`concat_segment` with
    ``position='start'``. See that function for the full normalisation
    contract.
    """
    return concat_segment(
        ffmpeg_binary=ffmpeg_binary,
        reel_path=reel_path,
        segment_path=intro_path,
        output_path=output_path,
        position="start",
        width=width,
        height=height,
        fps=fps,
        audio_sample_rate=audio_sample_rate,
        audio_channels=audio_channels,
        stage="intro_concat",
    )


__all__ = ["concat_intro_to_reel"]
