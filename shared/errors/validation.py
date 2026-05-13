"""Pure validation helpers for inbound webhook / payload data.

These helpers are lightweight predicates (no exceptions, no logging) so
callers can decide whether to log a warning, raise a
:class:`shared.errors.ValidationError`, or silently fall back to a
default. Feature 16 introduced :func:`is_valid_hex_color` to vet the
per-property accent colors arriving from the WordPress webhook
(``wppd_accent_text_color`` / ``wppd_accent_background_color``).
"""

from __future__ import annotations

import re

# 3, 4, 6, or 8 hex digits with optional leading "#". Matches:
#   "#fff", "fff", "#ffff", "ffff", "#ffffff", "ffffff",
#   "#ffffffff", "ffffffff" (the 4 / 8 digit forms include alpha).
_HEX_COLOR_PATTERN = re.compile(r"^#?(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def is_valid_hex_color(value: str | None) -> bool:
    """Return whether ``value`` parses as a HEX color string.

    ``None`` is considered valid (the field is optional and the
    renderer falls back to a default). Empty / whitespace-only strings
    are *not* valid: callers that want "missing" should pass ``None``
    instead so we can distinguish an actively malformed webhook payload
    from a field that was never provided.

    Accepts 3 / 4 / 6 / 8 digit forms with or without a leading ``#``
    (the 4 and 8 digit forms include alpha; the rendering pipeline
    discards alpha downstream but ingestion still treats them as valid
    HEX). Comparison is case-insensitive. Leading and trailing
    whitespace is tolerated.
    """
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return _HEX_COLOR_PATTERN.fullmatch(value.strip()) is not None


__all__ = ["is_valid_hex_color"]
