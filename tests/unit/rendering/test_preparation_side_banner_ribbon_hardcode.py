"""Unit tests for the side_banner ribbon background colour.

Feature 17 introduced the ``#FECF4D`` hardcoded fallback for the vertical
status ribbon. Feature 29 keeps that fallback as the global default but
parameterises the colour so the renderer can honour
``BrandSettings.secondary_color`` per agency: the call site now reads
``property_data.side_banner_ribbon_background_color`` first and only
falls back to ``_SIDE_BANNER_RIBBON_BACKGROUND`` when the brand override
is absent. The accent_* fields keep driving the top/bottom panels (reel
+ poster).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from modules.rendering.infrastructure import preparation as preparation_module
from modules.rendering.infrastructure.preparation import (
    _SIDE_BANNER_RIBBON_BACKGROUND,
    _render_vertical_status_banner,
    _resolve_vertical_banner_layout,
    prepare_reel_render_assets,
)
from tests.unit.rendering.conftest import build_property_data, build_template


def test_side_banner_ribbon_background_constant_value() -> None:
    """Hotfix 2026-05-15: the historical ``#FECF4D`` was a temporary
    visual probe; the canonical fallback is now Tailwind ``gray-400``
    (``#9CA3AF``) so an unconfigured agency renders a neutral grey
    ribbon instead of an unexpected yellow stripe.
    """
    assert _SIDE_BANNER_RIBBON_BACKGROUND == "#9CA3AF"


def test_render_vertical_status_banner_uses_supplied_background_for_drawbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``background_hex`` flows verbatim into the ffmpeg drawbox filter.

    Feature 29: the caller is responsible for resolving the cascade
    (brand secondary → hardcoded fallback). ``_render_vertical_status_banner``
    accepts the resolved value as-is and only falls back to its own
    navy default when ``background_hex`` is ``None``.
    """
    captured: dict[str, list[str]] = {}

    def _fake_run(command, capture_output, text, check):  # type: ignore[no-untyped-def]
        captured["command"] = list(command)
        output_path = Path(command[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        class _Completed:
            returncode = 0
            stderr = ""

        return _Completed()

    monkeypatch.setattr(preparation_module.subprocess, "run", _fake_run)

    property_data = build_property_data(
        accent_background_color="#e22f8c",
        accent_text_color="#ffffff",
        property_status="For Sale",
    )

    output_path = tmp_path / "vertical_status_banner.png"
    _render_vertical_status_banner(
        ffmpeg_binary="/usr/bin/ffmpeg",
        output_path=output_path,
        width=132,
        height=588,
        notch_height=48,
        text="FOR SALE",
        background_hex=_SIDE_BANNER_RIBBON_BACKGROUND,
        text_hex=property_data.accent_text_color,
        font_path=Path("/tmp/fake-font.ttf"),
        property_data=property_data,
    )

    command = captured["command"]
    assert "-vf" in command
    filter_graph = command[command.index("-vf") + 1]
    # Hotfix 2026-05-15: the default ribbon colour is the neutral grey
    # ``#9CA3AF`` (``gray-400``) — the previous ``#FECF4D`` amber probe
    # is gone.
    assert "color=0x9ca3af@1.00" in filter_graph
    assert "0xfecf4d" not in filter_graph
    # The per-property accent must NOT leak into the ribbon — the
    # WordPress webhook feed is no longer consulted at this layer.
    assert "0xe22f8c" not in filter_graph
    assert "@0.85" not in filter_graph


def test_render_vertical_status_banner_honours_brand_secondary_color(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Feature 29: a brand secondary HEX wins over the hardcoded fallback."""
    captured: dict[str, list[str]] = {}

    def _fake_run(command, capture_output, text, check):  # type: ignore[no-untyped-def]
        captured["command"] = list(command)
        output_path = Path(command[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        class _Completed:
            returncode = 0
            stderr = ""

        return _Completed()

    monkeypatch.setattr(preparation_module.subprocess, "run", _fake_run)

    property_data = build_property_data(
        accent_text_color="#ffffff",
        property_status="For Sale",
    )

    output_path = tmp_path / "vertical_status_banner.png"
    _render_vertical_status_banner(
        ffmpeg_binary="/usr/bin/ffmpeg",
        output_path=output_path,
        width=132,
        height=588,
        notch_height=48,
        text="FOR SALE",
        background_hex="#FF00FF",
        text_hex=property_data.accent_text_color,
        font_path=Path("/tmp/fake-font.ttf"),
        property_data=property_data,
    )

    command = captured["command"]
    filter_graph = command[command.index("-vf") + 1]
    assert "color=0xff00ff@1.00" in filter_graph
    assert "0xfecf4d" not in filter_graph


def test_prepare_reel_render_assets_wires_secondary_color_cascade() -> None:
    """The call site reads the brand override then falls back to the constant.

    Feature 29 source-level guard: the call to
    ``_render_vertical_status_banner`` must pass
    ``property_data.side_banner_ribbon_background_color`` first and only
    use ``_SIDE_BANNER_RIBBON_BACKGROUND`` as fallback. A regression that
    drops the override (e.g. reintroduces ``background_hex=_SIDE_BANNER_RIBBON_BACKGROUND``
    unconditionally) would silently break per-agency colours, so we
    inspect the source to be explicit.
    """
    source = inspect.getsource(prepare_reel_render_assets)
    assert "_render_vertical_status_banner(" in source
    assert "side_banner_ribbon_background_color" in source
    assert "_SIDE_BANNER_RIBBON_BACKGROUND" in source
    # Must NOT have reverted to the property accent (feature 17 unwired
    # that) and must NOT be hardcoded-only (feature 29 reintroduces the
    # parameterised cascade).
    assert "background_hex=property_data.accent_background_color" not in source


def test_resolve_vertical_banner_layout_uses_taller_body_height() -> None:
    """Feature 17 lengthens the ribbon body to ~32.5% of frame height."""
    layout = _resolve_vertical_banner_layout(build_template(width=1080, height=1920))
    assert layout is not None
    notch_height = layout["notch_height"]
    body_height = layout["height"] - notch_height
    assert body_height >= round(1920 * 0.325)
