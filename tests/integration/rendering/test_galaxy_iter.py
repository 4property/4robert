"""Visual iteration rig for the galaxy render template (Feature 42).

This test is OPT-IN: it is marked with ``@pytest.mark.visual_iter`` and
excluded by default in ``pytest.ini`` (``addopts = -m "not visual_iter"``).
Invoke it explicitly when iterating on the galaxy template:

    .venv/bin/python -m pytest tests/integration/rendering/test_galaxy_iter.py \\
        -m visual_iter -q -s

The test renders a single poster frame at the reference resolution
(1054x1492 — same as ``example-template-galaxy.png``) using a real
property photo from ``property_media/`` plus realistic mock property
metadata, and writes the resulting PNG to
``progress/galaxy_iter_<N>.png`` where ``<N>`` is the next available
index (1-based). The leader compares the output against
``example-template-galaxy.png`` and decides whether to iterate again.

Heavy primitives (ffmpeg, font resolution, slide normalization) are
NOT mocked — the goal is to produce a real frame that looks like the
production render minus the central logo circle (explicitly out of
scope per the v1 product call).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from modules.rendering.infrastructure.models import (
    PropertyReelTemplate,
    PropertyRenderData,
)
from modules.rendering.infrastructure.poster import (
    generate_property_poster_from_data,
)
from tests.support.postgres import APPLICATION_ROOT


_GALAXY_REFERENCE_WIDTH = 1054
_GALAXY_REFERENCE_HEIGHT = 1492


def _resolve_next_iter_path() -> Path:
    """Find the next free ``progress/galaxy_iter_<N>.png`` slot."""
    progress_dir = APPLICATION_ROOT / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    for index in range(1, 1000):
        candidate = progress_dir / f"galaxy_iter_{index}.png"
        if not candidate.exists():
            return candidate
    raise RuntimeError("No free galaxy_iter_<N>.png slot available")


def _resolve_property_photo() -> Path:
    """Pick a real property photo from property_media/ as the slide source.

    Falls back to a synthetic colour PNG if no property media is
    available on disk (CI without seeded data). The synthetic fallback
    is a 1500x2000 navy panel — uglier than a real photo but enough to
    exercise the layout primitives.
    """
    candidates = sorted(
        (APPLICATION_ROOT / "property_media").rglob("primary_image.jpg"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    raise FileNotFoundError(
        "No primary_image.jpg found under property_media/; "
        "the visual iter rig needs at least one real photo on disk."
    )


@pytest.mark.visual_iter
def test_galaxy_visual_iter_renders_progress_png(tmp_path: Path) -> None:
    """Render a galaxy frame to ``progress/galaxy_iter_<N>.png``."""
    output_path = _resolve_next_iter_path()
    workspace_dir = tmp_path / "_workspace"
    selected_dir = workspace_dir / "property_media" / "site-a" / "galaxy-sample" / "selected_photos"
    selected_dir.mkdir(parents=True, exist_ok=True)

    photo_source = _resolve_property_photo()
    photo_path = selected_dir / "primary_image.jpg"
    shutil.copyfile(photo_source, photo_path)

    template = PropertyReelTemplate(
        width=_GALAXY_REFERENCE_WIDTH,
        height=_GALAXY_REFERENCE_HEIGHT,
        max_slide_count=1,
        include_intro=False,
        intro_duration_seconds=0.0,
    )

    property_data = PropertyRenderData(
        site_id="site-a",
        property_id=42,
        slug="galaxy-sample",
        title="Galaxy Lane, Dublin 4",
        link="https://example.com/galaxy-sample",
        property_status="For Sale",
        listing_lifecycle="for_sale",
        banner_text="FOR SALE",
        selected_image_dir=selected_dir,
        selected_image_paths=(photo_path,),
        featured_image_url=None,
        bedrooms=4,
        bathrooms=3,
        ber_rating="A2",
        agent_name="Jane Doe",
        agent_photo_url=None,
        agent_email="jane@example.com",
        agent_mobile=None,
        agent_number="+353 1 234 5678",
        agency_psra=None,
        agency_logo_url=None,
        agency_logo_local_path=None,
        price="500000",
        price_display_text="€500,000",
        property_type_label="Detached House",
        property_area_label="Dublin 4",
        property_county_label="Dublin",
        eircode="D04 ABCD",
        property_size="180 m²",
        selected_slides=(),
        accent_text_color=None,
        accent_background_color=None,
        # The reference uses a navy-blue panel + gold ribbon. These are
        # the exact cascades documented in feature 42 acceptance.
        side_banner_ribbon_background_color="#C9A24B",
        side_banner_panel_color="#0E2F59",
        subtitle_style=None,
        subtitles_override=None,
    )

    rendered = generate_property_poster_from_data(
        APPLICATION_ROOT,
        property_data,
        output_path=output_path.with_suffix(".jpg"),
        template=template,
        layout_variant="galaxy",
    )
    assert rendered.exists()
    assert rendered.stat().st_size > 0

    # Promote the JPG to the canonical .png slot so the leader's
    # ``progress/galaxy_iter_<N>.png`` contract holds. ffmpeg is the
    # easiest way to do this without pulling Pillow as a test dep.
    import subprocess

    from modules.rendering.infrastructure.runtime import resolve_ffmpeg_binary

    ffmpeg_binary = resolve_ffmpeg_binary()
    completed = subprocess.run(
        [
            ffmpeg_binary,
            "-y",
            "-i",
            str(rendered),
            "-frames:v",
            "1",
            "-c:v",
            "png",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"ffmpeg JPG→PNG conversion failed: {completed.stderr.strip()}"
        )
    rendered.unlink(missing_ok=True)

    assert output_path.exists()
    print(f"\n[galaxy_iter] wrote {output_path}")
