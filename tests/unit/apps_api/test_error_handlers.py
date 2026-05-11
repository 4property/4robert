"""Unit tests for the structured JSON error handlers."""

from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.error_handlers import json_error, register_error_handlers
from shared.errors import (
    ApplicationError,
    PipelineError,
    ResourceNotFoundError,
    ValidationError,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raise/validation")
    async def raise_validation():  # type: ignore[no-untyped-def]
        raise ValidationError(
            "Bad input.",
            code="BAD_PAYLOAD",
            hint="Send a JSON object.",
            context={"field": "name"},
        )

    @app.get("/raise/not-found")
    async def raise_not_found():  # type: ignore[no-untyped-def]
        raise ResourceNotFoundError(
            "Reel missing.",
            context={"reel_id": "abc"},
        )

    @app.get("/raise/pipeline")
    async def raise_pipeline():  # type: ignore[no-untyped-def]
        raise PipelineError(
            "Boom.",
            stage="render",
            code="RENDER_FAILED",
            retryable=True,
            external_trace_id="trace-123",
        )

    @app.get("/raise/application")
    async def raise_application():  # type: ignore[no-untyped-def]
        raise ApplicationError(
            "Plain failure.",
            hint="Restart the service.",
        )

    return app


class JsonErrorTests(unittest.TestCase):
    def test_payload_only_includes_provided_fields(self) -> None:
        response = json_error(404, "Not found.")
        self.assertEqual(response.status_code, 404)
        body = response.body
        self.assertIn(b'"error":"Not found."', body)
        self.assertNotIn(b"code", body)
        self.assertNotIn(b"hint", body)
        self.assertNotIn(b"details", body)

    def test_payload_includes_all_optional_fields_when_present(self) -> None:
        response = json_error(
            400,
            "Bad payload.",
            code="BAD_PAYLOAD",
            hint="Try again.",
            details={"path": "/x"},
        )
        self.assertEqual(response.status_code, 400)
        body = response.body
        self.assertIn(b'"code":"BAD_PAYLOAD"', body)
        self.assertIn(b'"hint":"Try again."', body)
        self.assertIn(b'"details":{"path":"/x"}', body)


class RegisterErrorHandlersTests(unittest.TestCase):
    def test_validation_error_returns_400_with_canonical_shape(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)
        response = client.get("/raise/validation")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"], "Bad input.")
        self.assertEqual(body["code"], "BAD_PAYLOAD")
        self.assertEqual(body["hint"], "Send a JSON object.")
        self.assertIn("details", body)
        self.assertEqual(body["details"]["context"], {"field": "name"})
        self.assertEqual(body["details"]["stage"], "validation")
        self.assertEqual(body["details"]["retryable"], False)

    def test_resource_not_found_returns_404(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)
        response = client.get("/raise/not-found")
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(body["error"], "Reel missing.")
        self.assertEqual(body["code"], "RESOURCE_NOT_FOUND")
        self.assertEqual(body["details"]["context"], {"reel_id": "abc"})

    def test_pipeline_error_returns_500_with_stage_and_retryable(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)
        response = client.get("/raise/pipeline")
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"], "Boom.")
        self.assertEqual(body["code"], "RENDER_FAILED")
        self.assertEqual(body["details"]["stage"], "render")
        self.assertEqual(body["details"]["retryable"], True)
        self.assertEqual(body["details"]["external_trace_id"], "trace-123")

    def test_plain_application_error_still_returns_canonical_json(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)
        response = client.get("/raise/application")
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"], "Plain failure.")
        self.assertEqual(body["hint"], "Restart the service.")
        self.assertNotIn("code", body)


if __name__ == "__main__":
    unittest.main()
