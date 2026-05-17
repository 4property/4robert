"""Email validation + normalisation helpers (feature 27).

Used by the dispatcher (``modules.notifications.application.use_cases.
dispatch_review_requested_email``) to filter and dedupe the raw
``reviewEmails`` payload pulled from
``agency_reel_defaults.settings.automation.reviewEmails``. The shape
contract is "list of strings, lowercased, no duplicates, syntactically
valid". Bad shapes coming from legacy CSV strings or stray non-string
values are dropped silently — the dispatcher never crashes the worker
on bad input.

Layer rule: this module has zero non-stdlib imports and zero
dependencies on settings/ or modules/. Anyone can import it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


# Pragmatic regex aligned with the front-end ``src/lib/utils/email.js``
# helper (feature 26 of the front, chip editor). Not RFC 5322 perfect on
# purpose — we want symmetry with the client validator, not a strict
# parser. Quoted local-parts and IP-literal domains are rejected by
# design.
EMAIL_PATTERN: re.Pattern[str] = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def is_valid_email(value: object) -> bool:
    """Return ``True`` if ``value`` is a string that matches
    :data:`EMAIL_PATTERN` after stripping whitespace."""
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate:
        return False
    return EMAIL_PATTERN.match(candidate) is not None


def normalise_email(value: object) -> str | None:
    """Return the lowercased, stripped form of ``value`` if it is a valid
    email; otherwise ``None``.

    Used by the dispatcher to canonicalise each recipient before
    deduping. Returning ``None`` makes invalid entries trivially
    filterable with ``filter(None, …)``.
    """

    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if not candidate:
        return None
    if EMAIL_PATTERN.match(candidate) is None:
        return None
    return candidate


def normalise_review_emails(raw: Any) -> tuple[str, ...]:
    """Normalise the ``reviewEmails`` field from agency defaults.

    Accepted shapes:

    * ``list[str]`` (canonical, written by the chip editor in front #26).
    * ``str`` (legacy CSV from the early mock — split by comma, trim).
    * Anything else (``None``, ``int``, ``dict``, ...) → empty tuple.

    Returns a tuple of lowercased, deduped, syntactically-valid emails
    in **first-seen order** so deterministic ordering is preserved for
    tests and console output.
    """

    candidates: Iterable[object]
    if isinstance(raw, str):
        candidates = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        candidates = raw
    else:
        return ()

    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        normalised = normalise_email(candidate)
        if normalised is None or normalised in seen:
            continue
        seen.add(normalised)
        ordered.append(normalised)
    return tuple(ordered)


__all__ = [
    "EMAIL_PATTERN",
    "is_valid_email",
    "normalise_email",
    "normalise_review_emails",
]
