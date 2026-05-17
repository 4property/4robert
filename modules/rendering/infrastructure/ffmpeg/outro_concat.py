"""Concatenate an uploaded outro video at the end of a rendered reel.

Feature 33 introduced the original implementation here. Feature 34
factored the heavy lifting out to
:mod:`modules.rendering.infrastructure.ffmpeg.video_segment_concat` so
the symmetric intro path could reuse the same normalisation + concat
demuxer logic. This module is a thin wrapper that preserves the
``concat_outro_to_reel`` symbol and stage name (``outro_concat``) the
frame composition pipeline already imports.
"""

from __future__ import annotations

from pathlib import Path

from modules.rendering.infrastructure.ffmpeg.video_segment_concat import (
    concat_segment,
)


def concat_outro_to_reel(
    *,
    ffmpeg_binary: str,
    reel_path: Path,
    outro_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    audio_sample_rate: int = 44100,
    audio_channels: int = 2,
) -> Path:
    """Concatenate ``outro_path`` after ``reel_path`` into ``output_path``.

    Backward-compatible wrapper over :func:`concat_segment` with
    ``position='end'``. See that function for the full normalisation
    contract.
    """
    return concat_segment(
        ffmpeg_binary=ffmpeg_binary,
        reel_path=reel_path,
        segment_path=outro_path,
        output_path=output_path,
        position="end",
        width=width,
        height=height,
        fps=fps,
        audio_sample_rate=audio_sample_rate,
        audio_channels=audio_channels,
        stage="outro_concat",
    )


__all__ = ["concat_outro_to_reel"]
