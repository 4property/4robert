"""Unit tests for ``compute_next_publish_slot``.

Feature 11 introduced this pure use case with five canonical scenarios
(immediate publish, before window, after window, off-day, empty rules).
Feature 14 extended it with:

* ``agency_timezone`` kwarg (IANA, fallback UTC with WARNING log).
* ``hold_window_seconds`` on ``AutomationRules`` (delay before the slot).
* ``quiet_hours_enabled`` toggle — the legacy "window = allowed hours"
  semantics now only applies when this flag is ``True``. Pre-feature-13
  rows have it as ``False`` so the previous "defer outside the window"
  behaviour is silenced until the user opts in from the Automation UI.
* ``skip_weekends`` toggle — Saturday/Sunday local advance to the next
  allowed weekday at ``publish_window_start``.

The use case stays pure (no UoW, no I/O), so tests pin the function on
a fixed ``now_utc`` and assert the returned ``datetime`` (or ``None``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from modules.configuration.application.use_cases.compute_next_publish_slot import (
    compute_next_publish_slot,
)
from modules.configuration.domain import AutomationRules


def _rules(
    *,
    publish_window_start: str = "09:00",
    publish_window_end: str = "17:00",
    publish_days: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri"),
    hold_window_seconds: int = 0,
    quiet_hours_enabled: bool = False,
    skip_weekends: bool = False,
) -> AutomationRules:
    return AutomationRules(
        agency_id="agency-1",
        approval_required=False,
        publish_window_start=publish_window_start,
        publish_window_end=publish_window_end,
        publish_days=publish_days,
        trigger_on_status=("for_sale",),
        hold_window_seconds=hold_window_seconds,
        quiet_hours_enabled=quiet_hours_enabled,
        skip_weekends=skip_weekends,
        created_at="",
        updated_at="",
    )


# ---------------------------------------------------------------------------
# Legacy feature-11 cases — preserved semantics when ``quiet_hours_enabled``
# is ``True`` (the only mode that still interprets the window as "allowed
# hours"). The 2026-05-13 fixture is a Wednesday; 2026-05-16 is a Saturday;
# 2026-05-18 is a Monday.
# ---------------------------------------------------------------------------


def test_rules_none_returns_none() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    assert compute_next_publish_slot(None, now) is None


def test_empty_window_start_returns_none_when_quiet_hours_enabled() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    rules = _rules(publish_window_start="", quiet_hours_enabled=True)
    assert compute_next_publish_slot(rules, now) is None


def test_empty_publish_days_returns_none_when_quiet_hours_enabled() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    rules = _rules(publish_days=(), quiet_hours_enabled=True)
    assert compute_next_publish_slot(rules, now) is None


def test_inside_window_on_valid_day_returns_none() -> None:
    # Wednesday, 10:00 UTC, window 09:00-17:00, Mon-Fri.
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    rules = _rules(quiet_hours_enabled=True)
    assert compute_next_publish_slot(rules, now) is None


def test_inside_window_at_exact_start_returns_none() -> None:
    now = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)
    rules = _rules(quiet_hours_enabled=True)
    assert compute_next_publish_slot(rules, now) is None


def test_inside_window_at_exact_end_returns_none() -> None:
    now = datetime(2026, 5, 13, 17, 0, tzinfo=timezone.utc)
    rules = _rules(quiet_hours_enabled=True)
    assert compute_next_publish_slot(rules, now) is None


def test_before_window_same_day_returns_today_at_start() -> None:
    # Wednesday, 06:00 UTC, window 09:00-17:00 (interpreted in UTC),
    # Mon-Fri, quiet_hours_enabled=True.
    now = datetime(2026, 5, 13, 6, 0, tzinfo=timezone.utc)
    rules = _rules(quiet_hours_enabled=True)
    expected = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)
    assert compute_next_publish_slot(rules, now) == expected


def test_after_window_same_day_returns_next_valid_day_at_start() -> None:
    # Wednesday, 18:00 UTC, window 09:00-17:00, Mon-Fri.
    # Next valid day is Thursday 2026-05-14.
    now = datetime(2026, 5, 13, 18, 0, tzinfo=timezone.utc)
    rules = _rules(quiet_hours_enabled=True)
    expected = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    assert compute_next_publish_slot(rules, now) == expected


def test_off_day_returns_next_valid_day_at_start() -> None:
    # Saturday 2026-05-16, 10:00 UTC, Mon-Fri window.
    # Next valid day is Monday 2026-05-18 at 09:00 UTC.
    now = datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)
    rules = _rules(quiet_hours_enabled=True)
    expected = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    assert compute_next_publish_slot(rules, now) == expected


def test_off_day_friday_evening_skips_weekend() -> None:
    # Friday 2026-05-15, 22:00 UTC (after Friday window closes).
    # Mon-Fri window: next valid day is Monday 2026-05-18 at 09:00 UTC.
    now = datetime(2026, 5, 15, 22, 0, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="09:00",
        publish_window_end="17:00",
        publish_days=("mon", "tue", "wed", "thu", "fri"),
        quiet_hours_enabled=True,
    )
    expected = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
    assert compute_next_publish_slot(rules, now) == expected


def test_weekend_only_window_skips_weekdays() -> None:
    # Wednesday 2026-05-13, 10:00 UTC.
    # publish_days = (sat, sun): next valid is Saturday 2026-05-16.
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="11:00",
        publish_window_end="13:00",
        publish_days=("sat", "sun"),
        quiet_hours_enabled=True,
    )
    expected = datetime(2026, 5, 16, 11, 0, tzinfo=timezone.utc)
    assert compute_next_publish_slot(rules, now) == expected


def test_invalid_hh_mm_format_returns_none() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="9am",
        publish_window_end="17",
        quiet_hours_enabled=True,
    )
    assert compute_next_publish_slot(rules, now) is None


def test_invalid_hour_returns_none() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    rules = _rules(publish_window_start="25:00", quiet_hours_enabled=True)
    assert compute_next_publish_slot(rules, now) is None


def test_invalid_minute_returns_none() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    rules = _rules(publish_window_start="09:60", quiet_hours_enabled=True)
    assert compute_next_publish_slot(rules, now) is None


def test_unknown_weekday_strings_are_ignored() -> None:
    # Only "wed" survives normalisation; with current weekday Wed and
    # before-window time, we expect today at start.
    now = datetime(2026, 5, 13, 6, 0, tzinfo=timezone.utc)
    rules = _rules(publish_days=("bogus", "wed", ""), quiet_hours_enabled=True)
    expected = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)
    assert compute_next_publish_slot(rules, now) == expected


def test_now_without_tzinfo_is_treated_as_utc() -> None:
    naive_now = datetime(2026, 5, 13, 6, 0)
    rules = _rules(quiet_hours_enabled=True)
    expected = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)
    assert compute_next_publish_slot(rules, naive_now) == expected


def test_now_in_different_tz_is_converted_to_utc() -> None:
    # 2026-05-13 09:00 in UTC+02:00 == 2026-05-13 07:00 UTC, which is
    # before the 09:00 UTC window opens for the same-day Wednesday.
    aware_now = datetime(
        2026, 5, 13, 9, 0, tzinfo=timezone(timedelta(hours=2))
    )
    rules = _rules(quiet_hours_enabled=True)
    expected = datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc)
    assert compute_next_publish_slot(rules, aware_now) == expected


def test_wrap_around_window_inside_evening() -> None:
    # Wednesday, 23:00 UTC, window 22:00 → 06:00 (wrap-around). The
    # wrap-around window covers Wed publish_day, so this is inside.
    now = datetime(2026, 5, 13, 23, 0, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="22:00",
        publish_window_end="06:00",
        quiet_hours_enabled=True,
    )
    assert compute_next_publish_slot(rules, now) is None


def test_wrap_around_window_inside_early_morning() -> None:
    # Wednesday, 03:00 UTC, window 22:00 → 06:00. Treat as inside.
    now = datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="22:00",
        publish_window_end="06:00",
        quiet_hours_enabled=True,
    )
    assert compute_next_publish_slot(rules, now) is None


@pytest.mark.parametrize(
    "weekday_abbr,expected_weekday_int",
    [
        ("mon", 0),
        ("tue", 1),
        ("wed", 2),
        ("thu", 3),
        ("fri", 4),
        ("sat", 5),
        ("sun", 6),
    ],
)
def test_weekday_mapping_round_trip(
    weekday_abbr: str, expected_weekday_int: int
) -> None:
    # If today's weekday matches the only configured day, and we are
    # before the window, we get today at start.
    # 2026-05-13 is Wednesday (weekday 2). Pick a base date matching.
    base = datetime(2026, 5, 11, tzinfo=timezone.utc)  # Monday
    while base.weekday() != expected_weekday_int:
        base = base.replace(day=base.day + 1)
    now_before = base.replace(hour=6, minute=0)
    rules = _rules(publish_days=(weekday_abbr,), quiet_hours_enabled=True)
    expected = base.replace(hour=9, minute=0)
    assert compute_next_publish_slot(rules, now_before) == expected


# ---------------------------------------------------------------------------
# Feature 14 — new semantics
# ---------------------------------------------------------------------------


def test_all_toggles_off_returns_none_immediate_publish() -> None:
    """Pre-feature-13 contract: with every toggle off the slot is None.

    Even though feature 11 historically would have deferred a request
    that fell outside ``publish_window_start/end``, that behaviour now
    requires ``quiet_hours_enabled=True``. With all three feature-13
    flags off the use case returns ``None`` so the caller publishes
    immediately.
    """
    now = datetime(2026, 5, 13, 23, 0, tzinfo=timezone.utc)  # outside 09:00-17:00
    rules = _rules()  # everything off
    assert compute_next_publish_slot(rules, now) is None


def test_hold_window_only_returns_now_plus_delta_utc() -> None:
    """A pure hold without quiet hours or skip weekends just delays."""
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    rules = _rules(hold_window_seconds=3600)
    expected = datetime(2026, 5, 13, 11, 0, tzinfo=timezone.utc)
    assert compute_next_publish_slot(rules, now) == expected


def test_hold_window_capped_at_24h() -> None:
    """Values above 86_400 are clamped defensively to 24 h."""
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    rules = _rules(hold_window_seconds=10_000_000)
    expected = now + timedelta(seconds=86_400)
    assert compute_next_publish_slot(rules, now) == expected


def test_hold_window_exactly_24h_is_honoured() -> None:
    """``hold_window_seconds == 86_400`` is the maximum allowed delay."""
    now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    rules = _rules(hold_window_seconds=86_400)
    expected = now + timedelta(seconds=86_400)
    assert compute_next_publish_slot(rules, now) == expected


def test_quiet_hours_dublin_evening_defers_to_next_morning() -> None:
    """Quiet hours 22:00→07:00 Dublin defer a Tue 23:30 local request.

    May is BST (UTC+1) in Dublin, so Tue 23:30 local == Tue 22:30 UTC.
    The next allowed start time is Wed 07:00 Dublin == Wed 06:00 UTC.
    ``publish_window_start=07:00``, ``publish_window_end=22:00``.
    """
    # Tue 2026-05-12 23:30 Dublin → 22:30 UTC.
    now = datetime(2026, 5, 12, 22, 30, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="07:00",
        publish_window_end="22:00",
        quiet_hours_enabled=True,
        publish_days=("mon", "tue", "wed", "thu", "fri"),
    )
    expected_local = datetime(
        2026, 5, 13, 7, 0, tzinfo=ZoneInfo("Europe/Dublin")
    )
    expected_utc = expected_local.astimezone(timezone.utc)
    assert (
        compute_next_publish_slot(
            rules, now, agency_timezone="Europe/Dublin"
        )
        == expected_utc
    )


def test_hold_window_plus_quiet_hours_dublin_BST() -> None:
    """Hold + quiet hours combine in agency local time (Dublin BST).

    May is BST (UTC+1). ``now_utc = 2026-05-12 20:30 UTC`` → Dublin
    21:30. Add 1 h hold → Dublin 22:30, which is outside
    ``[07:00, 22:00]`` → defer to next 07:00 Dublin (Wed 06:00 UTC).
    """
    now = datetime(2026, 5, 12, 20, 30, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="07:00",
        publish_window_end="22:00",
        hold_window_seconds=3600,
        quiet_hours_enabled=True,
        publish_days=("mon", "tue", "wed", "thu", "fri"),
    )
    expected_local = datetime(
        2026, 5, 13, 7, 0, tzinfo=ZoneInfo("Europe/Dublin")
    )
    expected_utc = expected_local.astimezone(timezone.utc)
    assert (
        compute_next_publish_slot(
            rules, now, agency_timezone="Europe/Dublin"
        )
        == expected_utc
    )


def test_skip_weekends_saturday_morning_dublin_advances_to_monday() -> None:
    """Sat 10:00 Dublin → next Mon at 09:00 Dublin local."""
    # Sat 2026-05-16 10:00 Dublin BST → 09:00 UTC.
    now = datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="09:00",
        publish_window_end="17:00",
        publish_days=("mon", "tue", "wed", "thu", "fri"),
        skip_weekends=True,
    )
    expected_local = datetime(
        2026, 5, 18, 9, 0, tzinfo=ZoneInfo("Europe/Dublin")
    )
    expected_utc = expected_local.astimezone(timezone.utc)
    assert (
        compute_next_publish_slot(
            rules, now, agency_timezone="Europe/Dublin"
        )
        == expected_utc
    )


def test_skip_weekends_friday_evening_plus_hold_lands_on_monday() -> None:
    """Friday 23:00 Dublin + 2 h hold → Sat 01:00 → next Mon at start.

    Hold lands on Saturday local → ``skip_weekends`` shifts the slot
    forward to the next allowed weekday (Monday) at
    ``publish_window_start``.
    """
    # Fri 2026-05-15 23:00 Dublin BST → 22:00 UTC.
    now = datetime(2026, 5, 15, 22, 0, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="09:00",
        publish_window_end="17:00",
        publish_days=("mon", "tue", "wed", "thu", "fri"),
        hold_window_seconds=7200,  # 2 h → target Sat 01:00 Dublin.
        skip_weekends=True,
    )
    expected_local = datetime(
        2026, 5, 18, 9, 0, tzinfo=ZoneInfo("Europe/Dublin")
    )
    expected_utc = expected_local.astimezone(timezone.utc)
    assert (
        compute_next_publish_slot(
            rules, now, agency_timezone="Europe/Dublin"
        )
        == expected_utc
    )


def test_quiet_hours_enabled_with_empty_publish_days_returns_none() -> None:
    """No allowed days → caller falls back to immediate publish."""
    now = datetime(2026, 5, 13, 23, 0, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="09:00",
        publish_window_end="17:00",
        publish_days=(),
        quiet_hours_enabled=True,
    )
    assert (
        compute_next_publish_slot(
            rules, now, agency_timezone="Europe/Dublin"
        )
        is None
    )


def test_invalid_agency_timezone_falls_back_to_utc_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Garbage IANA string → UTC fallback + WARNING in the log."""
    # Wed 2026-05-13 18:00 UTC, window 09:00-17:00 Mon-Fri, quiet hours
    # enabled. With a valid timezone of UTC the slot would be Thursday
    # 09:00 UTC. With "garbage_not_iana" we expect the same answer.
    now = datetime(2026, 5, 13, 18, 0, tzinfo=timezone.utc)
    rules = _rules(quiet_hours_enabled=True)
    expected = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    with caplog.at_level(logging.WARNING):
        result = compute_next_publish_slot(
            rules, now, agency_timezone="garbage_not_iana"
        )
    assert result == expected
    matching = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING
        and "garbage_not_iana" in record.getMessage()
    ]
    assert matching, "Expected a WARNING log for the invalid timezone."


def test_dst_spring_forward_ambiguous_local_time_is_safe() -> None:
    """A target that lands on a Dublin spring-forward gap must not crash.

    Dublin's 2026-03-29 ``01:30`` local does not exist (clocks jump from
    01:00 to 02:00). The use case must either land on a valid local
    instant or fall back gracefully — never raise. We assert the result
    is a UTC-aware datetime (the slot moved past the gap) without
    pinning the exact value, since CPython's ZoneInfo policy treats the
    nonexistent local hour by adding the DST offset.
    """
    # now_utc = 2026-03-29 01:30 UTC. With a 0 s hold the target lands
    # at the same UTC instant; converted to Dublin local this falls
    # inside the DST gap. Quiet hours 09:00–17:00 push us to the next
    # allowed start at 09:00 local that day.
    now = datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="09:00",
        publish_window_end="17:00",
        publish_days=("sun",),  # Allow Sunday so today is valid.
        quiet_hours_enabled=True,
    )
    result = compute_next_publish_slot(
        rules, now, agency_timezone="Europe/Dublin"
    )
    assert result is not None
    assert result.tzinfo is timezone.utc or result.utcoffset() == timedelta(0)


def test_skip_weekends_with_empty_publish_days_returns_none() -> None:
    """``skip_weekends`` cannot anchor a slot without a publish_window."""
    now = datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)  # Saturday
    rules = _rules(
        publish_window_start="",  # no anchor
        publish_window_end="",
        publish_days=("mon", "tue"),
        skip_weekends=True,
    )
    assert (
        compute_next_publish_slot(
            rules, now, agency_timezone="Europe/Dublin"
        )
        is None
    )


def test_quiet_hours_inside_window_at_local_noon_returns_none() -> None:
    """Wed 12:00 Dublin local is inside 09:00–17:00 → immediate."""
    # 12:00 Dublin BST == 11:00 UTC.
    now = datetime(2026, 5, 13, 11, 0, tzinfo=timezone.utc)
    rules = _rules(
        publish_window_start="09:00",
        publish_window_end="17:00",
        publish_days=("mon", "tue", "wed", "thu", "fri"),
        quiet_hours_enabled=True,
    )
    assert (
        compute_next_publish_slot(
            rules, now, agency_timezone="Europe/Dublin"
        )
        is None
    )
