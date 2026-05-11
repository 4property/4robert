"""Unit tests for apps.api.host_filter."""

from __future__ import annotations

from apps.api.host_filter import (
    is_local_docs_host,
    looks_like_hostname,
    normalise_allowed_host,
    resolve_allowed_hosts,
    should_enable_docs,
)


def test_normalise_allowed_host_strips_scheme_and_port() -> None:
    assert normalise_allowed_host("https://Example.com/api") == "example.com"
    assert normalise_allowed_host("foo.bar:8080") == "foo.bar"
    assert normalise_allowed_host("*") == "*"


def test_normalise_allowed_host_returns_none_for_blank() -> None:
    assert normalise_allowed_host("") is None
    assert normalise_allowed_host("   ") is None


def test_looks_like_hostname_matches_domains_localhost_and_wildcards() -> None:
    assert looks_like_hostname("ckp.ie") is True
    assert looks_like_hostname("localhost") is True
    assert looks_like_hostname("*.example.com") is True
    assert looks_like_hostname("not-a-host") is False


def test_resolve_allowed_hosts_dedups_and_appends_localhost() -> None:
    result = resolve_allowed_hosts(
        allowed_hosts=("example.com", "Example.COM"),
        site_secrets={"acme.example": "secret", "not-a-host": "secret"},
    )
    assert result == ("example.com", "acme.example", "127.0.0.1", "localhost")


def test_should_enable_docs_returns_true_when_explicitly_enabled() -> None:
    assert should_enable_docs(host="prod.example", enable_docs=True) is True


def test_should_enable_docs_returns_true_for_local_hosts() -> None:
    assert should_enable_docs(host="127.0.0.1", enable_docs=False) is True
    assert should_enable_docs(host="localhost", enable_docs=False) is True


def test_should_enable_docs_returns_false_for_remote_hosts() -> None:
    assert should_enable_docs(host="prod.example", enable_docs=False) is False


def test_is_local_docs_host_handles_brackets_and_url_form() -> None:
    assert is_local_docs_host("[::1]") is True
    assert is_local_docs_host("http://localhost") is True
    assert is_local_docs_host("") is False
