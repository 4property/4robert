"""Unit tests for ``apps.api.admin_auth.build_admin_access_policy``."""

from __future__ import annotations

from apps.api.admin_auth import AdminAccessPolicy, build_admin_access_policy


def test_build_admin_access_policy_normalises_none_token() -> None:
    policy = build_admin_access_policy(
        enabled=True,
        base_path="/v1/admin",
        bearer_token=None,
        disable_auth_for_testing=False,
    )
    assert isinstance(policy, AdminAccessPolicy)
    assert policy.bearer_token == ""
    assert policy.enabled is True
    assert policy.base_path == "/v1/admin"
    assert policy.disable_auth_for_testing is False


def test_build_admin_access_policy_coerces_truthiness() -> None:
    policy = build_admin_access_policy(
        enabled=1,  # truthy non-bool
        base_path="/admin",
        bearer_token="abc",
        disable_auth_for_testing=1,
    )
    assert policy.enabled is True
    assert policy.disable_auth_for_testing is True
    assert policy.bearer_token == "abc"
