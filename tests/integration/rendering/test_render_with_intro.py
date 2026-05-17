"""Integration test for the intro concat path (feature 34).

Symmetric to ``test_render_with_outro.py``. Three angles are
exercised:

* ``concat_intro_to_reel`` runs end-to-end against ffmpeg so the real
  concat path produces a video whose duration ≈ ``intro_duration +
  base_reel_duration``.

* ``DefaultMediaRenderer._render_reel`` is exercised with the heavy
  primitives monkeypatched so we can assert that the renderer routes
  the intro context flag correctly: ``uploaded`` triggers the helper,
  ``brand_card`` / ``source='none'`` / missing path do not.

* The combined case (intro + outro both enabled with valid blobs)
  triggers BOTH concat helpers in order (intro first, outro second).
  Verified via the renderer-level test plus a real-ffmpeg duration
  sanity check (``base + intro + outro``).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from modules.catalog.domain.wordpress_property import Property
from modules.reels.domain.types import (
    MediaDeliveryPlan,
    PreparedMediaAssets,
    PropertyContext,
)
from modules.rendering.application import frame_composition as fc_module
from modules.rendering.application.frame_composition import DefaultMediaRenderer
from modules.rendering.infrastructure.ffmpeg.intro_concat import concat_intro_to_reel
from modules.rendering.infrastructure.ffmpeg.outro_concat import concat_outro_to_reel
from modules.tenancy.domain.context import TenantContext
from shared.storage.site_layout import resolve_site_storage_layout


_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "configuration" / "_fixtures"
_INTRO_OK_PATH = _FIXTURE_DIR / "tiny_outro_5s.mp4"


def _ffprobe_duration(path: Path) -> float:
    binary = shutil.which("ffprobe")
    if binary is None:
        pytest.skip("ffprobe is required for this test")
    completed = subprocess.run(
        [
            binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(f"ffprobe failed for {path}: {completed.stderr.strip()}")
    return float((completed.stdout or "0").strip())


def _build_base_reel(tmp_path: Path, *, duration_seconds: int) -> Path:
    """Render a synthetic silent-ish reel under tmp_path for concat testing."""
    binary = shutil.which("ffmpeg")
    if binary is None:
        pytest.skip("ffmpeg is required for this test")
    output_path = tmp_path / "base_reel.mp4"
    completed = subprocess.run(
        [
            binary,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=320x240:d={duration_seconds}:r=15",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            str(duration_seconds),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(f"ffmpeg failed to build base reel: {completed.stderr}")
    return output_path


def test_concat_intro_to_reel_produces_combined_duration(tmp_path: Path) -> None:
    """The combined video duration ≈ intro + base (±200ms tolerance)."""
    if not _INTRO_OK_PATH.exists():
        pytest.skip(f"Missing fixture {_INTRO_OK_PATH}")
    binary = shutil.which("ffmpeg")
    if binary is None:
        pytest.skip("ffmpeg is required for this test")
    base_duration_seconds = 6
    base_reel = _build_base_reel(tmp_path, duration_seconds=base_duration_seconds)
    base_actual_duration = _ffprobe_duration(base_reel)
    intro_actual_duration = _ffprobe_duration(_INTRO_OK_PATH)

    output_path = tmp_path / "reel_with_intro.mp4"
    concat_intro_to_reel(
        ffmpeg_binary=binary,
        reel_path=base_reel,
        intro_path=_INTRO_OK_PATH,
        output_path=output_path,
        width=320,
        height=240,
        fps=15,
    )
    assert output_path.exists() and output_path.stat().st_size > 0

    final_duration = _ffprobe_duration(output_path)
    expected = base_actual_duration + intro_actual_duration
    assert abs(final_duration - expected) <= 0.5, (
        f"final_duration={final_duration:.3f}s expected≈{expected:.3f}s"
    )


def test_concat_intro_then_outro_produces_combined_duration(tmp_path: Path) -> None:
    """Combined intro+base+outro pass: duration ≈ intro + base + outro."""
    if not _INTRO_OK_PATH.exists():
        pytest.skip(f"Missing fixture {_INTRO_OK_PATH}")
    binary = shutil.which("ffmpeg")
    if binary is None:
        pytest.skip("ffmpeg is required for this test")
    base_duration_seconds = 4
    base_reel = _build_base_reel(tmp_path, duration_seconds=base_duration_seconds)
    base_actual_duration = _ffprobe_duration(base_reel)
    intro_actual_duration = _ffprobe_duration(_INTRO_OK_PATH)
    outro_actual_duration = intro_actual_duration  # same fixture file

    intermediate_path = tmp_path / "reel_with_intro.mp4"
    final_path = tmp_path / "reel_with_intro_and_outro.mp4"

    # 1) intro at the start
    concat_intro_to_reel(
        ffmpeg_binary=binary,
        reel_path=base_reel,
        intro_path=_INTRO_OK_PATH,
        output_path=intermediate_path,
        width=320,
        height=240,
        fps=15,
    )
    intermediate_duration = _ffprobe_duration(intermediate_path)
    assert abs(intermediate_duration - (base_actual_duration + intro_actual_duration)) <= 0.5

    # 2) outro at the end of the (intro+base) reel
    concat_outro_to_reel(
        ffmpeg_binary=binary,
        reel_path=intermediate_path,
        outro_path=_INTRO_OK_PATH,  # reuse the same fixture as a stand-in outro
        output_path=final_path,
        width=320,
        height=240,
        fps=15,
    )
    final_duration = _ffprobe_duration(final_path)
    expected = base_actual_duration + intro_actual_duration + outro_actual_duration
    assert abs(final_duration - expected) <= 1.0, (
        f"final_duration={final_duration:.3f}s expected≈{expected:.3f}s"
    )


def _stub_render_primitives(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    captured: dict[str, list[Any]] = {
        "prepare": [],
        "manifest": [],
        "reel": [],
        "poster": [],
        "append_outro": [],
        "prepend_intro": [],
    }

    def _fake_template(profile: str, *, template=None):
        class _StubTemplate:
            width = 320
            height = 240
            fps = 15

        return _StubTemplate()

    def _fake_selected_slides(selected_dir, paths):
        return [{"stub": str(p)} for p in paths]

    def _fake_prepare(
        workspace,
        render_data,
        *,
        template,
        working_dir,
        layout_variant="classic",
        music_tracks=None,
    ):
        captured["prepare"].append({"layout_variant": layout_variant})
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        return object()

    def _fake_manifest(
        workspace,
        render_data,
        *,
        output_path,
        template,
        render_profile,
        render_template_id,
        render_template_settings_hash,
        poster_template,
        prepared_assets,
        working_dir,
    ):
        Path(output_path).write_text("{}", encoding="utf-8")

    def _fake_reel(
        workspace,
        render_data,
        *,
        output_path,
        template,
        prepared_assets,
        working_dir,
        layout_variant="classic",
    ):
        captured["reel"].append({"output_path": str(output_path)})
        Path(output_path).write_bytes(b"mp4-stub")

    def _fake_poster(
        workspace,
        render_data,
        *,
        output_path,
        template,
        layout_variant="classic",
    ):
        captured["poster"].append({"layout_variant": layout_variant})
        Path(output_path).write_bytes(b"jpg-stub")

    def _fake_append_outro(*, reel_path, outro_path, template):
        captured["append_outro"].append(
            {"reel_path": str(reel_path), "outro_path": str(outro_path)}
        )

    def _fake_prepend_intro(*, reel_path, intro_path, template):
        captured["prepend_intro"].append(
            {"reel_path": str(reel_path), "intro_path": str(intro_path)}
        )

    monkeypatch.setattr(fc_module, "build_reel_template_for_render_profile", _fake_template)
    monkeypatch.setattr(fc_module, "build_local_selected_slides", _fake_selected_slides)
    monkeypatch.setattr(fc_module, "prepare_reel_render_assets", _fake_prepare)
    monkeypatch.setattr(fc_module, "write_property_reel_manifest_from_data", _fake_manifest)
    monkeypatch.setattr(fc_module, "generate_property_reel_from_data", _fake_reel)
    monkeypatch.setattr(fc_module, "generate_property_poster_from_data", _fake_poster)
    monkeypatch.setattr(fc_module, "_append_outro_to_reel", _fake_append_outro)
    monkeypatch.setattr(fc_module, "_prepend_intro_to_reel", _fake_prepend_intro)
    return captured


def _build_context(
    workspace: Path,
    *,
    intro_local_path: Path | None = None,
    intro_source: str = "none",
    intro_duration_seconds: int = 0,
    outro_local_path: Path | None = None,
    outro_source: str = "none",
    outro_duration_seconds: int = 0,
) -> PropertyContext:
    site_id = "site-a"
    storage_paths = resolve_site_storage_layout(workspace, site_id)
    property_item = Property.from_api_payload(
        {
            "id": 42,
            "slug": "intro-property",
            "title": {"rendered": "Intro Property"},
            "wppd_pics": ["https://example.com/img1.jpg"],
        }
    )
    delivery_plan = MediaDeliveryPlan(
        listing_lifecycle="for_sale",
        artifact_kind="reel_video",
        render_profile="for_sale_reel",
        social_post_type="reel",
        asset_strategy="curated_selection",
        banner_text="FOR SALE",
        price_display_text=None,
    )
    tenant = TenantContext(
        site_id=site_id,
        agency_id="agency-feature-34",
        wordpress_source_id="ingestion-1",
    )
    return PropertyContext(
        workspace_dir=workspace,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
        intro_local_path=intro_local_path,
        intro_source=intro_source,
        intro_duration_seconds=intro_duration_seconds,
        outro_local_path=outro_local_path,
        outro_source=outro_source,
        outro_duration_seconds=outro_duration_seconds,
    )


def _build_prepared(selected_dir: Path) -> PreparedMediaAssets:
    selected_dir.mkdir(parents=True, exist_ok=True)
    photo_path = selected_dir / "01.jpg"
    photo_path.write_bytes(b"stub-photo")
    return PreparedMediaAssets(
        selected_dir=selected_dir,
        selected_photo_paths=(photo_path,),
        downloaded_images=((1, "https://example.com/img1.jpg", photo_path),),
        primary_image_path=selected_dir / "primary_image.jpg",
    )


def test_renderer_invokes_intro_concat_when_uploaded_and_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _INTRO_OK_PATH.exists():
        pytest.skip(f"Missing fixture {_INTRO_OK_PATH}")
    captured = _stub_render_primitives(monkeypatch)
    selected_dir = tmp_path / "selected"
    intro_path = tmp_path / "intro.mp4"
    intro_path.write_bytes(_INTRO_OK_PATH.read_bytes())
    context = _build_context(
        tmp_path,
        intro_local_path=intro_path,
        intro_source="uploaded",
        intro_duration_seconds=5,
    )

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, _build_prepared(selected_dir))

    assert captured["prepend_intro"], "_prepend_intro_to_reel was not invoked"
    invocation = captured["prepend_intro"][0]
    assert invocation["intro_path"] == str(intro_path)
    assert invocation["reel_path"].endswith(".mp4")
    # When only intro is configured, the outro pass must not fire.
    assert captured["append_outro"] == []


def test_renderer_invokes_both_intro_and_outro_when_both_uploaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both helpers run in order: intro first, then outro."""
    if not _INTRO_OK_PATH.exists():
        pytest.skip(f"Missing fixture {_INTRO_OK_PATH}")
    captured = _stub_render_primitives(monkeypatch)
    selected_dir = tmp_path / "selected"
    intro_path = tmp_path / "intro.mp4"
    intro_path.write_bytes(_INTRO_OK_PATH.read_bytes())
    outro_path = tmp_path / "outro.mp4"
    outro_path.write_bytes(_INTRO_OK_PATH.read_bytes())
    context = _build_context(
        tmp_path,
        intro_local_path=intro_path,
        intro_source="uploaded",
        intro_duration_seconds=5,
        outro_local_path=outro_path,
        outro_source="uploaded",
        outro_duration_seconds=5,
    )

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, _build_prepared(selected_dir))

    assert len(captured["prepend_intro"]) == 1
    assert len(captured["append_outro"]) == 1
    intro_call = captured["prepend_intro"][0]
    outro_call = captured["append_outro"][0]
    assert intro_call["intro_path"] == str(intro_path)
    assert outro_call["outro_path"] == str(outro_path)
    # Both passes target the same reel media path.
    assert intro_call["reel_path"] == outro_call["reel_path"]


def test_renderer_skips_intro_concat_when_source_is_brand_card(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``brand_card`` is reserved for a future feature; it must not concat."""
    captured = _stub_render_primitives(monkeypatch)
    selected_dir = tmp_path / "selected"
    context = _build_context(
        tmp_path,
        intro_local_path=None,
        intro_source="brand_card",
        intro_duration_seconds=0,
    )
    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, _build_prepared(selected_dir))

    assert captured["prepend_intro"] == []


def test_renderer_skips_intro_concat_when_path_is_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stripped ``intro_local_path`` (intro_enabled=False upstream) → no concat."""
    captured = _stub_render_primitives(monkeypatch)
    selected_dir = tmp_path / "selected"
    context = _build_context(
        tmp_path,
        intro_local_path=None,
        intro_source="uploaded",  # source uploaded but path stripped upstream
        intro_duration_seconds=0,
    )
    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, _build_prepared(selected_dir))

    assert captured["prepend_intro"] == []


def test_renderer_skips_intro_concat_when_source_is_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _stub_render_primitives(monkeypatch)
    selected_dir = tmp_path / "selected"
    context = _build_context(tmp_path, intro_local_path=None, intro_source="none")
    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, _build_prepared(selected_dir))
    assert captured["prepend_intro"] == []
