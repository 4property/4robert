"""Compute the next valid publish slot for a given automation window.

Pure function with no UoW and no I/O. Given an :class:`AutomationRules`
record, the current UTC instant and the owning agency's IANA timezone,
returns the next ``datetime`` (UTC) at which a publish job is allowed to
fire, or ``None`` if the job should publish immediately.

Semantics (feature 14, supersedes feature 11):

The behaviour is driven by three independent toggles on the automation
record (added in feature 13) plus the legacy
``publish_window_start`` / ``publish_window_end`` / ``publish_days``
that survived feature 13:

* ``hold_window_seconds`` (0..86400) — wait this many seconds from
  ``now_utc`` before considering the slot. ``0`` means "no hold".
* ``quiet_hours_enabled`` — when ``True`` the
  ``[publish_window_start, publish_window_end]`` interval (in agency
  local time) is the only window during which publication is allowed;
  anything that lands outside is deferred to the next valid start. When
  ``False`` the window is ignored — the legacy feature-11 behaviour where
  the window was implicitly "allowed hours" is **no longer** the
  default. Rows existing before feature 13 get
  ``quiet_hours_enabled=False`` from the migration, which silences the
  legacy deferral until the user opts in from the Automation UI.
* ``skip_weekends`` — when ``True``, Saturday and Sunday local are
  skipped to the next Monday at ``publish_window_start``. ``publish_days``
  is still honoured on top: if Monday is not in ``publish_days`` the
  shift keeps walking forward.

Algorithm (orden estricto):

1. ``rules is None`` → ``None``.
2. ``hold = clamp(int(rules.hold_window_seconds or 0), 0, 86400)``.
3. ``target_utc = now_utc + timedelta(seconds=hold)``.
4. Resolve the agency timezone via :class:`zoneinfo.ZoneInfo`. Any
   invalid IANA string, missing tzdata or unexpected error falls back
   to UTC with a ``logger.warning`` so the approve flow never crashes.
5. ``target_local = target_utc.astimezone(tz)``.
6. If ``rules.skip_weekends`` and ``target_local.weekday() in (5, 6)``,
   advance to the next Monday at ``publish_window_start`` (or to the
   next day in ``publish_days`` if Monday is not allowed).
7. If ``rules.quiet_hours_enabled`` and ``target_local.time()`` is
   outside ``[publish_window_start, publish_window_end]`` (supports
   wrap-around windows like 22:00 → 07:00), advance to the next valid
   ``publish_window_start`` respecting ``publish_days``.
8. If all three feature-13 toggles are off (``hold==0``,
   ``quiet_hours_enabled=False``, ``skip_weekends=False``) → ``None``
   (immediate publish — pre-feature-13 contract).
9. If after every shift the resulting UTC instant equals ``now_utc``,
   return ``None`` (no actual wait → immediate publish).
10. Otherwise return ``target_local.astimezone(timezone.utc)``.

The helpers :func:`_parse_hh_mm` and :func:`_normalise_publish_days`
remain unchanged so feature 11 callers that only relied on them keep
their semantics. Malformed ``HH:MM`` collapses the quiet-hours shift to
``None`` for that specific check (defensive — never crash the approve
flow on bad payloads).
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.configuration.domain import AutomationRules


logger = logging.getLogger(__name__)


# Map of weekday three-letter lowercase abbreviations → ``datetime.weekday()``
# integers (Monday = 0, Sunday = 6). Kept module-local since there is no
# canonical enum elsewhere in the repo (the spike confirmed this).
_WEEKDAY_INDEX: dict[str, int] = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


# Defensive upper bound on ``hold_window_seconds`` — the payload already
# rejects values outside ``[0, 86400]`` with 422, but we re-clamp here so
# direct callers (tests, future workers) cannot push the slot more than
# 24 h into the future.
_HOLD_WINDOW_MAX_SECONDS: int = 86400


def _parse_hh_mm(value: str) -> time | None:
    """Parse a ``"HH:MM"`` 24h string into a :class:`time` instance.

    Returns ``None`` on any malformed input (empty, wrong shape, out of
    range). The caller treats ``None`` as "no schedule".
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or ":" not in text:
        return None
    head, _, tail = text.partition(":")
    try:
        hour = int(head)
        minute = int(tail)
    except ValueError:
        return None
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def _normalise_publish_days(publish_days: tuple[str, ...] | list[str]) -> tuple[int, ...]:
    """Translate weekday names into their ``datetime.weekday()`` integers.

    Unknown or empty entries are silently dropped. Duplicates collapse
    to a single value. Returns an empty tuple if no valid weekday
    survives normalisation.
    """
    seen: set[int] = set()
    indices: list[int] = []
    for raw_day in publish_days or ():
        if not isinstance(raw_day, str):
            continue
        index = _WEEKDAY_INDEX.get(raw_day.strip().lower())
        if index is None or index in seen:
            continue
        seen.add(index)
        indices.append(index)
    return tuple(indices)


def _resolve_timezone(agency_timezone: str) -> ZoneInfo:
    """Return a :class:`ZoneInfo` for ``agency_timezone`` or UTC on error.

    Any failure (invalid IANA string, missing system tzdata, unexpected
    runtime error) is logged at WARNING level and the function falls
    back to UTC. The approve flow must never crash on a bad agency
    timezone string.
    """
    try:
        return ZoneInfo(str(agency_timezone or "UTC").strip() or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        logger.warning(
            "compute_next_publish_slot: invalid agency_timezone %r → falling back to UTC (%s).",
            agency_timezone,
            exc,
        )
        return ZoneInfo("UTC")


def _coerce_hold_window_seconds(raw_value: object) -> int:
    """Clamp ``rules.hold_window_seconds`` into ``[0, 86400]``."""
    try:
        value = int(raw_value or 0)
    except (TypeError, ValueError):
        return 0
    if value < 0:
        return 0
    if value > _HOLD_WINDOW_MAX_SECONDS:
        return _HOLD_WINDOW_MAX_SECONDS
    return value


def _next_allowed_day_at_start(
    *,
    after_local: datetime,
    publish_day_indices: tuple[int, ...],
    start_time: time,
    include_after: bool = False,
) -> datetime | None:
    """Advance ``after_local`` to the next day in ``publish_day_indices``.

    If ``include_after`` is ``True`` and ``after_local``'s weekday is in
    ``publish_day_indices``, returns the same date at ``start_time``.
    Otherwise walks forward up to 7 days. Returns ``None`` if
    ``publish_day_indices`` is empty.
    """
    if not publish_day_indices:
        return None
    base_date = after_local.date()
    tz = after_local.tzinfo
    if include_after and after_local.weekday() in publish_day_indices:
        return datetime.combine(base_date, start_time, tzinfo=tz)
    for offset in range(1, 8):
        candidate_date = base_date + timedelta(days=offset)
        if candidate_date.weekday() in publish_day_indices:
            return datetime.combine(candidate_date, start_time, tzinfo=tz)
    return None


def _is_inside_quiet_hours_window(
    *,
    moment: time,
    start_time: time,
    end_time: time,
) -> bool:
    """``True`` if ``moment`` falls inside ``[start_time, end_time]``.

    Supports wrap-around windows (start > end, e.g. 22:00 → 07:00) the
    same way feature 11 did.
    """
    if start_time <= end_time:
        return start_time <= moment <= end_time
    # Wrap-around: window covers ``[start_time, 23:59]`` ∪ ``[00:00, end_time]``.
    return moment >= start_time or moment <= end_time


def compute_next_publish_slot(
    rules: AutomationRules | None,
    now_utc: datetime,
    *,
    agency_timezone: str = "UTC",
) -> datetime | None:
    """Return the next valid publish slot for ``rules`` given ``now_utc``.

    See the module docstring for the full semantics. The function is
    pure: no UoW, no I/O, deterministic given its arguments (except for
    the WARNING side-effect on invalid ``agency_timezone``).
    """
    if rules is None:
        return None

    # Step 2: clamp hold window.
    hold_window_seconds = _coerce_hold_window_seconds(
        getattr(rules, "hold_window_seconds", 0)
    )

    # Step 3: ensure ``now_utc`` is UTC-aware, then apply hold.
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)
    target_utc = now_utc + timedelta(seconds=hold_window_seconds)

    quiet_hours_enabled = bool(getattr(rules, "quiet_hours_enabled", False))
    skip_weekends = bool(getattr(rules, "skip_weekends", False))

    # Step 8 (early): if no toggle is engaged we preserve the
    # pre-feature-13 "immediate publish" contract regardless of the
    # legacy ``publish_window_*`` settings.
    if hold_window_seconds == 0 and not quiet_hours_enabled and not skip_weekends:
        return None

    # Step 4: resolve agency timezone (with safe fallback).
    tz = _resolve_timezone(agency_timezone)

    # Step 5: convert the target to agency local time.
    target_local = target_utc.astimezone(tz)

    start_time = _parse_hh_mm(getattr(rules, "publish_window_start", "") or "")
    end_time = _parse_hh_mm(getattr(rules, "publish_window_end", "") or "")
    publish_day_indices = _normalise_publish_days(
        getattr(rules, "publish_days", ()) or ()
    )

    # Step 6: skip_weekends shift. We avoid the shift only if there is no
    # valid ``publish_window_start`` to anchor the new slot to — without
    # a start the caller cannot honour the wait and we fall through to
    # the immediate-publish contract.
    if skip_weekends and target_local.weekday() in (5, 6):
        if start_time is None or not publish_day_indices:
            # No anchor → preserve feature-13 "no schedule" semantics.
            return None
        # Walk forward to the next allowed weekday (Monday at start, or
        # later if Monday is excluded from ``publish_days``).
        next_slot_local = _next_allowed_day_at_start(
            after_local=target_local,
            publish_day_indices=publish_day_indices,
            start_time=start_time,
            include_after=False,
        )
        if next_slot_local is None:
            return None
        target_local = next_slot_local

    # Step 7: quiet hours shift.
    if quiet_hours_enabled:
        if (
            start_time is None
            or end_time is None
            or not publish_day_indices
        ):
            # The window or the publish_days list is malformed/empty.
            # Preserve the legacy "no schedule" semantics — caller will
            # publish immediately.
            return None
        # First make sure the current weekday is itself allowed.
        if target_local.weekday() not in publish_day_indices:
            shifted = _next_allowed_day_at_start(
                after_local=target_local,
                publish_day_indices=publish_day_indices,
                start_time=start_time,
                include_after=False,
            )
            if shifted is None:
                return None
            target_local = shifted
        # Re-check the time-of-day after any weekday shift.
        if not _is_inside_quiet_hours_window(
            moment=target_local.time().replace(microsecond=0),
            start_time=start_time,
            end_time=end_time,
        ):
            # Outside the allowed window today → advance to the next
            # valid weekday at ``start_time``. We use ``include_after``
            # only when the *current* day is still allowed AND the
            # window opens later today; otherwise we always walk forward.
            same_day_start = datetime.combine(
                target_local.date(), start_time, tzinfo=target_local.tzinfo
            )
            if (
                target_local.weekday() in publish_day_indices
                and same_day_start > target_local
            ):
                target_local = same_day_start
            else:
                shifted = _next_allowed_day_at_start(
                    after_local=target_local,
                    publish_day_indices=publish_day_indices,
                    start_time=start_time,
                    include_after=False,
                )
                if shifted is None:
                    return None
                target_local = shifted

    # Step 9: collapse to ``None`` if no actual wait was introduced.
    resolved_utc = target_local.astimezone(timezone.utc)
    if resolved_utc == now_utc:
        return None
    return resolved_utc


__all__ = ["compute_next_publish_slot"]
