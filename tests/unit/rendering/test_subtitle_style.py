"""Unit tests for feature 31's ``SubtitleStyle`` cascade.

Covers:

* the ``SubtitleStyle`` dataclass defaults match the contract the rest of
  the renderer assumes (white text, outline background, bottom / centered,
  no uppercase, 36-char cap, enabled);
* ``frame_composition._build_subtitle_style`` materialises every
  documented ``subtitle_*`` key (snake_case) into the dataclass with the
  correct types;
* missing keys fall back to the dataclass defaults so a freshly-onboarded
  agency still renders the historical look;
* ``auto_captions_enabled=False`` flips ``SubtitleStyle.enabled`` off so
  the filters layer can skip every subtitle ``drawtext``.
"""

from __future__ import annotations

from modules.rendering.application.frame_composition import _build_subtitle_style
from modules.rendering.infrastructure.models import SubtitleStyle


def test_subtitle_style_defaults() -> None:
    style = SubtitleStyle()
    assert style.enabled is True
    assert style.font_family is None
    assert style.weight == "700"
    assert style.color == "#ffffff"
    assert style.bg_style == "outline"
    assert style.bg_color == "#0f1729"
    assert style.bg_opacity == 82
    assert style.position == "bottom"
    assert style.alignment == "center"
    assert style.uppercase is False
    assert style.max_chars == 36


def test_build_subtitle_style_from_full_settings() -> None:
    reel_settings = {
        "subtitle_font_family": "Manrope",
        "subtitle_weight": "500",
        "subtitle_color": "#FF0000",
        "subtitle_bg_style": "BLOCK",
        "subtitle_bg_color": "#000000",
        "subtitle_bg_opacity": 50,
        "subtitle_position": "TOP",
        "subtitle_alignment": "LEFT",
        "subtitle_uppercase": True,
        "subtitle_max_chars": 24,
        "auto_captions_enabled": True,
    }
    style = _build_subtitle_style(reel_settings)
    assert style.enabled is True
    assert style.font_family == "Manrope"
    assert style.weight == "500"
    assert style.color == "#FF0000"
    # bg_style / position / alignment are lowercased so the filters
    # layer can match against canonical tokens.
    assert style.bg_style == "block"
    assert style.bg_color == "#000000"
    assert style.bg_opacity == 50
    assert style.position == "top"
    assert style.alignment == "left"
    assert style.uppercase is True
    assert style.max_chars == 24


def test_build_subtitle_style_empty_settings_returns_defaults() -> None:
    style = _build_subtitle_style({})
    expected = SubtitleStyle()
    assert style == expected


def test_build_subtitle_style_auto_captions_false_disables_subtitles() -> None:
    style = _build_subtitle_style({"auto_captions_enabled": False})
    assert style.enabled is False


def test_build_subtitle_style_blank_strings_fall_back_to_defaults() -> None:
    """Whitespace-only values are treated as "not provided"."""
    style = _build_subtitle_style(
        {
            "subtitle_font_family": "   ",
            "subtitle_color": "",
            "subtitle_position": "   ",
        }
    )
    assert style.font_family is None
    assert style.color == "#ffffff"
    assert style.position == "bottom"


def test_build_subtitle_style_invalid_int_keeps_default() -> None:
    style = _build_subtitle_style(
        {"subtitle_bg_opacity": "not-a-number", "subtitle_max_chars": ""}
    )
    assert style.bg_opacity == 82
    assert style.max_chars == 36


def test_build_subtitle_style_uppercase_string_truthy() -> None:
    """The frontend persists booleans verbatim, but be defensive on strings."""
    style = _build_subtitle_style({"subtitle_uppercase": "true"})
    assert style.uppercase is True
