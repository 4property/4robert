"""Generic intro/outro concat helper for property reels.

Feature 34: feature 33 introduced ``concat_outro_to_reel`` (in
``outro_concat.py``) that pre-normalised a user-uploaded MP4/MOV and
concatenated it after the rendered reel. The same machinery works for
the intro variant — only the segment ordering changes — so we extract
it into :func:`concat_segment` and parameterise on ``position``.

The function is intentionally agnostic of "intro" vs "outro" naming:
``position="start"`` prepends ``segment_path`` to ``reel_path``,
``position="end"`` appends it. Both flows share the identical
normalisation pass (scale/pad/setsar=1/fps/yuv420p + AAC 44.1kHz stereo
+ silent-track fallback) so the concat demuxer cannot stutter on a
codec/SAR/sample-rate mismatch — see the feature 33 brief for the
trade-off rationale.

``outro_concat.py`` is preserved as a thin wrapper around this module so
the existing ``frame_composition.py:42`` import (feature 33) keeps
working without churn. Feature 34 adds a symmetric ``intro_concat.py``
wrapper for readability at the renderer call site.

The function is idempotent for the same inputs and leaves no temporary
files behind on success. On failure it raises
:class:`shared.errors.PropertyReelError` and the caller keeps the
pre-concat reel — a broken intro/outro concat must NOT lose the reel.
"""

from __future__ import annotations

import logging
import shutil
import subprocess  # nosec B404 — fixed argv to ffmpeg/ffprobe
import tempfile
from pathlib import Path
from typing import Literal

from shared.errors import PropertyReelError

logger = logging.getLogger(__name__)

SegmentPosition = Literal["start", "end"]


def concat_segment(
    *,
    ffmpeg_binary: str,
    reel_path: Path,
    segment_path: Path,
    output_path: Path,
    position: SegmentPosition,
    width: int,
    height: int,
    fps: int,
    audio_sample_rate: int = 44100,
    audio_channels: int = 2,
    stage: str = "video_segment_concat",
) -> Path:
    """Concatenate ``segment_path`` and ``reel_path`` into ``output_path``.

    ``position="start"`` produces ``segment + reel``; ``position="end"``
    produces ``reel + segment``. The segment is first re-encoded to
    match the reel's geometry (width, height, SAR=1:1, fps, yuv420p)
    and audio (AAC, 44.1kHz stereo, with silent fallback when the
    segment has no audio track). The concat is performed via the
    ``concat`` demuxer with ``-c copy`` so the reel bytes are not
    re-encoded a second time.

    Returns the resolved ``output_path`` on success. Raises
    :class:`PropertyReelError` if ffmpeg fails or the output is empty.
    """
    if position not in ("start", "end"):
        raise ValueError(f"Unsupported segment position: {position!r}")

    reel_path = Path(reel_path)
    segment_path = Path(segment_path)
    output_path = Path(output_path)

    if not reel_path.exists() or reel_path.stat().st_size == 0:
        raise PropertyReelError(
            "The base reel is missing or empty; cannot concat segment.",
            stage=stage,
            context={"reel_path": str(reel_path), "position": position},
            hint="The upstream reel render failed silently.",
        )
    if not segment_path.exists() or segment_path.stat().st_size == 0:
        raise PropertyReelError(
            "The uploaded intro/outro segment is missing on disk.",
            stage=stage,
            context={"segment_path": str(segment_path), "position": position},
            hint=(
                "Verify the segment asset blob is still present in the "
                "agency's _agency_intro/_agency_outro folder."
            ),
        )

    work_dir = Path(
        tempfile.mkdtemp(prefix="segment_concat_", dir=str(output_path.parent))
    )
    normalized_segment = work_dir / "segment_normalized.mp4"
    concat_list = work_dir / "concat_list.txt"
    try:
        _normalize_segment(
            ffmpeg_binary=ffmpeg_binary,
            segment_path=segment_path,
            normalized_path=normalized_segment,
            width=int(width),
            height=int(height),
            fps=int(fps),
            audio_sample_rate=int(audio_sample_rate),
            audio_channels=int(audio_channels),
            stage=stage,
        )
        ordered_segments: tuple[Path, ...]
        if position == "start":
            ordered_segments = (
                normalized_segment.resolve(),
                reel_path.resolve(),
            )
        else:
            ordered_segments = (
                reel_path.resolve(),
                normalized_segment.resolve(),
            )
        _write_concat_list(concat_list, ordered_segments)
        _run_concat_demuxer(
            ffmpeg_binary=ffmpeg_binary,
            concat_list_path=concat_list,
            output_path=output_path,
            stage=stage,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PropertyReelError(
            "The segment-concat ffmpeg pass did not produce an output file.",
            stage=stage,
            context={"output_path": str(output_path), "position": position},
        )
    return output_path


def _normalize_segment(
    *,
    ffmpeg_binary: str,
    segment_path: Path,
    normalized_path: Path,
    width: int,
    height: int,
    fps: int,
    audio_sample_rate: int,
    audio_channels: int,
    stage: str,
) -> None:
    """Re-encode the segment to match the reel's video + audio shape.

    Adds a silent audio track if the source has none — the concat
    demuxer requires symmetric stream layouts across all inputs, so a
    no-audio segment would otherwise refuse to mux against an AAC reel.
    """
    has_audio = _probe_has_audio(segment_path)
    video_filter = (
        f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={fps},format=yuv420p"
    )
    command: list[str] = [ffmpeg_binary, "-y"]
    if has_audio:
        command.extend(["-i", str(segment_path)])
    else:
        command.extend(
            [
                "-i",
                str(segment_path),
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=channel_layout=stereo:sample_rate={audio_sample_rate}",
            ]
        )
    command.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?" if has_audio else "1:a:0",
            "-vf",
            video_filter,
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            str(audio_sample_rate),
            "-ac",
            str(audio_channels),
            "-b:a",
            "192k",
        ]
    )
    if not has_audio:
        command.extend(["-shortest"])
    command.extend(["-movflags", "+faststart", str(normalized_path)])
    _run_ffmpeg(
        command,
        failure_message=(
            "ffmpeg failed while normalising the intro/outro segment "
            "before the final concat."
        ),
        output_path=normalized_path,
        stage=stage,
    )


def _write_concat_list(path: Path, segments: tuple[Path, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for segment in segments:
        escaped = segment.as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_concat_demuxer(
    *,
    ffmpeg_binary: str,
    concat_list_path: Path,
    output_path: Path,
    stage: str,
) -> None:
    command = [
        ffmpeg_binary,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run_ffmpeg(
        command,
        failure_message="ffmpeg failed while concatenating the reel with the segment.",
        output_path=output_path,
        stage=stage,
    )


def _run_ffmpeg(
    command: list[str],
    *,
    failure_message: str,
    output_path: Path,
    stage: str,
) -> None:
    completed = subprocess.run(  # nosec B603 — fixed argv, paths under control
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise PropertyReelError(
            f"{failure_message}\n{stderr}",
            stage=stage,
            context={
                "ffmpeg_binary": command[0],
                "output_path": str(output_path),
            },
            hint=(
                "Inspect the ffmpeg stderr above and verify the segment "
                "asset is a valid MP4/MOV with a single video stream."
            ),
        )


def _probe_has_audio(path: Path) -> bool:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return False
    completed = subprocess.run(  # nosec B603 — fixed argv
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        return False
    return "audio" in (completed.stdout or "").lower()


__all__ = ["SegmentPosition", "concat_segment"]
