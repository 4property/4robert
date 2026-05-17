"""Unit tests for :class:`shared.email.templates.EmailTemplateRenderer`."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.email.templates import EmailTemplateRenderer


_DEFAULT_CONTEXT = {
    "agency_name": "CKP Properties",
    "property_title": "Casa Azul",
    "property_address": "Dublin 4, Ireland",
    "reel_url": "https://admin.example.com/reels?site_id=ckp.ie&property_id=42",
}


def _renderer() -> EmailTemplateRenderer:
    return EmailTemplateRenderer()


def test_render_plain_substitutes_every_placeholder() -> None:
    body = _renderer().render_plain("review_requested", _DEFAULT_CONTEXT)
    assert "CKP Properties" in body
    assert "Casa Azul" in body
    assert "Dublin 4, Ireland" in body
    assert (
        "https://admin.example.com/reels?site_id=ckp.ie&property_id=42" in body
    )
    assert "{property_title}" not in body
    assert "{reel_url}" not in body


def test_render_plain_includes_canonical_headers() -> None:
    body = _renderer().render_plain("review_requested", _DEFAULT_CONTEXT)
    assert body.startswith("Hi,")
    assert "A new reel is awaiting your approval" in body
    assert body.rstrip().endswith("— 4Reels")


def test_render_html_escapes_unsafe_characters_in_context_values() -> None:
    context = {
        "agency_name": "Cool & Co <Premium>",
        "property_title": "<script>alert(1)</script>",
        "property_address": "Dublin & Wicklow",
        "reel_url": "https://admin.example.com/reels?site_id=ckp.ie&property_id=42",
    }
    body = _renderer().render_html("review_requested", context)
    assert body is not None
    assert "Cool &amp; Co &lt;Premium&gt;" in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    # The literal "<script>" must not appear in the rendered HTML.
    assert "<script>" not in body
    # Templates own legitimate ``<html>``, ``<body>``, ``<a>`` tags;
    # those come from the template source, NOT from the context.
    assert "<a href=" in body
    # Ampersands in URLs survive (the URL came from the trusted source).
    assert "site_id=ckp.ie" in body


def test_render_html_returns_none_when_template_file_missing(tmp_path: Path) -> None:
    plain_only = tmp_path / "ping.txt"
    plain_only.write_text("hello {agency_name}", encoding="utf-8")
    renderer = EmailTemplateRenderer(templates_root=tmp_path)
    assert renderer.render_plain("ping", {"agency_name": "X"}) == "hello X"
    assert renderer.render_html("ping", {"agency_name": "X"}) is None


def test_render_plain_raises_when_template_missing(tmp_path: Path) -> None:
    renderer = EmailTemplateRenderer(templates_root=tmp_path)
    with pytest.raises(FileNotFoundError):
        renderer.render_plain("nonexistent", {})


def test_template_cache_returns_same_string_on_repeat_call(tmp_path: Path) -> None:
    template_file = tmp_path / "ping.txt"
    template_file.write_text("hi {name}", encoding="utf-8")
    renderer = EmailTemplateRenderer(templates_root=tmp_path)
    first = renderer.render_plain("ping", {"name": "Alice"})
    # Mutate the underlying file; the renderer must keep the cached
    # template, not re-read disk.
    template_file.write_text("HELLO {name}", encoding="utf-8")
    second = renderer.render_plain("ping", {"name": "Alice"})
    assert first == "hi Alice"
    assert second == "hi Alice"
