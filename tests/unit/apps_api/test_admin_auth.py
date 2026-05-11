"""Unit tests for the admin bearer-token authorization helper."""

from __future__ import annotations

import json
import unittest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from apps.api.admin_auth import (
    AdminAccessPolicy,
    authorize_admin_request,
    extract_bearer_token,
)


def _build_app(policy: AdminAccessPolicy) -> FastAPI:
    app = FastAPI()

    @app.get("/admin/ping")
    async def ping(request: Request) -> JSONResponse:
        request.state.request_id = "test-req"
        denial = authorize_admin_request(request, policy)
        if denial is not None:
            return denial
        return JSONResponse(status_code=200, content={"ok": True})

    return app


class ExtractBearerTokenTests(unittest.TestCase):
    def test_returns_token_for_well_formed_header(self) -> None:
        self.assertEqual(extract_bearer_token("Bearer abc.def"), "abc.def")
        self.assertEqual(extract_bearer_token("bearer abc"), "abc")

    def test_returns_none_for_missing_or_malformed_headers(self) -> None:
        self.assertIsNone(extract_bearer_token(None))
        self.assertIsNone(extract_bearer_token(""))
        self.assertIsNone(extract_bearer_token("Basic abc"))
        self.assertIsNone(extract_bearer_token("Bearer "))


class AuthorizeAdminRequestTests(unittest.TestCase):
    def test_happy_path_allows_request_with_valid_token(self) -> None:
        policy = AdminAccessPolicy(
            enabled=True,
            base_path="/v1/admin",
            bearer_token="secret-token",
            disable_auth_for_testing=False,
        )
        client = TestClient(_build_app(policy))
        response = client.get(
            "/admin/ping",
            headers={"Authorization": "Bearer secret-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_missing_authorization_header_returns_401(self) -> None:
        policy = AdminAccessPolicy(
            enabled=True,
            base_path="/v1/admin",
            bearer_token="secret-token",
            disable_auth_for_testing=False,
        )
        client = TestClient(_build_app(policy))
        response = client.get("/admin/ping")
        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertEqual(body["code"], "ADMIN_AUTH_REQUIRED")
        self.assertIn("error", body)
        self.assertIn("hint", body)

    def test_invalid_bearer_token_returns_401(self) -> None:
        policy = AdminAccessPolicy(
            enabled=True,
            base_path="/v1/admin",
            bearer_token="secret-token",
            disable_auth_for_testing=False,
        )
        client = TestClient(_build_app(policy))
        response = client.get(
            "/admin/ping",
            headers={"Authorization": "Bearer wrong-token"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "INVALID_ADMIN_TOKEN")

    def test_disabled_admin_api_returns_404(self) -> None:
        policy = AdminAccessPolicy(
            enabled=False,
            base_path="/v1/admin",
            bearer_token="",
            disable_auth_for_testing=False,
        )
        client = TestClient(_build_app(policy))
        response = client.get(
            "/admin/ping",
            headers={"Authorization": "Bearer anything"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "ADMIN_API_DISABLED")

    def test_unconfigured_admin_token_returns_503(self) -> None:
        policy = AdminAccessPolicy(
            enabled=True,
            base_path="/v1/admin",
            bearer_token="",
            disable_auth_for_testing=False,
        )
        client = TestClient(_build_app(policy))
        response = client.get(
            "/admin/ping",
            headers={"Authorization": "Bearer anything"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "ADMIN_API_NOT_CONFIGURED")

    def test_disable_auth_for_testing_bypasses_token_check(self) -> None:
        policy = AdminAccessPolicy(
            enabled=True,
            base_path="/v1/admin",
            bearer_token="",
            disable_auth_for_testing=True,
        )
        client = TestClient(_build_app(policy))
        response = client.get("/admin/ping")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_constant_time_comparison_uses_full_token(self) -> None:
        policy = AdminAccessPolicy(
            enabled=True,
            base_path="/v1/admin",
            bearer_token="real-token",
            disable_auth_for_testing=False,
        )
        client = TestClient(_build_app(policy))
        # Prefix match must still fail.
        response = client.get(
            "/admin/ping",
            headers={"Authorization": "Bearer real"},
        )
        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertEqual(body["code"], "INVALID_ADMIN_TOKEN")
        # Body must be valid JSON (sanity check on response shape).
        self.assertIsInstance(json.dumps(body), str)


if __name__ == "__main__":
    unittest.main()
