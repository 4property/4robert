"""Tiny email-template renderer (feature 27).

Templates live under ``assets/email/templates/<name>.txt`` and
``<name>.html``. Placeholders use the ``str.format`` mini-language
(e.g. ``{property_title}``). The renderer never pulls in a real
templating engine (Jinja2, Mako, …) on purpose — these are not
user-editable, the formats are tiny, and the smaller surface keeps the
worker side dependency-free.

HTML escaping is applied to every context value when rendering an HTML
template; plain text values pass through verbatim. If a placeholder is
missing from ``context`` the renderer raises :class:`KeyError`, so
callers get a loud failure instead of silently leaking
``"{property_title}"`` into an email body.
"""

from __future__ import annotations

import html
from pathlib import Path
from threading import Lock
from typing import Mapping


_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "assets" / "email" / "templates"


class EmailTemplateRenderer:
    """Render plain-text + HTML email bodies from cached template files.

    The renderer caches the raw template source (string) per file path
    in-process so the worker does not re-read disk for every job. The
    cache is keyed by absolute path, which means swapping the templates
    in dev requires a worker restart — same trade-off as Django's
    ``cached.Loader``.
    """

    def __init__(self, *, templates_root: Path | None = None) -> None:
        self._root = (
            Path(templates_root).resolve() if templates_root is not None else _DEFAULT_ROOT
        )
        self._cache: dict[str, str] = {}
        self._lock = Lock()

    @property
    def templates_root(self) -> Path:
        return self._root

    def render_plain(self, template_name: str, context: Mapping[str, object]) -> str:
        """Return the rendered ``<template_name>.txt`` body.

        Raises :class:`FileNotFoundError` if the plain template is
        missing — every email kind MUST ship the plain variant (the
        HTML variant is optional).
        """

        source = self._load(template_name, "txt", required=True)
        assert source is not None  # required=True guarantees this
        return source.format_map(_NoneSafeMapping(context))

    def render_html(
        self, template_name: str, context: Mapping[str, object]
    ) -> str | None:
        """Return the rendered ``<template_name>.html`` body with every
        context value HTML-escaped.

        Returns ``None`` if the HTML variant does not exist on disk —
        that is the documented signal to the caller that the email
        should be sent as plain text only.
        """

        source = self._load(template_name, "html", required=False)
        if source is None:
            return None
        escaped_context = {
            key: html.escape(str(value), quote=True)
            for key, value in context.items()
        }
        return source.format_map(_NoneSafeMapping(escaped_context))

    def _load(
        self, template_name: str, suffix: str, *, required: bool
    ) -> str | None:
        path = self._root / f"{template_name}.{suffix}"
        cache_key = str(path)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        if not path.is_file():
            if required:
                raise FileNotFoundError(
                    f"Email template {template_name}.{suffix} not found at {path}"
                )
            return None
        source = path.read_text(encoding="utf-8")
        with self._lock:
            self._cache[cache_key] = source
        return source


class _NoneSafeMapping(dict):
    """Mapping wrapper that surfaces missing keys verbatim via
    :class:`KeyError`. We deliberately do NOT swallow missing keys —
    callers should pass a complete context, and a missing placeholder
    is a programming error worth crashing on.
    """

    def __init__(self, source: Mapping[str, object]) -> None:
        super().__init__()
        for key, value in source.items():
            self[key] = value


__all__ = ["EmailTemplateRenderer"]
