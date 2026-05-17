"""Unit tests for the ``reviewEmails`` normaliser (feature 27).

Covers the contract documented in
``progress/design_email_notifications_and_brand_customisation.md`` §A.4
and the dispatcher path in
``modules.notifications.application.use_cases.dispatch_review_requested_email``.
"""

from __future__ import annotations

from shared.email.validators import (
    is_valid_email,
    normalise_email,
    normalise_review_emails,
)


def test_csv_string_is_split_and_normalised() -> None:
    assert normalise_review_emails("a@x.com, B@Y.com") == ("a@x.com", "b@y.com")


def test_csv_string_strips_whitespace_around_each_value() -> None:
    assert normalise_review_emails(" a@x.com ,\tb@y.com\n") == ("a@x.com", "b@y.com")


def test_array_input_is_lowercased_and_returned_in_first_seen_order() -> None:
    raw = ["Ops@Example.com", "boss@example.com"]
    assert normalise_review_emails(raw) == ("ops@example.com", "boss@example.com")


def test_dedup_is_case_insensitive() -> None:
    raw = ["a@x.com", "A@X.com", "a@x.com"]
    assert normalise_review_emails(raw) == ("a@x.com",)


def test_invalid_entries_are_dropped_silently() -> None:
    raw = ["not-an-email", "valid@x.com", "@no-local.com", "missing-at.com"]
    assert normalise_review_emails(raw) == ("valid@x.com",)


def test_empty_and_none_and_int_yield_empty_tuple() -> None:
    assert normalise_review_emails(None) == ()
    assert normalise_review_emails("") == ()
    assert normalise_review_emails([]) == ()
    assert normalise_review_emails(0) == ()
    assert normalise_review_emails(123) == ()
    assert normalise_review_emails({"key": "value"}) == ()


def test_mixed_array_with_non_strings_skips_non_strings() -> None:
    assert normalise_review_emails(["a@x.com", 42, None, "b@y.com"]) == (
        "a@x.com",
        "b@y.com",
    )


def test_is_valid_email_basic_truth_table() -> None:
    assert is_valid_email("a@x.com") is True
    assert is_valid_email("nested.label@sub.example.co.uk") is True
    assert is_valid_email("not-an-email") is False
    assert is_valid_email("@nope.com") is False
    assert is_valid_email("nope@.com") is False  # domain must start with non-dot
    assert is_valid_email("nope@nope") is False
    assert is_valid_email(None) is False
    assert is_valid_email(123) is False
    assert is_valid_email("") is False
    assert is_valid_email("   ") is False


def test_normalise_email_returns_canonical_form_or_none() -> None:
    assert normalise_email("Foo@Example.COM") == "foo@example.com"
    assert normalise_email("  Foo@Example.COM  ") == "foo@example.com"
    assert normalise_email("not-valid") is None
    assert normalise_email(None) is None
