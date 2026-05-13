"""Unit tests for HTML entity decoding inside `normalize_caption`.

Feature 12 `unescape_html_entities_everywhere` — captions that flow to the MP4
subtitle overlay must be decoded so `&#8217;`, `&amp;`, `&quot;`, `&#x2019;`
never reach ffmpeg. ``normalize_caption`` is the final hop before captions are
written into the slide manifest and the layout subtitles fallback.

This file covers the six mandated cases (decimal numeric, hex numeric, named,
nested, idempotency, empty input) for the rendering integration point.
"""

from __future__ import annotations

import sys
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[3]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from modules.rendering.infrastructure.ai_photo_selection.prompting import normalize_caption


def test_normalize_caption_decodes_decimal_numeric_entity() -> None:
    assert normalize_caption("Dublin&#8217;s elegant home") == "Dublin’s elegant home."


def test_normalize_caption_decodes_hex_numeric_entity() -> None:
    assert normalize_caption("Owner&#x2019;s private suite") == "Owner’s private suite."


def test_normalize_caption_decodes_named_entities() -> None:
    # NOTE: `normalize_caption` strips wrapping ``"`` and ``'`` characters
    # (legacy behavior, unrelated to feature 12). The decoded ``&quot;`` that
    # lands at the END of the string is therefore stripped before the trailing
    # period is appended, which is intentional — captions wrapped in stray
    # quotes from upstream get tidied up. We assert the round-trip on a case
    # where the decoded characters live in the middle of the string.
    assert (
        normalize_caption("Smith &amp; Sons present &quot;The Property&quot; here")
        == 'Smith & Sons present "The Property" here.'
    )


def test_normalize_caption_decodes_nested_entities_one_level() -> None:
    """``html.unescape`` decodes one level only — ``&amp;amp;`` → ``&amp;``.

    Captures the documented behavior so future maintainers do not assume the
    pipeline double-decodes silently.
    """
    assert normalize_caption("A &amp;amp; B") == "A &amp; B."


def test_normalize_caption_is_idempotent_on_already_decoded_text() -> None:
    first_pass = normalize_caption("Dublin’s elegant home.")
    second_pass = normalize_caption(first_pass)

    assert first_pass == "Dublin’s elegant home."
    assert second_pass == "Dublin’s elegant home."


def test_normalize_caption_returns_fallback_for_empty_input() -> None:
    assert normalize_caption("", fallback="Bright family home.") == "Bright family home."
    assert normalize_caption(None, fallback="Bright family home.") == "Bright family home."


def test_normalize_caption_strips_html_entities_before_appending_terminator() -> None:
    """Edge case: input ends in a decoded entity that yields a sentence terminator.

    Ensures the entity decoding runs BEFORE the ``[-1] in ".!?"`` check, so we
    do not append a redundant period to ``Hello&#33;`` → ``Hello!``.
    """
    assert normalize_caption("Hello&#33;") == "Hello!"
