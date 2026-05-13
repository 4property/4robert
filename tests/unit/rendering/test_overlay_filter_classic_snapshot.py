"""Golden-snapshot test for the classic filter graph.

Feature 16 (pass-2 nit 3): the classic ``layout_variant`` must remain
byte-for-byte identical across releases — any silent drift in panel
geometry, drawtext ordering, default colors, or overlay chain would
ripple into every existing render. This test pins the *full* filter
graph emitted by :func:`build_overlay_filter` against an inline
snapshot. If you intentionally change the classic output, update the
snapshot literal in this file (don't mute the test).

Determinism:

- ``conftest.build_property_data`` / ``build_template`` produce a
  canonical fixture.
- The only environment-dependent token in the script is the absolute
  font path; we normalize it to ``<FONT_Bold>`` / ``<FONT_Regular>``
  before comparing so the snapshot is portable across machines.
"""

from __future__ import annotations

import re

from modules.rendering.infrastructure.ffmpeg.filters import build_overlay_filter
from tests.unit.rendering.conftest import build_property_data, build_template

_FONT_PATH_PATTERN = re.compile(
    r"fontfile='[^']*Inter[^']*?(Bold|Regular)\.ttf'",
)

# Pinned snapshot of the classic filter graph emitted by
# ``build_overlay_filter`` for the canonical fixture. Update only when
# you intend to change the classic render output.
EXPECTED_CLASSIC_FILTER_GRAPH = (
    "[video_base]"
    "drawbox=x=43:y=1584:w=994:h=278:color=black@0.46:t=fill,"
    "drawbox=x=43:y=58:w=994:h=374:color=black@0.38:t=fill,"
    "drawtext=fontfile='<FONT_Bold>':text='FOR SALE':fontcolor=white:"
    "fontsize=96:x=69:y=93:fix_bounds=1,"
    "drawtext=fontfile='<FONT_Bold>':text='€500\\,000':fontcolor=white:"
    "fontsize=88:x=69:y=201:fix_bounds=1,"
    "drawtext=fontfile='<FONT_Regular>':text='110 Example Road\\, Dublin 14':"
    "fontcolor=white:fontsize=42:x=69:y=301:fix_bounds=1,"
    "drawtext=fontfile='<FONT_Regular>':text='3 beds | 2 baths':fontcolor=white:"
    "fontsize=42:x=69:y=355:fix_bounds=1,"
    "drawtext=fontfile='<FONT_Bold>':text='Jane Doe':fontcolor=white:"
    "fontsize=50:x=275:y=1619:fix_bounds=1,"
    "drawtext=fontfile='<FONT_Regular>':text='+353 1 234 5678':fontcolor=white:"
    "fontsize=38:x=275:y=1677:fix_bounds=1,"
    "drawtext=fontfile='<FONT_Regular>':text='jane@example.com':fontcolor=white:"
    "fontsize=38:x=275:y=1723:fix_bounds=1,"
    "drawtext=fontfile='<FONT_Bold>':text='Caption.':fontcolor=0xF4D03F:"
    "fontsize=28:x=69+max((942-text_w)/2\\,0):y=1521:borderw=2:bordercolor=black@0.80:"
    "shadowx=0:shadowy=3:shadowcolor=black@0.75:text_shaping=1:fix_bounds=1:"
    "enable='between(t\\,0.000\\,2.500)'"
    "[video_with_property_panels];"
    "[video_with_property_panels][ber_icon]overlay=x=810:y=212"
    "[video_with_ber_panel];"
    "[video_with_ber_panel][agent_panel_image]overlay=x=69:y=1633"
    "[video_with_agent_panel];"
    "[video_with_agent_panel][logo_image]overlay=x=720:y=1640"
    "[video_with_agency_logo];"
    "[video_with_agency_logo]null[vout]"
)


def _normalize_font_paths(script: str) -> str:
    """Replace the absolute font path with a stable placeholder."""
    return _FONT_PATH_PATTERN.sub(r"fontfile='<FONT_\1>'", script)


def test_classic_filter_graph_matches_pinned_snapshot() -> None:
    actual = build_overlay_filter(
        build_property_data(),
        build_template(width=1080, height=1920),
        slide_captions=("Caption",),
        slide_duration=2.5,
        ber_icon_label="ber_icon",
        logo_image_label="logo_image",
    )
    actual_normalized = _normalize_font_paths(actual)
    assert actual_normalized == EXPECTED_CLASSIC_FILTER_GRAPH, (
        "Classic filter graph drifted from the pinned snapshot.\n"
        f"Expected:\n{EXPECTED_CLASSIC_FILTER_GRAPH}\n\nActual:\n{actual_normalized}"
    )


def test_classic_layout_variant_kwarg_default_is_identical_to_omitted() -> None:
    # Belt-and-braces: passing ``layout_variant='classic'`` explicitly
    # must produce the same output as omitting the kwarg entirely.
    common_kwargs = dict(
        slide_captions=("Caption",),
        slide_duration=2.5,
        ber_icon_label="ber_icon",
        logo_image_label="logo_image",
    )
    property_data = build_property_data()
    template = build_template(width=1080, height=1920)
    implicit = build_overlay_filter(property_data, template, **common_kwargs)
    explicit = build_overlay_filter(
        property_data, template, layout_variant="classic", **common_kwargs
    )
    assert implicit == explicit
