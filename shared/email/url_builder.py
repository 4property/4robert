"""Helpers that build deep-link URLs into the admin frontend.

Feature 27 emails point to ``/reels?site_id=<site>&property_id=<id>``,
which the SvelteKit frontend opens at the reels list and selects the
matching card. Centralised here so the templates do not duplicate URL
construction logic and so we have one place to test query-string
escaping.
"""

from __future__ import annotations

from urllib.parse import quote


def build_reel_editor_url(
    frontend_base_url: str,
    *,
    site_id: str,
    property_id: int,
) -> str:
    """Return the admin URL that targets one specific reel.

    ``frontend_base_url`` is the value of the ``FRONTEND_BASE_URL`` env
    var resolved by :func:`settings.notifications.load_notification_settings`.
    Trailing slashes are stripped so the result is canonical. The
    ``site_id`` is percent-escaped because it can technically contain
    characters that are not URL-safe (dots are kept verbatim by
    :func:`urllib.parse.quote`).
    """

    base = (frontend_base_url or "").rstrip("/")
    escaped_site = quote(str(site_id or ""), safe="")
    return f"{base}/reels?site_id={escaped_site}&property_id={int(property_id)}"


__all__ = ["build_reel_editor_url"]
